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
TMP = tempfile.TemporaryDirectory(prefix='chen-v152-high-frequency-')
TEST_DB = Path(TMP.name) / 'app.db'
os.environ.update({
    'APP_DB_PATH': str(TEST_DB),
    'APP_USERNAME': 'ui-test',
    'APP_PASSWORD_SALT': 'dGVzdHNhbHQ=',
    'APP_PASSWORD_HASH': 'x',
    'APP_SESSION_SECRET': 'v152-high-frequency-session',
    'APP_ENCRYPTION_KEY': 'x',
    'APP_SECURE_COOKIE': '0',
})

from app.db import db, init_db, now_iso  # noqa: E402
from app.payment_v02 import current_period  # noqa: E402
from app.security import create_session  # noqa: E402


def seed():
    init_db()
    now = now_iso()
    period = current_period()
    with db() as conn:
        cid = int(conn.execute(
            'INSERT INTO customers(name,group_code,payment_enabled,created_at,updated_at) VALUES(?,?,?,?,?)',
            ('v152高频缴费客户', 'V152', 1, now, now),
        ).lastrowid)
        ids = []
        for idx, amount in enumerate((100, 200, 300), 1):
            sid = int(conn.execute(
                '''INSERT INTO services
                   (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
                    payment_cycle,payment_interval_months,next_payment_period,active_from_period,
                    sort_order,source_row,payment_method)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (cid, '成员', f'成员{idx}', f'1390000015{idx}', f'ACC-V152-{idx}', amount, 0,
                 '1个月', 1, '', period, idx * 10, idx, '微信'),
            ).lastrowid)
            ids.append(sid)
            conn.execute(
                '''INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at)
                   VALUES(?,?,?,?,?)''',
                (sid, '1900-01', 'variable', 0, now),
            )
    token, _, _ = create_session()
    return cid, ids, token


def wait_http(url: str):
    for _ in range(120):
        try:
            if urllib.request.urlopen(url, timeout=1).status == 200:
                return
        except Exception:
            pass
        time.sleep(.2)
    raise RuntimeError('server start failed')


def main():
    cid, ids, token = seed()
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8158'],
        cwd=ROOT, env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8158/health')
        from playwright.sync_api import expect, sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1500, 'height': 950})
            context.grant_permissions(['clipboard-read', 'clipboard-write'], origin='http://127.0.0.1:8158')
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8158'}])
            page = context.new_page()

            # Customer management is payment-first and does not require a second
            # tab click before the user's main work becomes visible.
            page.goto('http://127.0.0.1:8158/work/customers', wait_until='networkidle')
            expect(page.locator('[data-home-tab="payment"]')).to_have_class('active')
            expect(page.locator('[data-home-panel="payment"]')).to_be_visible()
            assert page.locator('[data-home-tab]').first.get_attribute('data-home-tab') == 'payment'

            # Home now exposes customer management directly as the high-frequency
            # work entry rather than forcing a detour through /work.
            page.goto('http://127.0.0.1:8158/', wait_until='networkidle')
            expect(page.locator('a.v10-primary[href="/work/customers"]')).to_be_visible()
            expect(page.locator('.bottom-nav a[href="/work/customers"]')).to_contain_text('客户')

            page.goto(f'http://127.0.0.1:8158/customers/{cid}', wait_until='networkidle')
            page.wait_for_timeout(900)
            rows = [page.locator(f'[data-payment-row][data-service-id="{sid}"]') for sid in ids]
            for row in rows:
                expect(row).to_have_attribute('data-confirmed', '0')

            # Monthly total is physically at the bottom of the payment table and
            # visually anchored to the table's bottom-right edge.
            total_row = page.locator('[data-payment-total-row-v152]')
            expect(total_row).to_be_visible()
            total_box = total_row.locator('.payment-total-v152')
            expect(total_box.locator('#paymentGrandTotal')).to_have_text('¥600')
            assert page.locator('#paymentSortable > *').last.get_attribute('data-payment-total-row-v152') == '1'
            row_rect = total_row.bounding_box()
            total_rect = total_box.bounding_box()
            assert row_rect and total_rect
            assert abs((row_rect['x'] + row_rect['width']) - (total_rect['x'] + total_rect['width'])) <= 20

            # Manual 未核对 -> 已核对: immediately move to the next pending amount
            # and copy that destination row's account to the clipboard.
            rows[0].locator('[data-review-toggle]').click()
            expect(rows[0]).to_have_attribute('data-confirmed', '1', timeout=4000)
            expect(rows[1].locator('.quick-amount')).to_be_focused(timeout=4000)
            clipboard = page.evaluate('navigator.clipboard.readText()')
            assert clipboard == 'ACC-V152-2', clipboard

            # Enter save keeps the established advance behavior and adds the same
            # destination-account copy. Use a real amount change so the mature
            # rollback/review semantics are exercised rather than bypassed.
            amount2 = rows[1].locator('.quick-amount')
            amount2.fill('225')
            amount2.press('Enter')
            expect(rows[2].locator('.quick-amount')).to_be_focused(timeout=4000)
            clipboard = page.evaluate('navigator.clipboard.readText()')
            assert clipboard == 'ACC-V152-3', clipboard

            browser.close()
        print('v1.5.2 high-frequency payment flow acceptance passed')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
