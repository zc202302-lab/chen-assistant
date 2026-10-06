from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = tempfile.TemporaryDirectory(prefix='chen-work-lists-contract-')
os.environ.update(APP_DB_PATH=str(Path(TMP.name) / 'app.db'), APP_USERNAME='lists-test',
                  APP_PASSWORD_SALT='dGVzdHNhbHQ=', APP_PASSWORD_HASH='x',
                  APP_SESSION_SECRET='work-lists-test', APP_ENCRYPTION_KEY=Fernet.generate_key().decode(), APP_SECURE_COOKIE='0')

from fastapi.testclient import TestClient  # noqa: E402
from app.db import db, init_db, now_iso  # noqa: E402
from app.main import app  # noqa: E402
from app.security import create_session  # noqa: E402
from app.work_lists import ensure_work_lists_schema  # noqa: E402


def main():
    init_db()
    ensure_work_lists_schema()
    ensure_work_lists_schema()
    with db() as conn:
        now = now_iso()
        customer_id = conn.execute('INSERT INTO customers(name,source_sheet,created_at,updated_at) VALUES(?,?,?,?)', ('清单测试客户', 'lists-contract', now, now)).lastrowid
        original_customer = dict(conn.execute('SELECT * FROM customers WHERE id=?', (customer_id,)).fetchone())
        original_payments = [dict(r) for r in conn.execute('SELECT * FROM payment_entries')]
    token, csrf, _ = create_session()
    with TestClient(app) as client:
        assert client.get('/work/lists', follow_redirects=False).status_code == 303
        client.cookies.set('session_token', token)
        landing = client.get('/work/lists').text
        assert 'name="title"' not in landing and 'name="q"' in landing
        creation = client.get('/work/lists?view=new').text
        assert 'name="title"' in creation and 'name="q"' not in creation
        assert 'class="wl-grid"' not in creation
        assert 'name="title"' not in client.get('/work/lists?archived=1').text
        assert client.get('/work/lists?view=invalid').status_code == 400
        assert client.post('/work/lists', data={'title': 'blocked'}).status_code == 403
        result = client.post('/work/lists', data={'csrf': csrf, 'title': '欠费测试', 'preset': 'arrears'}, follow_redirects=False)
        assert result.status_code == 303, result.text
        path = result.headers['location']
        list_id = int(path.rsplit('/', 1)[1])
        with db() as conn:
            fields = [dict(r) for r in conn.execute('SELECT * FROM work_list_fields WHERE list_id=? ORDER BY position', (list_id,))]
        text_key, money_key, date_key, select_key = [f'f_{f["id"]}' for f in fields]
        payload = {'csrf': csrf, 'list_revision': '1', 'revision': '0', 'customer_id': str(customer_id),
                   'status': 'pending', 'note': '=SUM(1,2)', text_key: '001234', money_key: '123.45', date_key: '2026-09-30', select_key: '待联系'}
        for key, value in [(money_key, 'NaN'), (money_key, '1.001'), (date_key, '2026-02-30'), (select_key, '伪造选项'), ('customer_id', '999999999')]:
            bad = payload | {key: value}
            response = client.post(path + '/records/new', data=bad)
            assert response.status_code == 400, (key, response.text)
            assert '001234' in response.text, 'invalid input must preserve the form'
        with db() as conn:
            assert conn.execute('SELECT COUNT(*) FROM work_list_records').fetchone()[0] == 0
        response = client.post(path + '/records/new', data=payload, follow_redirects=False)
        assert response.status_code == 303, response.text
        with db() as conn:
            row = dict(conn.execute('SELECT * FROM work_list_records WHERE list_id=?', (list_id,)).fetchone())
            record_id = row['id']
            assert json.loads(row['values_json'])[str(fields[0]['id'])] == '001234'
        edit = path + f'/records/{record_id}/edit'
        assert client.post(edit, data=payload | {'revision': '1', 'status': 'done'}, follow_redirects=False).status_code == 303
        assert client.post(edit, data=payload | {'revision': '1'}).status_code == 409
        assert '001234' not in client.get(path + '?status=pending').text
        assert '001234' in client.get(path + '?q=001234&status=done').text
        exported = client.get(path + '/export.xlsx?q=001234&status=done')
        assert exported.status_code == 200
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            strings = archive.read('xl/sharedStrings.xml').decode()
            sheet = archive.read('xl/worksheets/sheet1.xml').decode()
            assert '001234' in strings and '=SUM(1,2)' in strings
            assert '<f>' not in sheet, 'user text must never become an Excel formula'
            assert '<v>123.45</v>' in sheet
        settings = {'csrf': csrf, 'revision': '1', 'title': '改名后', 'description': ''}
        for field in fields:
            settings[f'label_{field["id"]}'] = '号码' if field == fields[0] else field['label']
            settings[f'position_{field["id"]}'] = str(field['position'])
        settings[f'hidden_{fields[0]["id"]}'] = '1'
        assert client.post(path + '/settings', data=settings, follow_redirects=False).status_code == 303
        assert '001234' not in client.get(path).text
        assert client.post(edit, data=payload | {'revision': '2'}).status_code == 409, 'stale field layout must not overwrite values'
        assert client.post(edit, data=payload | {'revision': '2', 'list_revision': '2', text_key: ''}, follow_redirects=False).status_code == 303
        with db() as conn:
            assert json.loads(conn.execute('SELECT values_json FROM work_list_records WHERE id=?', (record_id,)).fetchone()[0])[str(fields[0]['id'])] == '001234'
        settings.pop(f'hidden_{fields[0]["id"]}')
        assert client.post(path + '/settings', data=settings | {'revision': '2'}, follow_redirects=False).status_code == 303
        assert '001234' in client.get(path).text
        assert client.post(path + '/fields', data={'csrf': csrf, 'revision': '3', 'label': '标签', 'kind': 'multi', 'options': '重要\n回访'}, follow_redirects=False).status_code == 303
        with db() as conn:
            multi_id = conn.execute('SELECT MAX(id) FROM work_list_fields WHERE list_id=?', (list_id,)).fetchone()[0]
        multi_payload = payload | {'revision': '3', 'list_revision': '4', f'f_{multi_id}': ['重要', '回访']}
        assert client.post(edit, data=multi_payload, follow_redirects=False).status_code == 303
        assert '重要、回访' in client.get(path).text
        assert client.post(edit, data=multi_payload | {'revision': '4', f'f_{multi_id}': ['不存在']}).status_code == 400
        other = client.post('/work/lists', data={'csrf': csrf, 'title': '商机测试', 'preset': 'opportunity'}, follow_redirects=False).headers['location']
        assert client.get(other + f'/records/{record_id}/edit').status_code == 404
        assert client.post(path + '/archive', data={'csrf': csrf, 'revision': '4'}, follow_redirects=False).status_code == 303
        assert client.get(path + '/records/new').status_code == 409
        assert client.post(edit, data=multi_payload).status_code == 409
        assert client.get(path + '/export.xlsx').status_code == 200
        assert '改名后' in client.get('/work/lists?archived=1').text
        assert client.post(path + '/archive', data={'csrf': csrf, 'revision': '5'}, follow_redirects=False).status_code == 303
        assert '重要、回访' in client.get(path).text
    with db() as conn:
        assert dict(conn.execute('SELECT * FROM customers WHERE id=?', (customer_id,)).fetchone()) == original_customer
        assert [dict(r) for r in conn.execute('SELECT * FROM payment_entries')] == original_payments
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
    print('work lists contract passed: validation, preservation, concurrency, archive, customer isolation, safe Excel')


if __name__ == '__main__':
    main()
