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
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v10-workspace-')
TEST_DB = Path(_TMPDIR.name) / 'app.db'
os.environ['APP_DB_PATH'] = str(TEST_DB)
os.environ.update({
    'APP_USERNAME': '晨',
    'APP_PASSWORD_SALT': 'dGVzdHNhbHQ=',
    'APP_PASSWORD_HASH': 'x',
    'APP_SESSION_SECRET': 'v10-workspace-session',
    'APP_ENCRYPTION_KEY': 'x',
    'APP_SECURE_COOKIE': '0',
})

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


def main():
    init_db(); ensure_v10_schema()
    token, _, _ = create_session()

    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8141'],
        cwd=ROOT, env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8141/health')
        from playwright.sync_api import expect, sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1450, 'height': 950})
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8141'}])
            page = context.new_page()

            # Global shell remains only a switchboard between independent spaces.
            page.goto('http://127.0.0.1:8141/', wait_until='networkidle')
            assert nav_labels(page) == ['首页', '工作', '生活', '搜索']
            expect(page.get_by_text('工作空间', exact=True)).to_be_visible()
            expect(page.get_by_text('生活空间', exact=True)).to_be_visible()

            # Work must render the mature pre-v1.0 dashboard, including the
            # payment/promotion entry tabs the user already relies on.
            page.goto('http://127.0.0.1:8141/work', wait_until='networkidle')
            assert nav_labels(page) == ['首页', '客户', '产品', '账户']
            work_tabs = page.locator('[data-home-tabs] [data-home-tab]')
            assert [x.strip() for x in work_tabs.all_inner_texts()] == [
                '待办 0', '缴费 0', '优惠 0', '最近客户'
            ]
            expect(page.locator('.brand')).to_have_attribute('href', '/work')
            expect(page.locator('.search-link')).to_have_attribute('href', '/search')

            # Original work search keeps its original scope and page.
            page.goto('http://127.0.0.1:8141/search', wait_until='networkidle')
            assert nav_labels(page) == ['首页', '客户', '产品', '账户']
            expect(page.locator('input[name="q"]')).to_have_attribute(
                'placeholder', '客户名 / 集团编码 / 税号 / 号码 / 账号 / 网站账户'
            )
            expect(page.get_by_text('菜谱', exact=True)).to_have_count(0)

            # Cross-space search exists separately and does not replace work search.
            page.goto('http://127.0.0.1:8141/global-search', wait_until='networkidle')
            assert nav_labels(page) == ['首页', '工作', '生活', '搜索']
            expect(page.get_by_role('heading', name='搜索整个晨的助手')).to_be_visible()
            expect(page.locator('form.v10-search')).to_have_attribute('action', '/global-search')

            # Life has its own navigation and cannot overwrite the work shell.
            page.goto('http://127.0.0.1:8141/life', wait_until='networkidle')
            assert nav_labels(page) == ['生活', '菜谱', '记录', '知识']
            expect(page.locator('.brand')).to_have_attribute('href', '/life')

            browser.close()

        print('v1.0 independent work/life workspace browser acceptance passed')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
