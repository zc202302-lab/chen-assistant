from __future__ import annotations

import io
import json
import os
import struct
import sys
import tempfile
import zipfile
from datetime import datetime
from html import escape
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = tempfile.TemporaryDirectory(prefix='chen-list-import-contract-')
os.environ.update(APP_DB_PATH=str(Path(TMP.name) / 'app.db'), APP_USERNAME='import-test', APP_PASSWORD_SALT='dGVzdHNhbHQ=',
                  APP_PASSWORD_HASH='x', APP_SESSION_SECRET='import-session', APP_ENCRYPTION_KEY=Fernet.generate_key().decode(), APP_SECURE_COOKIE='0')
from fastapi.testclient import TestClient  # noqa: E402
from app.db import db, init_db, now_iso  # noqa: E402
from app.main import app  # noqa: E402
from app.security import create_session, decrypt_secret  # noqa: E402
from app.work_list_excel import ExcelTable, MAX_BYTES  # noqa: E402
from app.work_list_import import ensure_work_list_import_schema  # noqa: E402
from app.work_lists import ensure_work_lists_schema  # noqa: E402


from work_list_import_fixtures import workbook, legacy_xls


def main():
    reader = ExcelTable(workbook(), 'sample.xlsm')
    table = reader.read('欠费明细', 1, 'D', 'H')
    assert [r['row'] for r in table['rows']] == [2, 3, 5]
    assert table['rows'][0]['cells'][:3] == ['000123', '125.5', '2026-09-30']
    assert table['columns'][0]['letter'] == 'D'
    reader.close()
    reader = ExcelTable(legacy_xls(), 'legacy.xls')
    assert reader.read(reader.sheets[0])['rows'][0]['cells'] == ['00123', '250']
    reader.close()
    for content, filename in [(b'bad', 'bad.xlsx'), (b'bad', 'bad.exe'), (b'x' * (MAX_BYTES + 1), 'big.xlsx')]:
        try:
            ExcelTable(content, filename)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid upload accepted')
    reader = ExcelTable(workbook(missing_formula=True), 'formula.xlsx')
    try:
        reader.read('欠费明细', 1, 'D', 'H')
    except ValueError as exc:
        assert '公式' in str(exc)
    else:
        raise AssertionError('uncached formulas must not silently become blanks')
    reader.close()
    bomb = bytearray(workbook())
    offset = bomb.index(b'PK\x01\x02')
    struct.pack_into('<I', bomb, offset + 24, 70 * 1024 * 1024)
    try:
        ExcelTable(bytes(bomb), 'bomb.xlsx')
    except ValueError:
        pass
    else:
        raise AssertionError('oversized expansion must be rejected')
    unsafe = io.BytesIO()
    with zipfile.ZipFile(unsafe, 'w') as archive:
        archive.writestr('xl/workbook.xml', ('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE workbook [<!ENTITY test "unsafe">]><workbook/>').encode('utf-16'))
    try:
        ExcelTable(unsafe.getvalue(), 'entities.xlsx')
    except ValueError as exc:
        assert 'XML' in str(exc)
    else:
        raise AssertionError('UTF-16 XML entity definitions must be rejected')
    init_db()
    ensure_work_lists_schema()
    ensure_work_list_import_schema()
    with db() as conn:
        now = now_iso()
        customer_id = conn.execute('INSERT INTO customers(name,source_sheet,created_at,updated_at) VALUES(?,?,?,?)', ('导入客户', 'import-contract', now, now)).lastrowid
        customer_before = dict(conn.execute('SELECT * FROM customers WHERE id=?', (customer_id,)).fetchone())
        payments_before = [dict(r) for r in conn.execute('SELECT * FROM payment_entries')]
    token, csrf, _ = create_session()
    with TestClient(app) as client:
        client.cookies.set('session_token', token)
        assert client.post('/work/list-import/upload', files={'file': ('file.xlsx', workbook())}).status_code == 403
        def upload(content=workbook(), target=0):
            response = client.post('/work/list-import/upload', data={'csrf': csrf, 'target': str(target)}, files={'file': ('sample.xlsx', content)}, follow_redirects=False)
            assert response.status_code == 303, response.text
            return response.headers['location']
        def prepare(path, target=0):
            response = client.post(path + '/prepare', data={'csrf': csrf, 'revision': '1', 'sheet': '欠费明细', 'header': '1', 'first': 'D', 'last': 'H', 'title': 'Excel欠费清单', 'target': str(target)}, follow_redirects=False)
            assert response.status_code == 303, response.text
        mapping = {'csrf': csrf, 'revision': '2', 'duplicates': 'skip', 'dest_4': 'new', 'label_4': '号码', 'kind_4': 'text',
                   'dest_5': 'new', 'label_5': '金额', 'kind_5': 'money', 'dest_6': 'new', 'label_6': '日期', 'kind_6': 'date',
                   'dest_7': 'customer_name', 'dest_8': 'note'}
        bad_path = upload(workbook(bad=True))
        prepare(bad_path)
        bad = client.post(bad_path + '/preview', data=mapping)
        assert bad.status_code == 400 and '第3行' in bad.text
        with db() as conn:
            assert conn.execute('SELECT COUNT(*) FROM work_list_records').fetchone()[0] == 0
            assert conn.execute('SELECT COUNT(*) FROM work_lists').fetchone()[0] == 0
        path = upload()
        prepare(path)
        assert client.post(path + '/confirm', data={'csrf': csrf, 'revision': '2'}).status_code == 409
        preview = client.post(path + '/preview', data=mapping)
        assert preview.status_code == 200 and '将新增 2 条' in preview.text and '跳过 1 条' in preview.text
        assert client.post(path + '/preview', data=mapping).status_code == 409
        assert client.post(path + '/confirm', data={'csrf': csrf, 'revision': '3'}, follow_redirects=False).status_code == 303
        assert client.post(path + '/confirm', data={'csrf': csrf, 'revision': '3'}, follow_redirects=False).status_code == 303
        with db() as conn:
            rows = [dict(r) for r in conn.execute('SELECT * FROM work_list_records')]
            assert len(rows) == 2 and all(r['customer_id'] == customer_id for r in rows)
            list_id = rows[0]['list_id']
            fields = [dict(r) for r in conn.execute('SELECT * FROM work_list_fields WHERE list_id=? ORDER BY position', (list_id,))]
            assert json.loads(rows[0]['values_json'])[str(fields[0]['id'])] == '000123'
            stored = conn.execute('SELECT payload_enc FROM work_list_imports WHERE token=?', (path.rsplit('/', 1)[-1],)).fetchone()[0]
            receipt = json.loads(decrypt_secret(stored))
            assert 'source' not in receipt and receipt['imported'] == 2
        path2 = upload(target=list_id)
        prepare(path2, list_id)
        existing_mapping = mapping | {f'dest_{col}': str(field['id']) for col, field in zip([4, 5, 6], fields)}
        preview = client.post(path2 + '/preview', data=existing_mapping)
        assert '将新增 0 条' in preview.text and '跳过 3 条' in preview.text
        assert client.post(path2 + '/confirm', data={'csrf': csrf, 'revision': '3'}, follow_redirects=False).status_code == 303
        with db() as conn:
            assert [dict(r) for r in conn.execute('SELECT * FROM work_list_records')] == rows
        stale = upload(target=list_id)
        prepare(stale, list_id)
        assert client.post(stale + '/preview', data=existing_mapping).status_code == 200
        with db() as conn:
            conn.execute('UPDATE work_lists SET revision=revision+1 WHERE id=?', (list_id,))
        assert client.post(stale + '/confirm', data={'csrf': csrf, 'revision': '3'}).status_code == 409
        other_token, other_csrf, _ = create_session()
        client.cookies.set('session_token', other_token)
        assert client.get(stale).status_code == 404
        assert client.post(stale + '/confirm', data={'csrf': other_csrf, 'revision': '3'}).status_code == 404
        client.cookies.set('session_token', token)
        with db() as conn:
            conn.execute("UPDATE work_list_imports SET expires_at='2000-01-01T00:00:00+00:00' WHERE token=?", (stale.rsplit('/', 1)[-1],))
        assert client.get(stale).status_code == 410
        assert client.post(stale + '/confirm', data={'csrf': csrf, 'revision': '3'}).status_code == 410
    with db() as conn:
        assert dict(conn.execute('SELECT * FROM customers WHERE id=?', (customer_id,)).fetchone()) == customer_before
        assert [dict(r) for r in conn.execute('SELECT * FROM payment_entries')] == payments_before
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
    print('work list Excel import contract passed: XLS/XLSX/XLSM, range, zeros, dates, validation, preview, atomicity, duplicates, replay, stale schemas, session isolation')


if __name__ == '__main__':
    main()
