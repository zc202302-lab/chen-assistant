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
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v151-search-')
TEST_DB = Path(_TMPDIR.name) / 'app.db'
os.environ['APP_DB_PATH'] = str(TEST_DB)
os.environ.update({
    'APP_USERNAME': 'ui-test',
    'APP_PASSWORD_SALT': 'dGVzdHNhbHQ=',
    'APP_PASSWORD_HASH': 'x',
    'APP_SESSION_SECRET': 'v151-search-session',
    'APP_ENCRYPTION_KEY': 'x',
    'APP_SECURE_COOKIE': '0',
})

from app.db import db, init_db, now_iso  # noqa: E402
from app.security import create_session  # noqa: E402
from app.v10_routes import ensure_v10_schema  # noqa: E402


def seed():
    init_db()
    ensure_v10_schema()
    now = now_iso()
    with db() as conn:
        cid = int(conn.execute(
            '''INSERT INTO customers(name,group_code,tax_id,payment_enabled,created_at,updated_at)
               VALUES(?,?,?,?,?,?)''',
            ('欧木自动搜索客户', 'OM-151', 'TAX-151', 1, now, now),
        ).lastrowid)
        sid = int(conn.execute(
            '''INSERT INTO services(customer_id,service_type,holder_name,number,account,sort_order)
               VALUES(?,?,?,?,?,?)''',
            (cid, '成员', '欧木测试成员', '139 0000-0151', 'OM-ACC-151', 10),
        ).lastrowid)
    token, _, _ = create_session()
    return cid, sid, token


def wait_http(url: str):
    for _ in range(100):
        try:
            if urllib.request.urlopen(url, timeout=1).status == 200:
                return
        except Exception:
            pass
        time.sleep(.2)
    raise RuntimeError('server start failed')


def main():
    cid, sid, token = seed()
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8147'],
        cwd=ROOT, env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8147/health')
        from playwright.sync_api import expect, sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1440, 'height': 900})
            context.grant_permissions(['clipboard-read', 'clipboard-write'], origin='http://127.0.0.1:8147')
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8147'}])
            page = context.new_page()


            # The inline dashboard search is a separate mature interaction from
            # the top-bar overlay. Exercise its real initializer and navigation
            # at both desktop and phone sizes after page-scoped asset loading.
            for viewport in [{'width': 1440, 'height': 900}, {'width': 390, 'height': 844}]:
                page.set_viewport_size(viewport)
                page.goto('http://127.0.0.1:8147/work/customers', wait_until='networkidle')
                dashboard_url = page.url
                inline = page.locator('[data-v03-home-search]')
                expect(inline).to_have_count(1)
                field = inline.locator('[data-v03-search-input]')
                expect(field).to_be_visible()
                field.fill('欧木')
                expect(page).to_have_url(dashboard_url)
                result = inline.locator('[data-v03-search-result]').filter(has_text='欧木自动搜索客户')
                expect(result).to_be_visible(timeout=4000)
                expect(result).to_have_attribute('href', f'/customers/{cid}')
                field.press('ArrowDown')
                field.press('Enter')
                expect(page).to_have_url(f'http://127.0.0.1:8147/customers/{cid}', timeout=5000)
                page.goto('http://127.0.0.1:8147/work/customers', wait_until='networkidle')
                field = page.locator('[data-v03-search-input]')
                field.fill('OM-151')
                result = page.locator('[data-v03-search-result]').filter(has_text='欧木自动搜索客户')
                expect(result).to_be_visible(timeout=4000)
                result.click()
                expect(page).to_have_url(f'http://127.0.0.1:8147/customers/{cid}', timeout=5000)
            page.set_viewport_size({'width': 1440, 'height': 900})

            # Work quick search stays on the current document while typing and
            # shows customer results first, before any detail-hit sections.
            page.goto('http://127.0.0.1:8147/work', wait_until='networkidle')
            start_url = page.url
            page.locator('[data-quick-search-trigger]').click()
            search_input = page.locator('[data-quick-search-input]')
            expect(search_input).to_be_visible()
            search_input.fill('欧木')
            expect(page).to_have_url(start_url)
            live = page.locator('[data-quick-search-results]')
            expect(live).to_be_visible(timeout=4000)
            groups = live.locator('.quick-search-group-v151')
            expect(groups.nth(0).locator('.quick-search-group-head-v151 strong')).to_have_text('客户', timeout=4000)
            expect(groups.nth(0)).to_contain_text('欧木自动搜索客户')
            assert page.locator('[data-quick-search-form] input[name="q"]').count() == 0

            # Hover reveals just this field's button; copying preserves the preview
            # and writes the original individual value into the real clipboard.
            def copy_field(group, label, value, query):
                button = group.get_by_role('button', name='复制' + label, exact=True)
                button.locator('..').hover()
                expect(button).to_have_css('opacity', '1')
                button.click()
                expect(button).to_have_text('已复制')
                assert page.evaluate('navigator.clipboard.readText()') == value
                expect(page).to_have_url(start_url)
                expect(search_input).to_have_value(query)
                expect(live).to_be_visible()

            name_button = groups.nth(0).get_by_role('button', name='复制集团名称', exact=True)
            page.mouse.move(0, 0)
            expect(name_button).to_have_css('opacity', '0')
            copy_field(groups.nth(0), '集团名称', '欧木自动搜索客户', '欧木')
            copy_field(groups.nth(0), '集团编码', 'OM-151', '欧木')
            tax_button = groups.nth(0).get_by_role('button', name='复制税号', exact=True)
            page.mouse.move(0, 0)
            tax_button.focus()
            expect(tax_button).to_have_css('opacity', '1')
            tax_button.press('Enter')
            expect(tax_button).to_have_text('已复制')
            assert page.evaluate('navigator.clipboard.readText()') == 'TAX-151'
            expect(page).to_have_url(start_url)
            expect(live).to_be_visible()

            # Denied clipboard access gives feedback without submitting or navigating.
            page.evaluate('window.originalCopy = window.ChenCopyText; window.ChenCopyText = async () => false')
            tax_button.click()
            expect(tax_button).to_have_text('复制失败')
            expect(page).to_have_url(start_url)
            expect(live).to_be_visible()
            page.evaluate('window.ChenCopyText = window.originalCopy; delete window.originalCopy')

            # A precise phone query keeps customer as the first section and exposes
            # the concrete service hit underneath without navigating automatically.
            search_input.fill('13900000151')
            expect(page).to_have_url(start_url)
            expect(groups.nth(0).locator('.quick-search-group-head-v151 strong')).to_have_text('客户', timeout=4000)
            expect(groups.nth(0)).to_contain_text('欧木自动搜索客户')
            expect(groups.nth(1).locator('.quick-search-group-head-v151 strong')).to_have_text('号码 / 账号')
            service_link = groups.nth(1).locator('[data-quick-search-result]').first
            expect(service_link).to_contain_text('139 0000-0151')
            expect(service_link).to_have_attribute('href', f'/customers/{cid}?tab=services&focus_service={sid}')

            copy_field(groups.nth(1), '号码', '139 0000-0151', '13900000151')
            copy_field(groups.nth(1), '账号', 'OM-ACC-151', '13900000151')

            # Choosing a result is the moment navigation happens.
            service_link.click()
            expect(page).to_have_url(f'http://127.0.0.1:8147/customers/{cid}?tab=services&focus_service={sid}', timeout=5000)

            # The main/home search uses the same live behavior and still prioritizes
            # customers in the cross-space suggestion list.
            page.goto('http://127.0.0.1:8147/', wait_until='networkidle')
            home_url = page.url
            page.locator('[data-quick-search-trigger]').click()
            home_input = page.locator('[data-quick-search-input]')
            home_input.fill('欧木')
            expect(page).to_have_url(home_url)
            home_groups = page.locator('[data-quick-search-results] .quick-search-group-v151')
            expect(home_groups.nth(0).locator('.quick-search-group-head-v151 strong')).to_have_text('客户', timeout=4000)
            expect(home_groups.nth(0)).to_contain_text('欧木自动搜索客户')

            home_copy = home_groups.nth(0).get_by_role('button', name='复制集团编码', exact=True)
            home_copy.locator('..').hover()
            home_copy.click()
            expect(home_copy).to_have_text('已复制')
            assert page.evaluate('navigator.clipboard.readText()') == 'OM-151'
            expect(page).to_have_url(home_url)

            # Actual touch emulation: buttons need no hover and fit the phone card.
            mobile = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
            mobile.grant_permissions(['clipboard-read', 'clipboard-write'], origin='http://127.0.0.1:8147')
            mobile.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8147'}])
            phone = mobile.new_page()
            phone.goto(start_url, wait_until='networkidle')
            phone.locator('[data-quick-search-trigger]').tap()
            phone.locator('[data-quick-search-input]').fill('欧木')
            phone_group = phone.locator('.quick-search-group-v151').first
            phone_copy = phone_group.get_by_role('button', name='复制集团编码', exact=True)
            expect(phone_copy).to_be_visible(timeout=4000)
            expect(phone_copy).to_have_css('opacity', '1')
            phone_copy.tap()
            expect(phone_copy).to_have_text('已复制')
            assert phone.evaluate('navigator.clipboard.readText()') == 'OM-151'
            expect(phone).to_have_url(start_url)
            expect(phone.locator('[data-quick-search-results]')).to_be_visible()
            assert phone.locator('.quick-search-card-v15').evaluate('(el) => el.scrollWidth <= el.clientWidth')
            phone_group.locator('[data-quick-search-result]').first.tap()
            expect(phone).to_have_url(f'http://127.0.0.1:8147/customers/{cid}', timeout=5000)
            mobile.close()
            browser.close()
        print('v1.5.1 live quick-search and clipboard desktop/keyboard/touch acceptance passed')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
