from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v150-live-refresh-')
TEST_DB = Path(_TMPDIR.name) / 'app.db'
os.environ['APP_DB_PATH'] = str(TEST_DB)
os.environ.update({
    'APP_USERNAME': 'ui-test',
    'APP_PASSWORD_SALT': 'dGVzdHNhbHQ=',
    'APP_PASSWORD_HASH': 'x',
    'APP_SESSION_SECRET': 'ui-test-session-secret',
    'APP_ENCRYPTION_KEY': 'x',
    'APP_SECURE_COOKIE': '0',
})

from app.db import db, init_db, now_iso  # noqa: E402
from app.security import create_session  # noqa: E402


def seed():
    init_db()
    now = now_iso()
    with db() as conn:
        cid = int(conn.execute(
            '''INSERT INTO customers(name,group_code,tax_id,payment_enabled,created_at,updated_at)
               VALUES(?,?,?,?,?,?)''',
            ('实时刷新客户', 'LIVE-001', 'TAX-001', 1, now, now),
        ).lastrowid)
    token, _, _ = create_session()
    return cid, token


def wait_http(url):
    for _ in range(100):
        try:
            if urllib.request.urlopen(url, timeout=1).status == 200:
                return
        except Exception:
            pass
        time.sleep(.2)
    raise RuntimeError('server start failed')


def main():
    cid, token = seed()
    assert TEST_DB.resolve() != (ROOT / 'data' / 'app.db').resolve()
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8143'],
        cwd=ROOT,
        env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8143/health')
        from playwright.sync_api import expect, sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.add_cookies([{
                'name': 'session_token',
                'value': token,
                'url': 'http://127.0.0.1:8143',
            }])
            page = context.new_page()
            page.goto(f'http://127.0.0.1:8143/customers/{cid}', wait_until='networkidle')
            expect(page.locator('.v023-name-line h1')).to_have_text('实时刷新客户')
            expect(page.locator('.v023-task-head .tab-text-link')).to_have_text('全部 0')
            assert page.evaluate('typeof window.ChenLiveRefresh?.refresh') == 'function'

            # Let the initial live read establish its signature, then mutate the DB
            # outside the browser. The open page must catch up without navigation.
            page.wait_for_timeout(750)
            sentinel = 'keep-the-same-document'
            page.evaluate('(value) => { window.__liveRefreshSentinel = value; }', sentinel)
            now = now_iso()
            with db() as conn:
                conn.execute(
                    'UPDATE customers SET name=?,group_code=?,tax_id=?,updated_at=? WHERE id=?',
                    ('实时刷新客户·已更新', 'LIVE-002', 'TAX-002', now, cid),
                )
                conn.execute(
                    'INSERT INTO tasks(customer_id,title,remind_date,note,done,created_at) VALUES(?,?,?,?,?,?)',
                    (cid, '无需F5的新待办', '2026-09-17', '', 0, now),
                )

            page.evaluate('window.ChenLiveRefresh.refresh()')
            expect(page.locator('.v023-name-line h1')).to_have_text('实时刷新客户·已更新', timeout=4000)
            expect(page.locator('.v023-identity-strip > div:nth-child(1) b')).to_have_text('LIVE-002')
            expect(page.locator('.v023-identity-strip > div:nth-child(2) b')).to_have_text('TAX-002')
            expect(page.locator('.v023-task-head .tab-text-link')).to_have_text('全部 1')
            expect(page.locator('.v023-task-card .v023-task-line span')).to_have_text('无需F5的新待办')
            assert page.evaluate('window.__liveRefreshSentinel') == sentinel, 'live refresh must not navigate/reload the document'

            # Dirty editors are protected from polling; server changes must not
            # overwrite a value the user is actively typing.
            edit = page.locator('.v023-customer-edit input[name="name"]')
            page.locator('.v023-customer-edit summary').click()
            edit.fill('我正在输入，不能被刷新覆盖')
            with db() as conn:
                conn.execute(
                    'UPDATE customers SET name=?,updated_at=? WHERE id=?',
                    ('服务器再次更新', now_iso(), cid),
                )
            page.evaluate('window.ChenLiveRefresh.refresh()')
            page.wait_for_timeout(900)
            expect(edit).to_have_value('我正在输入，不能被刷新覆盖')
            expect(page.locator('.v023-name-line h1')).to_have_text('服务器再次更新')

            browser.close()
        print('v1.5 customer live refresh acceptance passed')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
