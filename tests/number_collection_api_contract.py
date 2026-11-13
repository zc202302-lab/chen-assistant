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

    # History shares exact web sorting, completion times, and five-day retention.
    from datetime import datetime, timedelta, timezone
    from unittest.mock import patch
    from app.v162_number_inbox import _recorded_items
    now = datetime(2026, 11, 13, 7, 30, tzinfo=timezone.utc)
    history_url = '/number-submit/mini/history'
    for auth in [{}, {'Authorization': 'Basic ' + invite}, {'Authorization': 'Bearer wrong'}]:
        assert client.get(history_url, headers=auth).status_code == 401
    with db() as conn:
        conn.execute("UPDATE number_inbox SET completed_at=? WHERE number='13800000101'", ((now - timedelta(days=1)).isoformat(),))
        for number, completed in [('00123456789', now), ('12345678901234567890', now),
                                  ('13999990000', now - timedelta(days=5)),
                                  ('13999990001', now - timedelta(days=5, seconds=1))]:
            conn.execute("INSERT INTO number_inbox(number,normalized_number,status,submitted_at,completed_at,note,submitter) VALUES(?,?,'done',?,?,?,?)",
                         (number, number, now.isoformat(), completed.isoformat(), 'private-note', 'private-submitter'))
    with patch('app.number_inbox_batch.time.time', return_value=now.timestamp()):
        history = client.get(history_url, headers=headers)
        assert history.status_code == 200 and history.headers['cache-control'] == 'no-store'
        recorded = history.json()['items']
        assert [row['number'] for row in recorded] == ['12345678901234567890', '00123456789', '13800000101']
        assert recorded[0]['completed_display'] == '11-13 15:30'
        assert all(set(row) == {'number', 'completed_display'} for row in recorded)
        assert 'private-note' not in history.text and 'private-submitter' not in history.text
        with db(immediate=True) as conn:
            expected = [{key: row[key] for key in ('number', 'completed_display')} for row in _recorded_items(conn)]
            assert not conn.execute("SELECT 1 FROM number_inbox WHERE number IN ('13999990000','13999990001')").fetchone()
        assert recorded == expected
        import re
        start = client.get(f'/number-submit/{invite}')
        assert f'href="/number-submit/{invite}/history"' in start.text
        page = client.get(f'/number-submit/{invite}/history', headers={'Host': 'jituan.zbassistant.site'})
        assert page.status_code == 200 and 'no-store' in page.headers['cache-control']
        assert re.findall(r'data-history-copy="([^"]+)"', page.text) == [row['number'] for row in recorded]
        assert '11-13 15:30' in page.text and '已录号码保留5天' in page.text
        assert 'private-note' not in page.text and 'private-submitter' not in page.text
        assert client.get('/number-submit/invalid-invite/history').status_code == 404
        for asset, filename in [('history.css','number-public-history.css'),('history.js','number-public-history.js')]:
            assert f'/number-submit/assets/{asset}?v=1811' in page.text
            asset_response = client.get('/number-submit/assets/' + asset, headers={'Host':'jituan.zbassistant.site'})
            assert asset_response.status_code == 200 and 'no-store' in asset_response.headers['cache-control']
            from pathlib import Path
            assert asset_response.content == (Path(__file__).resolve().parents[1] / 'app/static' / filename).read_bytes()
        for name in ['app.js','config.py','history.json','unknown.css']:
            assert client.get('/number-submit/assets/' + name).status_code == 404
    assert '13900000000' not in history.text, 'pending numbers must not appear in history'

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
    assert client.get(history_url, headers=headers).status_code == 401
    assert client.get(f'/number-submit/{invite}/history').status_code == 404
    assert client.get('/number-submit/mini/entry').json()['invite'] == 'r' * 32
    assert client.post(url, headers=headers, json=valid).status_code == 401
    assert client.post(url, headers={'Authorization': 'Bearer ' + 'r' * 32}, json=valid).status_code == 200
    assert client.get(f'/number-submit/{invite}').status_code == 404
    print('mini program API passed: auth, bounded bodies, atomic batch, shared dedupe, rotation, privacy and rollback')


if __name__ == '__main__':
    main()
