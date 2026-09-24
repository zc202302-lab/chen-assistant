from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v160-info-')
TEST_DB = Path(_TMPDIR.name) / 'app.db'
os.environ['APP_DB_PATH'] = str(TEST_DB)
os.environ.update({
    'APP_USERNAME': 'ui-test',
    'APP_PASSWORD_SALT': 'dGVzdHNhbHQ=',
    'APP_PASSWORD_HASH': 'x',
    'APP_SESSION_SECRET': 'v160-info-session',
    'APP_ENCRYPTION_KEY': Fernet.generate_key().decode(),
    'APP_SECURE_COOKIE': '0',
})

from app.db import db, init_db, now_iso  # noqa: E402
from app.security import create_session, decrypt_secret, encrypt_secret  # noqa: E402
from app.v160_information_center import ensure_v160_schema  # noqa: E402


def seed():
    init_db()
    now = now_iso()
    with db() as conn:
        ensure_v160_schema(conn)
        conn.execute(
            '''INSERT INTO information_records
               (title,category,tags,body_enc,link_url,pinned,archived,created_at,updated_at)
               VALUES(?,?,?,?,?,1,0,?,?)''',
            ('美国VPS', '服务器', 'VPS Linux 代理', encrypt_secret('配置：1核1G\n用途：生产节点'), 'https://example.com', now, now),
        )
        conn.execute(
            '''INSERT INTO website_accounts
               (platform,url,username,email,phone,tags,notes,password_enc,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)''',
            ('GitHub', 'https://github.com', 'tester', '', '', '开发', '', encrypt_secret('secret'), now, now),
        )
    token, _, _ = create_session()
    return token


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
    token = seed()
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8160'],
        cwd=ROOT,
        env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8160/health')
        from playwright.sync_api import expect, sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1440, 'height': 900})
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8160'}])
            page = context.new_page()

            page.goto('http://127.0.0.1:8160/info', wait_until='networkidle')
            expect(page.get_by_role('heading', name='资料中心')).to_be_visible()
            expect(page.get_by_text('美国VPS', exact=True)).to_be_visible()
            expect(page.get_by_text('GitHub', exact=True)).to_have_count(0)
            expect(page.locator('.global-primary-nav a[href="/info"]')).to_have_class(/active/)

            page.goto('http://127.0.0.1:8160/info?q=生产节点', wait_until='networkidle')
            expect(page.get_by_text('美国VPS', exact=True)).to_be_visible()

            page.goto('http://127.0.0.1:8160/info/new', wait_until='networkidle')
            page.locator('input[name="title"]').fill('PON网络基础')
            page.locator('input[name="category"]').fill('学习')
            page.locator('input[name="tags"]').fill('网络 PON')
            page.locator('textarea[name="body"]').fill('OLT 与 ONU 的基础关系')
            page.get_by_role('button', name='保存').click()
            page.wait_for_load_state('networkidle')
            expect(page.get_by_role('heading', name='PON网络基础')).to_be_visible()
            expect(page.get_by_text('OLT 与 ONU 的基础关系', exact=True)).to_be_visible()

            with db() as conn:
                row = conn.execute("SELECT body_enc FROM information_records WHERE title='PON网络基础'").fetchone()
                assert row and row['body_enc'] != 'OLT 与 ONU 的基础关系'
                assert decrypt_secret(row['body_enc']) == 'OLT 与 ONU 的基础关系'

            page.goto('http://127.0.0.1:8160/work', wait_until='networkidle')
            expect(page.get_by_text('网站 / 平台账户', exact=True)).to_have_count(0)

            page.goto('http://127.0.0.1:8160/global-search?q=PON网络基础', wait_until='networkidle')
            expect(page.locator('h2').filter(has_text='资料')).to_be_visible()
            expect(page.get_by_text('PON网络基础', exact=True)).to_be_visible()

            browser.close()

        print('v1.6.0 information center browser acceptance passed')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
