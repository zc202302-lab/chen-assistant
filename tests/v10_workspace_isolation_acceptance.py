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
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v14-workspace-')
TEST_DB = Path(_TMPDIR.name) / 'app.db'
os.environ['APP_DB_PATH'] = str(TEST_DB)
os.environ.update({
    'APP_USERNAME': '晨',
    'APP_PASSWORD_SALT': 'dGVzdHNhbHQ=',
    'APP_PASSWORD_HASH': 'x',
    'APP_SESSION_SECRET': 'v14-workspace-session',
    'APP_ENCRYPTION_KEY': 'x',
    'APP_SECURE_COOKIE': '0',
})

from app import config  # noqa: E402
from app.db import init_db  # noqa: E402
from app.security import create_session  # noqa: E402
from app.v10_routes import ensure_v10_schema  # noqa: E402


def wait_http(url: str):
    for _ in range(100):
        try:
            if urllib.request.urlopen(url, timeout=1).status == 200:
                return
        except Exception:
            pass
        time.sleep(.2)
    raise RuntimeError('server start failed')


def nav_labels(page):
    return [text.strip() for text in page.locator('.bottom-nav .nav-item span').all_inner_texts()]


def assert_primary_nav(page, active_label: str):
    nav = page.locator('.global-primary-nav')
    expect(nav).to_be_visible()
    assert [x.strip() for x in nav.locator('a').all_inner_texts()] == ['首页', '工作', '生活']
    expect(nav.locator('a.active')).to_have_text(active_label)


def assert_history_nav(page):
    group = page.locator('[data-history-nav]')
    back = page.locator('[data-history-back]')
    forward = page.locator('[data-history-forward]')
    expect(group).to_be_visible()
    expect(back).to_be_visible()
    expect(forward).to_be_visible()
    expect(back).to_have_attribute('aria-label', '后退')
    expect(forward).to_have_attribute('aria-label', '前进')


def main():
    init_db(); ensure_v10_schema()
    token, _, _ = create_session()

    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8141'],
        cwd=ROOT, env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8141/health')
        global expect
        from playwright.sync_api import expect, sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1450, 'height': 950})
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8141'}])
            page = context.new_page()

            page.goto('http://127.0.0.1:8141/', wait_until='networkidle')
            assert nav_labels(page) == ['首页', '客户', '生活', '搜索']
            assert_primary_nav(page, '首页')
            expect(page.get_by_role('heading', name='客户管理')).to_have_count(0)
            expect(page.get_by_text('生活空间', exact=True)).to_have_count(0)
            assert_history_nav(page)

            page.goto('http://127.0.0.1:8141/work', wait_until='networkidle')
            assert nav_labels(page) == ['工作', '客户', '资料', '搜索']
            assert_primary_nav(page, '工作')
            expect(page.get_by_role('heading', name='客户管理')).to_be_visible()
            expect(page.get_by_role('heading', name='工作资料')).to_be_visible()
            expect(page.locator('.brand')).to_have_attribute('href', '/work')
            expect(page.locator('.search-link')).to_have_attribute('href', '/search')
            expect(page.locator('.brand')).to_contain_text(f'v{config.APP_VERSION}')
            assert_history_nav(page)

            page.goto('http://127.0.0.1:8141/work/customers', wait_until='networkidle')
            assert nav_labels(page) == ['工作', '客户', '资料', '搜索']
            assert_primary_nav(page, '工作')
            work_tabs = page.locator('[data-home-tabs] [data-home-tab]')
            assert [x.strip() for x in work_tabs.all_inner_texts()] == ['缴费 0', '待办 0', '优惠 0', '最近客户']
            expect(page.locator('.brand')).to_have_attribute('href', '/work')
            assert_history_nav(page)

            page.goto('http://127.0.0.1:8141/work/library', wait_until='networkidle')
            assert nav_labels(page) == ['工作', '客户', '资料', '搜索']
            assert_primary_nav(page, '工作')
            expect(page.get_by_role('heading', name='工作资料')).to_be_visible()
            expect(page.get_by_role('heading', name='产品资料')).to_be_visible()
            expect(page.get_by_role('heading', name='资费资料')).to_be_visible()
            expect(page.get_by_text('架构已建立 · 内容功能待开发', exact=True)).to_be_visible()
            expect(page.locator('.brand')).to_have_attribute('href', '/work')
            assert_history_nav(page)

            page.goto('http://127.0.0.1:8141/work?home=payment', wait_until='networkidle')
            assert '/work/customers?home=payment' in page.url
            expect(page.locator('[data-home-tab="payment"]')).to_have_class('active')

            page.goto('http://127.0.0.1:8141/search', wait_until='networkidle')
            assert nav_labels(page) == ['工作', '客户', '资料', '搜索']
            assert_primary_nav(page, '工作')
            expect(page.locator('input[name="q"]')).to_have_attribute('placeholder', '客户名 / 集团编码 / 税号 / 号码 / 账号 / 网站账户')
            expect(page.get_by_text('菜谱', exact=True)).to_have_count(0)
            assert_history_nav(page)

            page.goto('http://127.0.0.1:8141/customers', wait_until='networkidle')
            assert nav_labels(page) == ['工作', '客户', '资料', '搜索']
            assert_primary_nav(page, '工作')
            assert_history_nav(page)

            page.goto('http://127.0.0.1:8141/global-search', wait_until='networkidle')
            assert nav_labels(page) == ['首页', '客户', '生活', '搜索']
            assert_primary_nav(page, '首页')
            expect(page.get_by_role('heading', name='搜索整个晨的助手')).to_be_visible()
            assert_history_nav(page)

            page.goto('http://127.0.0.1:8141/life', wait_until='networkidle')
            assert nav_labels(page) == ['生活', '菜谱', '记录', '工具']
            assert_primary_nav(page, '生活')
            expect(page.locator('.brand')).to_have_attribute('href', '/')
            expect(page.locator('.brand')).to_contain_text(f'v{config.APP_VERSION}')
            expect(page.get_by_text('烹饪工具', exact=True)).to_be_visible()
            assert_history_nav(page)

            page.goto('http://127.0.0.1:8141/life/recipes', wait_until='networkidle')
            assert nav_labels(page) == ['生活', '菜谱', '记录', '工具']
            assert_primary_nav(page, '生活')
            assert_history_nav(page)

            page.goto('http://127.0.0.1:8141/life/tools', wait_until='networkidle')
            assert nav_labels(page) == ['生活', '菜谱', '记录', '工具']
            assert_primary_nav(page, '生活')
            expect(page.get_by_role('heading', name='基础知识 · 计算工具')).to_be_visible()
            assert_history_nav(page)

            browser.close()

        print('v1.5.4 global top navigation + v1.4 work architecture + independent work/life navigation acceptance passed')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
