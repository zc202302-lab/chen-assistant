from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v161-ui-')
TEST_DB = Path(_TMPDIR.name) / 'app.db'
os.environ['APP_DB_PATH'] = str(TEST_DB)
os.environ.update({
    'APP_USERNAME': 'ui-test',
    'APP_PASSWORD_SALT': 'dGVzdHNhbHQ=',
    'APP_PASSWORD_HASH': 'x',
    'APP_SESSION_SECRET': 'v161-ui-session',
    'APP_ENCRYPTION_KEY': 'x',
    'APP_SECURE_COOKIE': '0',
})

from app.db import db, init_db, now_iso  # noqa: E402
from app.security import create_session  # noqa: E402


def seed():
    init_db()
    now = now_iso()
    with db() as conn:
        rows = [
            ('中泰物流有限公司', 'c0000085396', 5243, '成员'),
            ('临淄区敬仲镇东柳村卫生室', 'c7216774127', 120, '数据专线'),
            ('临淄区朱台镇中心幼儿园', 'c7200565131', 100, '企宽'),
            ('临淄区朱台镇宁王幼儿园（产）', 'c7201786272', 100, 'FTTO'),
        ]
        for i, (name, code, fee, service_type) in enumerate(rows):
            cid = int(conn.execute(
                '''INSERT INTO customers(name,group_code,tax_id,payment_enabled,created_at,updated_at)
                   VALUES(?,?,?,?,?,?)''',
                (name, code, '', 1, now, now),
            ).lastrowid)
            conn.execute(
                '''INSERT INTO services(customer_id,service_type,holder_name,number,account,monthly_fee,sort_order)
                   VALUES(?,?,?,?,?,?,?)''',
                (cid, service_type, name, f'1380000{i:04d}', f'ACC-{i}', fee, 10),
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


def centered(box, viewport_width, tolerance=5):
    return abs((box['x'] + box['width'] / 2) - viewport_width / 2) <= tolerance


def main():
    token = seed()
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8161'],
        cwd=ROOT,
        env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8161/health')
        from playwright.sync_api import expect, sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()

            desktop = browser.new_context(viewport={'width': 1440, 'height': 900})
            desktop.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8161'}])
            page = desktop.new_page()
            page.goto('http://127.0.0.1:8161/customers', wait_until='networkidle')

            history_box = page.locator('[data-history-nav]').bounding_box()
            search_box = page.locator('[data-quick-search-trigger]').bounding_box()
            nav_box = page.locator('.global-primary-nav').bounding_box()
            assert history_box
            brand_box = page.locator('.brand').bounding_box()
            assert brand_box
            assert history_box['x'] > brand_box['x'] + brand_box['width']
            assert history_box['x'] < 360
            assert search_box and search_box['x'] > 1360
            assert nav_box and centered(nav_box, 1440)
            assert nav_box['y'] > history_box['y']

            cards = page.locator('.customer-card-v161')
            expect(cards).to_have_count(4)
            b0 = cards.nth(0).bounding_box()
            b1 = cards.nth(1).bounding_box()
            assert b0 and b1 and abs(b0['y'] - b1['y']) < 3
            assert b0['width'] > 450
            expect(page.locator('.customer-filter-v161 .pill').first).to_have_class(re.compile(r'active'))

            mobile = browser.new_context(viewport={'width': 390, 'height': 844})
            mobile.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8161'}])
            mpage = mobile.new_page()
            mpage.goto('http://127.0.0.1:8161/customers', wait_until='networkidle')

            mh = mpage.locator('[data-history-nav]').bounding_box()
            ms = mpage.locator('[data-quick-search-trigger]').bounding_box()
            mn = mpage.locator('.global-primary-nav').bounding_box()
            assert mh and centered(mh, 390)
            assert ms and ms['x'] > 335 and ms['width'] <= 42
            assert mn and mn['y'] > mh['y']

            mcards = mpage.locator('.customer-card-v161')
            mb0 = mcards.nth(0).bounding_box()
            mb1 = mcards.nth(1).bounding_box()
            assert mb0 and mb1 and mb1['y'] > mb0['y'] + mb0['height']
            assert mb0['width'] > 340
            assert mpage.locator('.customer-filter-v161').evaluate('(el) => el.scrollWidth >= el.clientWidth')
            expect(mpage.get_by_text('Excel导入/导出', exact=True)).to_be_visible()
            expect(mpage.get_by_text('＋ 新建', exact=True)).to_be_visible()

            browser.close()

        print('v1.6.2 desktop header + v1.6.1 mobile responsive acceptance passed')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
