"""Isolated account recovery boundaries. SMTP is mocked; no real messages sent."""
import base64
import re
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from v162_number_inbox_contract import TestClient, app, create_session, db, init_db
from app import config, account_security as service
from app.security import password_hash, verify_login, get_session, encrypt_secret, decrypt_secret
from cryptography.fernet import Fernet


def nonce(response):
    return re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)


def main():
    config.APP_PASSWORD_SALT = base64.urlsafe_b64encode(b'account-fixture-salt').decode()
    config.APP_PASSWORD_HASH = password_hash('old-password', config.APP_PASSWORD_SALT)
    config.APP_ENCRYPTION_KEY = Fernet.generate_key().decode()
    key = config.APP_ENCRYPTION_KEY
    cipher = encrypt_secret('existing private business value')
    init_db()
    # Runtime migration must be borrowed-transaction safe and idempotent.
    try:
        with db() as conn:
            service.ensure_account_schema(conn)
            raise RuntimeError('rollback')
    except RuntimeError:
        pass
    with db() as conn:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='account_security'").fetchone() is None
        service.ensure_account_schema(conn)
        service.ensure_account_schema(conn)
    assert verify_login(config.APP_USERNAME, 'old-password')
    token, csrf, _ = create_session()
    client = TestClient(app)
    client.cookies.set('session_token', token)
    anonymous = TestClient(app)
    assert anonymous.get('/account/security', follow_redirects=False).status_code == 303
    for path in ['/account/password', '/account/email/request', '/account/email/confirm', '/account/sessions/revoke']:
        assert client.post(path, data={'csrf': 'bad'}).status_code == 403
    for path in ['/account/forgot', '/account/reset']:
        assert anonymous.get(path).status_code == 200
        assert anonymous.post(path, data={}).status_code == 403
    assert anonymous.post('/account/reset', content=b'x' * 17000).status_code == 413
    sent = []

    def send(email, code, purpose):
        sent.append((email, code, purpose))

    def post(path, **fields):
        return client.post(path, data={'csrf': csrf, **fields}, follow_redirects=False)

    def clear_limits():
        with db() as conn:
            conn.execute('DELETE FROM account_rate_limits')

    def make_resend_possible():
        clear_limits()
        with db() as conn:
            conn.execute('UPDATE account_email_challenges SET created=created-61')

    def request_reset(email='owner@example.test'):
        response = anonymous.get('/account/forgot')
        return anonymous.post('/account/forgot', data={'csrf': nonce(response), 'email': email})

    with patch('app.account_mail.send_code', side_effect=send), patch('app.account_routes.available', return_value=True):
        for _ in range(3):
            assert post('/account/email/request', current='wrong', email='owner@example.test').status_code == 400
        with db() as conn:
            assert conn.execute('SELECT MAX(count) FROM account_rate_limits').fetchone()[0] >= 3
        clear_limits()
        assert post('/account/email/request', current='old-password', email='owner@example.test').status_code == 200
        assert len(sent) == 1 and re.fullmatch('[0-9]{8}', sent[0][1])
        code = sent[-1][1]
        with db() as conn:
            row = conn.execute("SELECT * FROM account_email_challenges WHERE purpose='bind'").fetchone()
            assert code != row['digest'] and row['state'] == 'sent'
            assert service.account(conn)['recovery_email'] == ''
        assert post('/account/email/confirm', current='wrong', email='owner@example.test', code=code).status_code == 400
        assert post('/account/email/confirm', current='old-password', email='other@example.test', code=code).status_code == 400
        assert post('/account/email/confirm', current='old-password', email='owner@example.test', code=code).status_code == 200
        assert post('/account/email/confirm', current='old-password', email='owner@example.test', code=code).status_code == 400
        clear_limits()
        assert 'owner@example.test' in client.get('/account/security').text
        before = len(sent)
        unknown = request_reset('unknown@example.test')
        assert len(sent) == before
        known = request_reset()
        assert len(sent) == before + 1
        assert '如该邮箱已绑定' in unknown.text and '如该邮箱已绑定' in known.text
        assert 'owner@example.test' not in known.text
        request_reset()  # resend cooldown cannot replace or email another code
        assert len(sent) == before + 1
        reset_code = sent[-1][1]
        for _ in range(5):
            assert not service.reset_password('owner@example.test', 'invalid', 'new-password', 'new-password', 'guess-test')
        assert not service.reset_password('owner@example.test', reset_code, 'new-password', 'new-password', 'guess-test')
        assert verify_login(config.APP_USERNAME, 'old-password') and get_session(token)
        make_resend_possible()
        request_reset()
        with db() as conn:
            conn.execute("UPDATE account_email_challenges SET expires=0 WHERE purpose='reset'")
        assert not service.reset_password('owner@example.test', sent[-1][1], 'new-password', 'new-password', 'expiry-test')
        make_resend_possible()
        request_reset()
        reset_code = sent[-1][1]
        old_other, _, _ = create_session()
        # Two concurrent attempts at the same code: only one transaction may win.
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: service.reset_password('owner@example.test', reset_code,
                ' 新密码! ', ' 新密码! ', 'parallel-test'), range(2)))
        assert sorted(results) == [False, True], results
        assert not get_session(token) and not get_session(old_other)
        assert not verify_login(config.APP_USERNAME, 'old-password')
        assert verify_login(config.APP_USERNAME, ' 新密码! ')
        assert config.APP_ENCRYPTION_KEY == key and decrypt_secret(cipher) == 'existing private business value'
        assert client.get('/account/security', follow_redirects=False).status_code == 303
        # Log in via real POST, then invalidate another device while keeping this one.
        client.cookies.clear()
        logged = client.post('/login', data={'username': config.APP_USERNAME, 'password': ' 新密码! '}, follow_redirects=False)
        assert logged.status_code == 303
        csrf = nonce(client.get('/account/security'))
        other, _, _ = create_session()
        assert post('/account/sessions/revoke', current=' 新密码! ').status_code == 200
        assert not get_session(other) and client.get('/account/security').status_code == 200
        # Failure after credential/session writes must roll everything back.
        current_token = client.cookies.get('session_token')
        with patch('app.account_security.record_event', side_effect=RuntimeError('synthetic failure')):
            try:
                service.change_password(' 新密码! ', 'rolled-back', 'rolled-back', 'rollback-test')
            except RuntimeError:
                pass
            else:
                raise AssertionError('expected rollback')
        assert get_session(current_token) and verify_login(config.APP_USERNAME, ' 新密码! ')
        clear_limits()
        assert post('/account/password', current=' 新密码! ', password='final-password', confirmation='different').status_code == 400
        assert post('/account/password', current=' 新密码! ', password='final-password', confirmation='final-password').status_code == 303
        assert not get_session(current_token) and verify_login(config.APP_USERNAME, 'final-password')
        assert not verify_login(config.APP_USERNAME, ' 新密码! ')
        assert decrypt_secret(cipher) == 'existing private business value'
        with db() as conn:
            assert service.account(conn)['recovery_email'] == 'owner@example.test'
        # Failed transport cannot enable a challenge or mutate the credential.
        make_resend_possible()
        with patch('app.account_mail.send_code', side_effect=RuntimeError('private transport error')):
            response = request_reset()
        assert 'private transport error' not in response.text
        with db() as conn:
            assert conn.execute("SELECT state FROM account_email_challenges WHERE purpose='reset'").fetchone()[0] == 'failed'
        assert verify_login(config.APP_USERNAME, 'final-password')
    from app.account_mail import available
    with patch.dict('os.environ', {'ACCOUNT_SMTP_HOST':'smtp.example.test', 'ACCOUNT_SMTP_FROM':'mail@example.test',
                                 'ACCOUNT_SMTP_USE_SSL':'0', 'ACCOUNT_SMTP_STARTTLS':'0'}):
        assert not available(), 'plaintext recovery transport must be rejected'
    print('account security passed: legacy migration, CSRF, verified email, single-use expiry, retries, concurrent reset, session revocation, rollback and preserved encrypted data; mocked SMTP only')


if __name__ == '__main__':
    main()
