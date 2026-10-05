from __future__ import annotations

import os
import sys
import tempfile
import io
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-number-inbox-')
os.environ['APP_DB_PATH'] = str(Path(_TMPDIR.name) / 'app.db')
os.environ.setdefault('APP_USERNAME', 'number-inbox-test')
os.environ.setdefault('APP_PASSWORD_SALT', 'dGVzdHNhbHQ=')
os.environ.setdefault('APP_PASSWORD_HASH', 'x')
os.environ.setdefault('APP_SESSION_SECRET', 'number-inbox-session-secret')
os.environ.setdefault('APP_ENCRYPTION_KEY', 'x')
os.environ.setdefault('APP_SECURE_COOKIE', '0')

from fastapi.testclient import TestClient  # noqa: E402
from app.db import db, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.security import create_session  # noqa: E402
from app.v162_number_inbox import ensure_desktop_token, ensure_number_inbox_schema, DESKTOP_TOKEN_META_KEY, TOKEN_META_KEY  # noqa: E402


def main():
    init_db()
    with db() as conn:
        token = ensure_number_inbox_schema(conn)
        assert len(token) >= 24
        saved = conn.execute('SELECT value FROM app_meta WHERE key=?', (TOKEN_META_KEY,)).fetchone()
        assert saved and saved['value'] == token
        desktop_token = ensure_desktop_token(conn)
        assert len(desktop_token) >= 32
        saved_desktop = conn.execute('SELECT value FROM app_meta WHERE key=?', (DESKTOP_TOKEN_META_KEY,)).fetchone()
        assert saved_desktop and saved_desktop['value'] == desktop_token

    client = TestClient(app)

    update_asset = client.get('/static/win-assistants/update.json', follow_redirects=False)
    update_cache = update_asset.headers.get('cache-control', '')
    assert 'no-store' in update_cache and 'no-cache' in update_cache, update_cache
    exe_asset = client.get('/static/win-assistants/win-assistants.exe', follow_redirects=False)
    exe_cache = exe_asset.headers.get('cache-control', '')
    assert 'no-cache' in exe_cache and 'max-age=0' in exe_cache, exe_cache

    bad = client.get('/number-submit/not-the-token', follow_redirects=False)
    assert bad.status_code == 404, bad.text

    page = client.get(f'/number-submit/{token}')
    assert page.status_code == 200, page.text
    assert '提交后会进入' not in page.text
    assert 'name="note"' not in page.text
    assert 'name="submitter"' not in page.text
    assert 'id="add-number"' in page.text
    assert f'/number-submit/{token}/pending' in page.text
    assert '请填写加集团号码' in page.text

    first = client.post(
        f'/number-submit/{token}',
        data={'number': '13800138000', 'submitter': '测试同事', 'note': '首次提交'},
    )
    assert first.status_code == 200, first.text
    assert '提交成功' in first.text
    assert first.text.count('number-type-new') == 1
    assert first.history[0].status_code == 303
    assert first.url.path == f'/number-submit/{token}/pending'
    assert '提交人' not in first.text
    assert '<th>类型</th><th>号码</th><th>提交时间</th>' in first.text
    assert desktop_token not in first.text
    assert 'assistant.ziboxiaozhushou.cn' not in first.text
    assert client.get('/number-submit/wrong/pending').status_code == 404
    assert client.post('/number-submit/wrong', data={'number': 'bad'}).status_code == 404

    duplicate = client.post(
        f'/number-submit/{token}',
        data={'number': '+86 13800138000', 'submitter': '另一同事', 'note': '重复提交'},
    )
    assert duplicate.status_code == 200, duplicate.text
    assert '已经在未加号码列表中' in duplicate.text
    assert 'number-type-new' not in duplicate.text
    assert 'number-type-previous' in duplicate.text

    unauth_feed = client.get('/api/number-inbox/pending', follow_redirects=False)
    assert unauth_feed.status_code == 401, unauth_feed.text
    feed = client.get(
        '/api/number-inbox/pending',
        headers={'Authorization': f'Bearer {desktop_token}'},
    )
    assert feed.status_code == 200, feed.text
    payload = feed.json()
    assert payload['ok'] is True
    assert payload['pending_count'] == 1
    assert len(payload['pending_ids']) == 1
    assert payload['latest_id'] > 0
    assert payload['items'][0]['number'] == '13800138000'
    assert feed.headers.get('cache-control') == 'no-store'

    desktop_done_unauth = client.post('/api/number-inbox/1/done', follow_redirects=False)
    assert desktop_done_unauth.status_code == 401

    with db() as conn:
        rows = conn.execute('SELECT * FROM number_inbox ORDER BY id').fetchall()
        assert len(rows) == 1, len(rows)
        assert rows[0]['normalized_number'] == '13800138000'
        assert rows[0]['status'] == 'pending'
        assert rows[0]['note'] == ''
        assert rows[0]['submitter'] == ''
        item_id = int(rows[0]['id'])

    desktop_done = client.post(
        f'/api/number-inbox/{item_id}/done',
        headers={'Authorization': f'Bearer {desktop_token}'},
    )
    assert desktop_done.status_code == 200, desktop_done.text
    assert desktop_done.json()['status'] == 'done'
    assert desktop_done.headers.get('cache-control') == 'no-store'
    with db() as conn:
        row = conn.execute('SELECT status,completed_at FROM number_inbox WHERE id=?', (item_id,)).fetchone()
        assert row['status'] == 'done'
        assert row['completed_at']
        conn.execute("UPDATE number_inbox SET status='pending',completed_at='' WHERE id=?", (item_id,))

    unauthenticated = client.get('/work/number-inbox', follow_redirects=False)
    assert unauthenticated.status_code == 303, unauthenticated.status_code
    assert unauthenticated.headers['location'] == '/login'

    session_token, csrf, _ = create_session()
    client.cookies.set('session_token', session_token)
    admin = client.get('/work/number-inbox')
    assert admin.status_code == 200, admin.text
    assert '13800138000' in admin.text
    assert 'data-group-batch-export' in admin.text
    assert '提交人' not in admin.text
    assert '号码收集二级导航' in admin.text
    assert '同事提交入口' not in admin.text and 'Windows 提醒连接' not in admin.text
    assert desktop_token not in admin.text and f'/number-submit/{token}' not in admin.text
    settings = client.get('/work/number-inbox?view=settings')
    assert settings.status_code == 200
    assert '同事提交入口' in settings.text and 'Windows 提醒连接' in settings.text
    assert desktop_token in settings.text
    assert 'title="点击复制号码"' not in settings.text
    assert '13800138000' not in settings.text
    assert f'https://jituan.zbassistant.site/number-submit/{token}' in settings.text
    assert '同事提交入口' not in client.get('/work/number-inbox?view=invalid').text
    assert 'zcassistant.site' not in admin.text
    assert '1 个未加' in client.get('/work').text
    assert '查看未加号码' in client.get('/').text
    assert '已处理' not in admin.text
    assert 'status=done' not in admin.text
    assert 'status=all' not in admin.text

    export_bad_csrf = client.post('/work/number-inbox/export-group-batch', data={'csrf': 'wrong'})
    assert export_bad_csrf.status_code == 403
    export = client.post('/work/number-inbox/export-group-batch', data={'csrf': csrf})
    assert export.status_code == 200, export.text
    assert export.headers['X-Number-Count'] == '1'
    disposition = export.headers['Content-Disposition']
    assert "filename*=UTF-8''" in disposition
    filename = unquote(disposition.split("filename*=UTF-8''", 1)[1])
    assert filename == '号码加集团.xlsx'
    assert export.headers['Cache-Control'] == 'no-store'
    with zipfile.ZipFile(io.BytesIO(export.content)) as workbook:
        sheet = ET.fromstring(workbook.read('xl/worksheets/sheet1.xml'))
        shared = ET.fromstring(workbook.read('xl/sharedStrings.xml'))
        ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        cells = {cell.attrib['r']: cell for cell in sheet.findall('.//x:c', ns)}
        strings = [''.join(text.text or '' for text in item.findall('.//x:t', ns)) for item in shared.findall('x:si', ns)]
        assert set(cells) == {'A1', 'B1'}, set(cells)
        assert strings[int(cells['A1'].find('x:v', ns).text)] == '13800138000'
        assert strings[int(cells['B1'].find('x:v', ns).text)] == 'c7210826122'

    done = client.post(
        f'/work/number-inbox/{item_id}/done',
        data={'csrf': csrf},
        follow_redirects=False,
    )
    assert done.status_code == 303
    with db() as conn:
        row = conn.execute('SELECT status,completed_at FROM number_inbox WHERE id=?', (item_id,)).fetchone()
        assert row['status'] == 'done'
        assert row['completed_at']

    pending_page = client.get(f'/number-submit/{token}/pending')
    assert '13800138000' not in pending_page.text
    assert '目前没有未加号码' in pending_page.text
    assert '13800138000' not in client.get('/work/number-inbox?status=done').text

    reopened = client.post(
        f'/work/number-inbox/{item_id}/reopen',
        data={'csrf': csrf},
        follow_redirects=False,
    )
    assert reopened.status_code == 303
    with db() as conn:
        row = conn.execute('SELECT status,completed_at FROM number_inbox WHERE id=?', (item_id,)).fetchone()
        assert row['status'] == 'pending'
        assert row['completed_at'] == ''

    # Every pending entry is visible, including entries beyond the old 300-row cap.
    with db() as conn:
        for index in range(305):
            conn.execute(
                "INSERT INTO number_inbox(number,normalized_number,submitter,status,submitted_at) VALUES(?,?,?,'pending',?)",
                (f'139{index:08d}', f'139{index:08d}', '<script>alert(1)</script>', '2026-10-01T00:00:00+00:00'),
            )
    public_pending = client.get(f'/number-submit/{token}/pending')
    assert public_pending.text.count('<tr><td>') == 306
    assert '10-01 08:00' in public_pending.text
    assert '<script>alert(1)</script>' not in public_pending.text
    assert '提交人' not in public_pending.text
    assert public_pending.headers['cache-control'] == 'no-store'
    assert desktop_token not in public_pending.text
    assert '13900000000' in public_pending.text and '13900000304' in public_pending.text
    assert client.get('/work/number-inbox').text.count('title="点击复制号码"') == 306
    bad_csrf = client.post(f'/work/number-inbox/{item_id}/done', data={'csrf': 'wrong'})
    assert bad_csrf.status_code == 403
    # Refreshing the redirected GET cannot submit the same number again.
    client.get(str(first.url))
    with db() as conn:
        assert conn.execute('SELECT COUNT(*) n FROM number_inbox').fetchone()['n'] == 306

    rotate_desktop = client.post(
        '/work/number-inbox/rotate-desktop-token',
        data={'csrf': csrf},
        follow_redirects=False,
    )
    assert rotate_desktop.status_code == 303
    assert rotate_desktop.headers['location'] == '/work/number-inbox?view=settings'
    with db() as conn:
        new_desktop_token = conn.execute(
            'SELECT value FROM app_meta WHERE key=?',
            (DESKTOP_TOKEN_META_KEY,),
        ).fetchone()['value']
        assert new_desktop_token != desktop_token
    old_feed = client.get(
        '/api/number-inbox/pending',
        headers={'Authorization': f'Bearer {desktop_token}'},
        follow_redirects=False,
    )
    assert old_feed.status_code == 401
    new_feed = client.get(
        '/api/number-inbox/pending',
        headers={'Authorization': f'Bearer {new_desktop_token}'},
    )
    assert new_feed.status_code == 200

    rotate = client.post(
        '/work/number-inbox/rotate-link',
        data={'csrf': csrf},
        follow_redirects=False,
    )
    assert rotate.status_code == 303
    assert rotate.headers['location'] == '/work/number-inbox?view=settings'
    with db() as conn:
        new_token = conn.execute('SELECT value FROM app_meta WHERE key=?', (TOKEN_META_KEY,)).fetchone()['value']
        assert new_token != token

    old_link = client.get(f'/number-submit/{token}', follow_redirects=False)
    assert old_link.status_code == 404
    assert client.get(f'/number-submit/{token}/pending').status_code == 404
    new_link = client.get(f'/number-submit/{new_token}')
    assert new_link.status_code == 200

    # Multiple repeated form keys are submitted together and normalized/deduplicated.
    batch = client.post(f'/number-submit/{new_token}', data={
        'number': ['13600000001', '+86 13600000002', '136 0000 0001', '', '13800138000'],
        'submitter': 'ignored legacy field',
    })
    assert batch.status_code == 200, batch.text
    assert batch.history[0].status_code == 303
    assert batch.text.count('number-type-new') == 2
    refreshed = client.get(f'/number-submit/{new_token}/pending')
    assert refreshed.text.count('number-type-new') == 2
    export_script = client.get('/static/number-inbox-v162.js')
    assert export_script.status_code == 200
    assert 'showDirectoryPicker' in export_script.text
    assert '号码加集团.xlsx' in export_script.text
    another_client = TestClient(app)
    assert 'number-type-new' not in another_client.get(f'/number-submit/{new_token}/pending').text
    assert 'httponly' in batch.history[0].headers['set-cookie'].lower()
    assert f'Path=/number-submit/{new_token}' in batch.history[0].headers['set-cookie']
    with db() as conn:
        batch_rows = conn.execute("SELECT * FROM number_inbox WHERE normalized_number IN ('13600000001','13600000002')").fetchall()
        assert len(batch_rows) == 2
        assert batch_rows[0]['submitted_at'] == batch_rows[1]['submitted_at']
        assert all(row['submitter'] == '' for row in batch_rows)
        before = conn.execute('SELECT COUNT(*) n FROM number_inbox').fetchone()['n']
    invalid_batch = client.post(f'/number-submit/{new_token}', data={'number': ['13600000003', 'bad']})
    assert invalid_batch.status_code == 400
    assert '13600000003' in invalid_batch.text
    with db() as conn:
        assert conn.execute('SELECT COUNT(*) n FROM number_inbox').fetchone()['n'] == before
    assert client.post(f'/number-submit/{new_token}', data={'number': [' ', '']}).status_code == 400
    assert client.post(f'/number-submit/{new_token}', data={'number': ['13600000004'] * 101}).status_code == 400
    assert client.get('/static/number-submit-v162.js').status_code == 200
    print('number inbox bulk submit, pending rows, validation, token and desktop contracts passed')


if __name__ == '__main__':
    main()
