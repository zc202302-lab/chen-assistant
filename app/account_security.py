"""Single-owner credentials, verified recovery email and one-use email challenges.

The data encryption key and session signing key are never rotated here.
"""
import base64
import hmac
import re
import secrets
import time

from . import config
from .db import connection_scope, db, execute_schema

SCHEMA = '''
CREATE TABLE IF NOT EXISTS account_security (
 id INTEGER PRIMARY KEY CHECK(id=1), password_salt TEXT NOT NULL DEFAULT '',
 password_hash TEXT NOT NULL DEFAULT '', recovery_email TEXT NOT NULL DEFAULT '',
 revision INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO account_security(id) VALUES(1);
CREATE TABLE IF NOT EXISTS account_email_challenges (
 purpose TEXT PRIMARY KEY CHECK(purpose IN ('bind','reset')), email TEXT NOT NULL,
 digest TEXT NOT NULL, generation TEXT NOT NULL, created REAL NOT NULL,
 expires REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 state TEXT NOT NULL DEFAULT 'sending'
);
CREATE TABLE IF NOT EXISTS account_rate_limits (
 key TEXT PRIMARY KEY, started REAL NOT NULL, count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS account_security_events (
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL, occurred REAL NOT NULL
);
'''


def ensure_account_schema(conn=None):
    with connection_scope(conn) as active:
        execute_schema(active, SCHEMA)


def account(conn):
    # Existing tooling may call init_db without runtime migrations.
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='account_security'").fetchone()
    row = conn.execute('SELECT * FROM account_security WHERE id=1').fetchone() if exists else None
    record = dict(row) if row else {'password_salt': '', 'password_hash': '', 'recovery_email': '', 'revision': 0}
    if not record['password_salt']:
        record['password_salt'] = config.APP_PASSWORD_SALT
        record['password_hash'] = config.APP_PASSWORD_HASH
    return record


def password_matches(record, password):
    from .security import password_hash
    if not isinstance(password, str) or not 1 <= len(password) <= 512:
        return False
    try:
        return hmac.compare_digest(password_hash(password, record['password_salt']), record['password_hash'])
    except (ValueError, TypeError):
        return False


def generation(record):
    from .security import token_digest
    return token_digest('|'.join(str(record[k]) for k in ('password_salt', 'password_hash', 'recovery_email', 'revision')))


def normalize_email(value):
    value = str(value).strip()
    if len(value) > 254 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}", value):
        raise ValueError('请输入有效邮箱地址。')
    return value.lower()


def check_new_password(password, confirmation):
    if not 1 <= len(password) <= 512:
        raise ValueError('密码不能为空，最多512个字符。')
    if password != confirmation:
        raise ValueError('两次输入的新密码不一致。')


def limit(conn, label, identity, maximum=10, seconds=900):
    from .security import token_digest
    key = token_digest(label + ':' + identity)
    now = time.time()
    conn.execute('DELETE FROM account_rate_limits WHERE started<?', (now - 86400,))
    row = conn.execute('SELECT * FROM account_rate_limits WHERE key=?', (key,)).fetchone()
    if not row or row['started'] <= now - seconds:
        conn.execute('INSERT OR REPLACE INTO account_rate_limits VALUES(?,?,1)', (key, now))
        return True
    if row['count'] >= maximum:
        return False
    conn.execute('UPDATE account_rate_limits SET count=count+1 WHERE key=?', (key,))
    return True


def record_event(conn, kind):
    conn.execute('INSERT INTO account_security_events(kind,occurred) VALUES(?,?)', (kind, time.time()))
    conn.execute('DELETE FROM account_security_events WHERE id NOT IN (SELECT id FROM account_security_events ORDER BY id DESC LIMIT 50)')


def replace_password(conn, password, kind):
    from .security import password_hash
    salt = base64.urlsafe_b64encode(secrets.token_bytes(16)).decode()
    conn.execute('UPDATE account_security SET password_salt=?,password_hash=?,revision=revision+1 WHERE id=1',
                 (salt, password_hash(password, salt)))
    conn.execute('DELETE FROM sessions')
    conn.execute('DELETE FROM account_email_challenges')
    record_event(conn, kind)


def change_password(current, password, confirmation, identity):
    check_new_password(password, confirmation)
    with db(immediate=True) as conn:
        if not limit(conn, 'reauth', identity) or not password_matches(account(conn), current):
            return False
        replace_password(conn, password, '修改登录密码')
        return True


def prepare_challenge(purpose, email, identity, current=''):
    """Reserve a generation-bound challenge before queuing transport outside the lock."""
    from .security import token_digest
    email = normalize_email(email)
    with db(immediate=True) as conn:
        if not limit(conn, 'email-request', identity, 10, 3600):
            return None
        record = account(conn)
        if purpose == 'bind':
            if not limit(conn, 'reauth', identity) or not password_matches(record, current):
                return False
        elif purpose != 'reset' or email != record['recovery_email'] or not record['recovery_email']:
            return None
        previous = conn.execute('SELECT created FROM account_email_challenges WHERE purpose=?', (purpose,)).fetchone()
        if previous and time.time() - previous['created'] < 60:
            return None
        if not limit(conn, 'mail-account-' + purpose, 'owner', 20, 86400):
            return None
        code = f'{secrets.randbelow(100_000_000):08d}'
        digest = token_digest(purpose + ':' + email + ':' + code)
        now = time.time()
        conn.execute('INSERT OR REPLACE INTO account_email_challenges VALUES(?,?,?,?,?,?,0,?)',
                     (purpose, email, digest, generation(record), now, now + 600, 'sending'))
        return purpose, email, code, digest


def deliver_challenge(purpose, email, code, digest):
    from .account_mail import send_code
    try:
        send_code(email, code, purpose)
        state = 'sent'
    except Exception:
        # SMTP exceptions can contain addresses or credentials: never log their text.
        state = 'failed'
    with db(immediate=True) as conn:
        conn.execute('UPDATE account_email_challenges SET state=? WHERE purpose=? AND digest=?', (state, purpose, digest))


def consume_challenge(conn, purpose, email, code):
    from .security import token_digest
    row = conn.execute('SELECT * FROM account_email_challenges WHERE purpose=?', (purpose,)).fetchone()
    if not row or row['email'] != email or row['state'] != 'sent' or row['expires'] <= time.time() or row['attempts'] >= 5:
        return False
    conn.execute('UPDATE account_email_challenges SET attempts=attempts+1 WHERE purpose=?', (purpose,))
    valid = (row['email'] == email and row['generation'] == generation(account(conn))
             and re.fullmatch('[0-9]{8}', code) is not None
             and hmac.compare_digest(row['digest'], token_digest(purpose + ':' + email + ':' + code)))
    if valid:
        conn.execute('DELETE FROM account_email_challenges WHERE purpose=?', (purpose,))
    return valid


def bind_email(current, email, code, identity):
    email = normalize_email(email)
    with db(immediate=True) as conn:
        if not limit(conn, 'reauth', identity) or not password_matches(account(conn), current):
            return False
        if not consume_challenge(conn, 'bind', email, code):
            return False
        conn.execute('UPDATE account_security SET recovery_email=?,revision=revision+1 WHERE id=1', (email,))
        conn.execute('DELETE FROM account_email_challenges')
        record_event(conn, '验证并绑定找回邮箱')
        return True


def reset_password(email, code, password, confirmation, identity):
    check_new_password(password, confirmation)
    email = normalize_email(email)
    with db(immediate=True) as conn:
        if not limit(conn, 'reset-attempt', identity, 20) or not consume_challenge(conn, 'reset', email, code):
            return False
        replace_password(conn, password, '邮箱验证重置密码')
        return True


def revoke_other_sessions(current, identity, session_token):
    from .security import token_digest
    with db(immediate=True) as conn:
        if not limit(conn, 'reauth', identity) or not password_matches(account(conn), current):
            return False
        conn.execute('DELETE FROM sessions WHERE token_hash<>?', (token_digest(session_token),))
        record_event(conn, '退出其他设备')
        return True
