"""Web-to-desktop contract with real XLSX packages and all pending numbers."""
import hashlib
import hmac
import io
import json
import sys
from pathlib import Path

import xlsxwriter

from v162_number_inbox_contract import ROOT, TestClient, app, create_session, db, init_db
from app.number_inbox_batch import settings, read_groups
from app.v162_number_inbox import ensure_desktop_token, ensure_number_inbox_schema
from app.work_list_excel import ExcelTable

sys.path.insert(0, str(ROOT / 'windows' / 'win-assistants'))
from win_assistants.number_batch import HEADERS, build_workbook  # noqa: E402
from win_assistants.number_batch_bridge import verify_request  # noqa: E402


def excel(rows, headers=None):
    buffer = io.BytesIO()
    book = xlsxwriter.Workbook(buffer, {'in_memory': True})
    sheet = book.add_worksheet('集团模板')
    sheet.write_row(0, 0, headers or ['集团编码'])
    for n, row in enumerate(rows, 1):
        sheet.write_row(n, 0, row)
    book.add_worksheet('格式说明').write(0, 0, '保留格式说明')
    book.close()
    return buffer.getvalue()


def main():
    init_db()
    with db() as conn:
        ensure_number_inbox_schema(conn)
        token = ensure_desktop_token(conn)
    client = TestClient(app)
    assert client.post('/work/number-inbox/batch-add', data={'csrf': 'wrong'}, follow_redirects=False).status_code == 303
    session, csrf, _ = create_session()
    client.cookies.set('session_token', session)
    assert client.post('/work/number-inbox/batch-add', data={'csrf': 'wrong'}).status_code == 403
    assert client.post('/work/number-inbox/batch-settings', data={'csrf': 'wrong', 'role': 'x', 'manual': '1'}).status_code == 403
    result = client.post('/work/number-inbox/batch-settings', data={'csrf': csrf, 'role': 'MemberSort0102', 'manual': '1'},
                         files={'group_template': ('groups.xlsx', excel([['G001'], ['00001234567890123456'], ['G001']]))}, follow_redirects=False)
    assert result.status_code == 303, result.text
    with db() as conn:
        assert settings(conn)['groups'] == ['G001', '00001234567890123456']
    # Invalid upload must not replace the valid template or settings.
    bad = client.post('/work/number-inbox/batch-settings', data={'csrf': csrf, 'role': 'changed', 'manual': '0'},
                      files={'group_template': ('bad.xlsx', b'not excel')})
    assert bad.status_code == 400, bad.text
    with db() as conn:
        assert settings(conn)['role'] == 'MemberSort0102'
    assert client.post('/work/number-inbox/batch-add', data={'csrf': csrf}).status_code == 400
    client.post('/work/number-inbox/batch-settings', data={'csrf': csrf, 'role': '=custom-role', 'manual': '0'})
    with db() as conn:
        for n in range(306):
            number = f'001{n:08d}'
            conn.execute("INSERT INTO number_inbox(number,normalized_number,status,submitted_at) VALUES(?,?,'pending','2026-10-01')", (number, number))
    result = client.post('/work/number-inbox/batch-add', data={'csrf': csrf})
    assert result.status_code == 200, result.text
    assert result.headers['cache-control'] == 'no-store'
    body = result.json()
    payload = verify_request(body, token)
    assert len(payload['numbers']) == 306, 'must not use the desktop reminder 200-row feed'
    assert payload['role'] == '=custom-role' and payload['manual'] == '0'
    assert token not in result.text and 'target' not in payload
    target = excel([['old', 'old', 'old', 'old', 'old', 'old'], ['stale']], HEADERS)
    output = build_workbook(target, payload['numbers'], payload['groups'], payload['role'], payload['manual'])
    reader = ExcelTable(output, 'members.xlsx')
    try:
        rows = reader.read(reader.sheets[0], 1, 'A', 'F')['rows']
        assert len(rows) == 306
        for n, row in enumerate(rows):
            a, b, c, d, e, f = row['cells']
            assert a in payload['groups'] and b == '=custom-role' and c == payload['numbers'][n]
            assert d == f == '' and e == '0'
    finally:
        reader.close()
    with db() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM number_inbox WHERE status='pending'").fetchone()['n'] == 306
    client.post('/work/number-inbox/rotate-desktop-token', data={'csrf': csrf})
    latest = client.post('/work/number-inbox/batch-add', data={'csrf': csrf}).json()
    try:
        verify_request(latest, token)
        raise AssertionError('rotated token must invalidate old desktop connection')
    except ValueError:
        pass
    for upload in (excel([[12345678901234567]]), excel([['=1+2']])):
        try:
            read_groups(upload, 'groups.xlsx')
            raise AssertionError('unsafe numeric precision/formula must be rejected')
        except ValueError:
            pass
    with db() as conn:
        for n in range(306, 5001):
            number = f'001{n:08d}'
            conn.execute("INSERT INTO number_inbox(number,normalized_number,status,submitted_at) VALUES(?,?,'pending','2026-10-01')", (number, number))
    assert client.post('/work/number-inbox/batch-add', data={'csrf': csrf}).status_code == 400
    print('number batch upload, defaults, all rows, OOXML clearing, signatures and unchanged pending status passed')


if __name__ == '__main__':
    main()
