"""Real HTTP adapter, shared inbox, invitation rotation and atomic failure."""
import json

from v162_number_inbox_contract import app, db, init_db, TestClient, TOKEN_META_KEY
from app.v162_number_inbox import ensure_number_inbox_schema
from app.number_collection import collect_numbers


def main():
    init_db()
    with db() as conn:
        invite = ensure_number_inbox_schema(conn)
    client = TestClient(app)
    url = '/number-submit/mini/submit'
    headers = {'Authorization': 'Bearer ' + invite}
    valid = {'consent': True, 'numbers': ['13800000101', '+86 13800000101', '13800000102']}

    def count():
        with db() as conn:
            return conn.execute('SELECT COUNT(*) FROM number_inbox').fetchone()[0]

    for auth in [{}, {'Authorization': 'Bearer wrong'}, {'Authorization': 'Basic ' + invite}]:
        r = client.post(url, headers=auth, json=valid)
        assert r.status_code == 401 and r.headers.get('location') is None, r.text
    for payload in [None, [], {'numbers': ['13800000101']},
                    {'consent': True, 'numbers': []}, {'consent': True, 'numbers': ['1']},
                    {'consent': True, 'numbers': ['13800000101', 'invalid']},
                    {'consent': True, 'numbers': [123456789]},
                    {'consent': True, 'numbers': ['13800000101'] * 101}]:
        r = client.post(url, headers=headers, content=json.dumps(payload))
        assert r.status_code == 415, r.text
        r = client.post(url, headers={**headers, 'Content-Type': 'application/json'}, content=json.dumps(payload))
        assert r.status_code == 400, (payload, r.text)
        assert count() == 0
    for body in [b'not-json', b'\xff', b'{']:
        assert client.post(url, headers={**headers, 'Content-Type': 'application/json'}, content=body).status_code == 400
    huge = client.post(url, headers={**headers, 'Content-Type': 'application/json'},
                       content=iter([b'{' + b'x' * 18000, b'x' * 18000 + b'}']))
    assert huge.status_code == 413 and count() == 0

    first = client.post(url, headers=headers, json=valid)
    assert first.status_code == 200, first.text
    assert {k:v for k,v in first.json().items() if k != 'batch'} == {'ok': True, 'received': 3, 'added': 2, 'duplicates': 1}
    assert len(first.json()['batch']) >= 24
    assert first.headers['cache-control'] == 'no-store'
    assert invite not in first.text and '13800000101' not in first.text
    assert count() == 2
    assert client.post(url, headers=headers, json=valid).json()['added'] == 0
    # Existing browser sees the same records and duplicate rule.
    web = client.post(f'/number-submit/{invite}', data={'number': '13800000101'})
    assert web.status_code == 200 and '已经在未加号码列表中' in web.text
    web = client.post(f'/number-submit/{invite}', data={'number': '13800000103'})
    assert '提交成功' in web.text
    assert client.post(url, headers=headers, json={'consent': True, 'numbers': ['13800000103']}).json()['duplicates'] == 1
    many = [f'1390000{i:04d}' for i in range(100)]
    assert client.post(url, headers=headers, json={'consent': True, 'numbers': many}).json()['added'] == 100
    # Native list mirrors the public web list, including new/previous and ordering.
    entry = client.get('/number-submit/mini/entry')
    assert entry.json() == {'ok': True, 'invite': invite}
    assert entry.headers['cache-control'] == 'no-store'
    pending_url = '/number-submit/mini/pending'
    for auth in [{}, {'Authorization': 'Basic ' + invite}, {'Authorization': 'Bearer wrong'}]:
        assert client.get(pending_url, headers=auth).status_code == 401
    pending = client.get(pending_url, headers=headers, params={'batch': first.json()['batch']})
    assert pending.status_code == 200 and pending.headers['cache-control'] == 'no-store'
    items = pending.json()['items']
    assert len(items) == count()
    assert all(set(item) == {'number', 'submitted_display', 'is_new'} for item in items)
    assert {item['number'] for item in items if item['is_new']} == {'13800000101', '13800000102'}
    assert 'submit_batch' not in pending.text and 'submitter' not in pending.text
    assert all(not item['is_new'] for item in client.get(pending_url, headers=headers).json()['items'])
    assert client.get(pending_url, headers=headers, params={'batch': 'x' * 129}).status_code == 400
    with db() as conn:
        conn.execute("UPDATE number_inbox SET status='done' WHERE number='13800000101'")
    assert '13800000101' not in client.get(pending_url, headers=headers).text
    # No anonymous list or admin/desktop access is gained by the adapter.
    assert client.get('/api/number-inbox/pending', headers=headers).status_code == 401
    assert client.get('/work/number-inbox', headers=headers, follow_redirects=False).status_code == 303
    assert client.get('/number-submit/mini/submit').status_code in (404, 405)

    before = count()
    try:
        with db() as conn:
            collect_numbers(conn, ['13700000199'])
            raise RuntimeError('force rollback')
    except RuntimeError:
        pass
    assert count() == before
    with db() as conn:
        conn.execute('UPDATE app_meta SET value=? WHERE key=?', ('r' * 32, TOKEN_META_KEY))
    assert client.get(pending_url, headers=headers).status_code == 401
    assert client.get('/number-submit/mini/entry').json()['invite'] == 'r' * 32
    assert client.post(url, headers=headers, json=valid).status_code == 401
    assert client.post(url, headers={'Authorization': 'Bearer ' + 'r' * 32}, json=valid).status_code == 200
    assert client.get(f'/number-submit/{invite}').status_code == 404
    print('mini program API passed: auth, bounded bodies, atomic batch, shared dedupe, rotation, privacy and rollback')


if __name__ == '__main__':
    main()
