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
                conn.execute(
                    'INSERT INTO contacts(customer_id,kind,name,relationship,phone) VALUES(?,?,?,?,?)',
                    (cid, '财务', '无需F5的新联系人', '缴费联系人', '13800000000'),
                )
                conn.execute(
                    'INSERT INTO visits(customer_id,visit_date,kind,result,plan,created_at) VALUES(?,?,?,?,?,?)',
                    (cid, '2026-09-16', '电话', '无需F5的新跟进', '继续跟进', now),
                )
                conn.execute(
                    '''INSERT INTO services(customer_id,service_type,holder_name,number,account,sort_order)
                       VALUES(?,?,?,?,?,?)''',
                    (cid, '测试业务', '测试成员', '13900000000', 'ACC-LIVE-001', 1),
                )

            page.evaluate('window.ChenLiveRefresh.refresh()')
            expect(page.locator('.v023-name-line h1')).to_have_text('实时刷新客户·已更新', timeout=4000)
            expect(page.locator('.v023-identity-strip > div:nth-child(1) b')).to_have_text('LIVE-002')
            expect(page.locator('.v023-identity-strip > div:nth-child(2) b')).to_have_text('TAX-002')
            expect(page.locator('.v023-name-line [data-customer-copy]')).to_have_attribute('data-customer-copy', '实时刷新客户·已更新')
            expect(page.locator('.v023-identity-strip > div:nth-child(1) [data-customer-copy]')).to_have_attribute('data-customer-copy', 'LIVE-002')
            expect(page.locator('.v023-identity-strip > div:nth-child(2) [data-customer-copy]')).to_have_attribute('data-customer-copy', 'TAX-002')
            expect(page.locator('.v023-task-head .tab-text-link')).to_have_text('全部 1')
            expect(page.locator('.v023-task-card .v023-task-line span')).to_have_text('无需F5的新待办')
            expect(page.locator('[data-customer-panel="contacts"]')).to_contain_text('无需F5的新联系人')
            expect(page.locator('[data-customer-panel="tasks"]')).to_contain_text('无需F5的新待办')
            expect(page.locator('[data-customer-panel="visits"]')).to_contain_text('无需F5的新跟进')
            expect(page.locator('[data-business-list] > [data-business-row]')).to_have_count(1)
            assert page.evaluate('window.__liveRefreshSentinel') == sentinel, 'live refresh must not navigate/reload the document'

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

            # Top-right search no longer navigates just to open search. The home
            # page behaves the same way; navigation only happens after submitting
            # a non-empty query, and customer results come first.
            page.goto('http://127.0.0.1:8143/', wait_until='networkidle')
            home_url = page.url
            page.locator('[data-quick-search-trigger]').click()
            expect(page.locator('[data-quick-search-v15]')).to_be_visible()
            assert page.url == home_url
            search_input = page.locator('[data-quick-search-input]')
            search_input.fill('服务器再次更新')
            assert page.url == home_url
            search_input.press('Enter')
            expect(page).to_have_url(__import__('re').compile(r'/global-search\?q='), timeout=4000)
            first_section = page.locator('.v10-search-sections .v10-section').nth(0)
            expect(first_section.locator('h2')).to_contain_text('客户')
            expect(first_section).to_contain_text('服务器再次更新')

            browser.close()
        print('v1.5 live refresh + quick search acceptance passed')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
