"""Real write receipt, snapshot isolation, idempotence and five-day retention."""
import asyncio
import copy
import json
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from number_inbox_batch_contract import ROOT, excel, HEADERS
from v162_number_inbox_contract import _TMPDIR, TestClient, app, create_session, db, init_db
from app.number_inbox_batch import META_KEY, complete_batch, purge_expired, RETENTION_SECONDS
from app.v162_number_inbox import ensure_number_inbox_schema, ensure_desktop_token
from win_assistants.number_batch_bridge import NumberBatchBridge
from win_assistants.number_batch_sync import signed_receipt


def main():
    init_db()
    with db() as conn:
        ensure_number_inbox_schema(conn)
        token = ensure_desktop_token(conn)
        conn.execute('INSERT OR REPLACE INTO app_meta VALUES(?,?)', (META_KEY, json.dumps({'groups': ['G001'], 'role': 'role', 'manual': '1'})))
        for number in ['00123456789', '12345678901234567890']:
            conn.execute("INSERT INTO number_inbox(number,normalized_number,status,submitted_at) VALUES(?,?,'pending',?)", (number, number, datetime.now(timezone.utc).isoformat()))
    client = TestClient(app)
    assert client.post('/api/number-inbox/batch-complete', json={}).status_code == 401
    session, csrf, _ = create_session()
    client.cookies.set('session_token', session)
    assert client.post('/work/number-inbox/batch-complete', json={}).status_code == 403
    signed = client.post('/work/number-inbox/batch-add', data={'csrf': csrf}).json()
    # The snapshot is issued before this new number arrives; it must remain pending.
    with db() as conn:
        conn.execute("INSERT INTO number_inbox(number,normalized_number,status,submitted_at) VALUES('13600000001','13600000001','pending',?)", (datetime.now(timezone.utc).isoformat(),))
    target = Path(_TMPDIR.name) / 'members.xlsx'
    original = excel([['stale']], HEADERS)
    target.write_bytes(original)
    bridge = NumberBatchBridge(lambda: token, lambda: target, ledger=Path(_TMPDIR.name) / 'ledger.json')
    body = bridge.execute(signed)
    receipt = body['receipt']
    with db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM number_inbox WHERE status='pending'").fetchone()[0] == 3
    headers = {'X-CSRF-Token': csrf}
    bad = copy.deepcopy(receipt); bad['signature'] = '0' * 64
    assert client.post('/work/number-inbox/batch-complete', json=bad, headers=headers).status_code == 400
    wrong_count = signed_receipt(signed, 1, token)
    assert client.post('/work/number-inbox/batch-complete', json=wrong_count, headers=headers).status_code == 400
    future = signed_receipt(signed, 2, token, int(time.time()) + 3600)
    assert client.post('/work/number-inbox/batch-complete', json=future, headers=headers).status_code == 400
    assert client.post('/work/number-inbox/batch-complete', json=receipt, headers=headers).json()['archived'] is True
    with db() as conn:
        rows = conn.execute('SELECT * FROM number_inbox ORDER BY id').fetchall()
        assert [r['status'] for r in rows] == ['done', 'done', 'pending']
        stamps = [r['completed_at'] for r in rows[:2]]
    page = client.get('/work/number-inbox').text
    assert '<summary>已录号码 <b>2</b></summary>' in page
    assert '<details class="number-inbox-done">' in page and '<details class="number-inbox-done" open' not in page
    # A duplicate successful callback is safe without a login cookie.
    client.cookies.clear()
    response = client.post('/api/number-inbox/batch-complete', json=receipt, headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 200, response.text
    with db() as conn:
        assert [r[0] for r in conn.execute("SELECT completed_at FROM number_inbox WHERE status='done' ORDER BY id")] == stamps
        # Exact age boundary, pending never deleted, retention uses completion not submission.
        conn.execute("UPDATE number_inbox SET submitted_at='2000-01-01' WHERE status='done'")
        complete_time = receipt['receipt']['completed_at']
        purge_expired(conn, complete_time + RETENTION_SECONDS - 1)
        assert conn.execute("SELECT COUNT(*) FROM number_inbox WHERE status='done'").fetchone()[0] == 2
        purge_expired(conn, complete_time + RETENTION_SECONDS)
        assert conn.execute("SELECT COUNT(*) FROM number_inbox WHERE status='done'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM number_inbox WHERE status='pending'").fetchone()[0] == 1
    # No receipt can be produced for a failed local file write.
    target.write_bytes(b'invalid')
    client.cookies.set('session_token', session)
    newer = client.post('/work/number-inbox/batch-add', data={'csrf': csrf}).json()
    try:
        bridge.execute(newer)
        raise AssertionError('invalid workbook must fail')
    except (ValueError, zipfile.BadZipFile):
        pass
    with db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM number_inbox WHERE status='pending'").fetchone()[0] == 1
    stored = json.loads(bridge.receipts.path.read_text())
    assert newer['payload']['nonce'] not in stored
    assert target.read_bytes() == b'invalid'
    from app.number_inbox_batch import retention_worker
    with db() as conn:
        conn.execute("INSERT INTO number_inbox(number,normalized_number,status,submitted_at,completed_at) VALUES('15500000001','15500000001','done','2000-01-01','2000-01-02T08:00:00+08:00')")
    async def tick():
        stop = asyncio.Event()
        def clean(conn):
            purge_expired(conn)
            stop.set()
        with patch('app.number_inbox_batch.purge_expired', side_effect=clean):
            await retention_worker(stop)
    asyncio.run(tick())
    with db() as conn:
        assert conn.execute("SELECT 1 FROM number_inbox WHERE number='15500000001'").fetchone() is None
        assert conn.execute("SELECT COUNT(*) FROM number_inbox WHERE status='pending'").fetchone()[0] == 1
    print('number archive receipt auth, real write, late submissions, failure isolation, idempotence and exact five-day retention passed')


if __name__ == '__main__':
    main()
