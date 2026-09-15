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
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v143-browser-')
TEST_DB = Path(_TMPDIR.name) / 'app.db'
os.environ['APP_DB_PATH'] = str(TEST_DB)
os.environ.update({
    'APP_USERNAME': 'ui-test',
    'APP_PASSWORD_SALT': 'dGVzdHNhbHQ=',
    'APP_PASSWORD_HASH': 'x',
    'APP_SESSION_SECRET': 'v143-browser-session',
    'APP_ENCRYPTION_KEY': 'x',
    'APP_SECURE_COOKIE': '0',
})

from app.db import db, init_db, now_iso  # noqa: E402
from app.payment_v02 import current_period  # noqa: E402
from app.security import create_session  # noqa: E402
from app.v0212_routes import _save_runtime  # noqa: E402


def seed():
    init_db()
    now = now_iso()
    period = current_period()
    with db() as conn:
        cid = int(conn.execute(
            'INSERT INTO customers(name,group_code,payment_enabled,created_at,updated_at) VALUES(?,?,?,?,?)',
            ('v143客户整体启停验收', 'V143', 1, now, now),
        ).lastrowid)
        active_sid = int(conn.execute(
            '''INSERT INTO services
               (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
                payment_cycle,payment_interval_months,next_payment_period,active_from_period,
                sort_order,source_row,payment_method)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (cid, '成员', '启用业务', '13800001431', 'V143-A', 100, 0,
             '1个月', 1, period, period, 10, 1, '微信'),
        ).lastrowid)
        inactive_sid = int(conn.execute(
            '''INSERT INTO services
               (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
                payment_cycle,payment_interval_months,next_payment_period,active_from_period,
                sort_order,source_row,payment_method)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (cid, '成员', '已停用业务', '13800001432', 'V143-B', 200, 0,
             '1个月', 1, period, period, 20, 2, '微信'),
        ).lastrowid)
        for sid, amount in ((active_sid, 100), (inactive_sid, 200)):
            conn.execute(
                'INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at) VALUES(?,?,?,?,?)',
                (sid, '1900-01', 'variable', amount, now),
            )
        _save_runtime(conn, inactive_sid, status='inactive')
    token, _, _ = create_session()
    return cid, active_sid, inactive_sid, token


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
    cid, active_sid, inactive_sid, token = seed()
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8146'],
        cwd=ROOT, env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8146/health')
        from playwright.sync_api import expect, sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1440, 'height': 900})
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8146'}])
            page = context.new_page()

            # Navigation remains real back/forward, but is now large and centered
            # in the page top bar instead of tucked into the left corner.
            page.goto('http://127.0.0.1:8146/work', wait_until='networkidle')
            nav = page.locator('[data-history-nav]')
            back = page.locator('[data-history-back]')
            forward = page.locator('[data-history-forward]')
            expect(nav).to_be_visible()
            box = nav.bounding_box()
            assert box, 'global history nav has no bounding box'
            assert abs((box['x'] + box['width'] / 2) - 720) <= 4, box
            b = back.bounding_box(); f = forward.bounding_box()
            assert b and f and b['width'] >= 44 and b['height'] >= 36 and f['width'] >= 44 and f['height'] >= 36

            page.goto('http://127.0.0.1:8146/work/customers?home=payment', wait_until='networkidle')
            expect(page.locator('[data-history-back]')).to_be_enabled()
            page.locator('[data-history-back]').click()
            expect(page).to_have_url('http://127.0.0.1:8146/work', timeout=3000)
            expect(page.locator('[data-history-forward]')).to_be_enabled(timeout=3000)
            page.locator('[data-history-forward]').click()
            expect(page).to_have_url('http://127.0.0.1:8146/work/customers?home=payment', timeout=3000)

            # Customer-level status lives on the Business page. Existing customer
            # and every existing service default/preserve their prior status.
            page.goto(f'http://127.0.0.1:8146/customers/{cid}?tab=services', wait_until='networkidle')
            status = page.locator('[data-customer-runtime-v143]')
            expect(status).to_be_visible()
            expect(status.locator('[data-customer-runtime-badge]')).to_have_text('已启用', timeout=3000)
            expect(status.locator('[data-customer-runtime-action]')).to_have_text('停用客户')
            expect(page.locator('#requiredCount')).to_have_text('1')
            assert page.locator(f'[data-business-row][data-service-id="{inactive_sid}"]').count() == 1

            # Stop the whole customer: no service-level status is overwritten, all
            # payment reminders disappear, and the Business page explicitly shows
            # that the customer-level gate is the reason.
            status.locator('[data-customer-runtime-action]').click()
            page.wait_for_load_state('networkidle')
            status = page.locator('[data-customer-runtime-v143]')
            expect(status.locator('[data-customer-runtime-badge]')).to_have_text('已停用', timeout=3000)
            expect(status.locator('[data-customer-runtime-action]')).to_have_text('重新启用')
            expect(page.locator('.customer-inactive-note-v143')).to_contain_text('不参与任何缴费提醒')
            expect(page.locator('[data-payment-row]')).to_have_count(0)
            expect(page.locator('.v023-review-count').nth(0)).to_contain_text('本月应缴 0')
            expect(page.locator('#paymentReadiness')).to_have_text('客户已停用，不参与本月缴费提醒')
            expect(page.locator('[data-business-row] [data-attr-key="__payment_state__"] strong')).to_have_count(2)
            for i in range(2):
                expect(page.locator('[data-business-row] [data-attr-key="__payment_state__"] strong').nth(i)).to_have_text('客户停用')

            with db() as conn:
                customer_runtime = conn.execute(
                    'SELECT status FROM customer_runtime_v143 WHERE customer_id=?', (cid,)
                ).fetchone()
                assert customer_runtime and customer_runtime['status'] == 'inactive'
                service_runtime = conn.execute(
                    'SELECT service_id,status FROM service_runtime_v0212 WHERE service_id IN (?,?) ORDER BY service_id',
                    (active_sid, inactive_sid),
                ).fetchall()
                by_id = {int(row['service_id']): row['status'] for row in service_runtime}
                # Active service has no runtime row; inactive service must remain inactive.
                assert by_id.get(inactive_sid) == 'inactive', by_id
                assert by_id.get(active_sid, 'active') == 'active', by_id

            # Re-enable the customer. The active service returns to the payment list,
            # while the individually disabled service stays disabled exactly as before.
            status.locator('[data-customer-runtime-action]').click()
            page.wait_for_load_state('networkidle')
            status = page.locator('[data-customer-runtime-v143]')
            expect(status.locator('[data-customer-runtime-badge]')).to_have_text('已启用', timeout=3000)
            expect(page.locator('[data-payment-row]')).to_have_count(1)
            expect(page.locator(f'[data-payment-row][data-service-id="{active_sid}"]')).to_have_count(1)
            expect(page.locator(f'[data-payment-row][data-service-id="{inactive_sid}"]')).to_have_count(0)
            with db() as conn:
                row = conn.execute('SELECT status FROM service_runtime_v0212 WHERE service_id=?', (inactive_sid,)).fetchone()
                assert row and row['status'] == 'inactive'
                customer_runtime = conn.execute('SELECT status FROM customer_runtime_v143 WHERE customer_id=?', (cid,)).fetchone()
                assert customer_runtime and customer_runtime['status'] == 'active'

            browser.close()

        print('v1.4.3 centered navigation + customer-level active/inactive acceptance passed')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
