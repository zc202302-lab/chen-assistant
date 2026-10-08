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

            page.goto('http://127.0.0.1:8146/work', wait_until='networkidle')
            primary_nav = page.locator('.global-primary-nav')
            nav = page.locator('[data-history-nav]')
            back = page.locator('[data-history-back]')
            forward = page.locator('[data-history-forward]')
            expect(primary_nav).to_be_visible()
            expect(nav).to_be_visible()
            primary_box = primary_nav.bounding_box()
            history_box = nav.bounding_box()
            assert primary_box, 'global primary nav has no bounding box'
            assert history_box, 'global history nav has no bounding box'
            assert abs((primary_box['x'] + primary_box['width'] / 2) - 720) <= 4, primary_box
            reminder_box = page.locator('.reminder-entry').bounding_box()
            assert reminder_box and history_box['x'] >= reminder_box['x'] + reminder_box['width'], (reminder_box, history_box)
            assert primary_box['y'] > history_box['y'], (primary_box, history_box)
            assert page.locator('.topbar-left [data-history-nav]').count() == 1
            b = back.bounding_box(); f = forward.bounding_box()
            assert b and f and b['width'] >= 34 and b['height'] >= 32 and f['width'] >= 34 and f['height'] >= 32

            page.goto('http://127.0.0.1:8146/work/customers?home=payment', wait_until='networkidle')
            expect(page.locator('[data-history-back]')).to_be_enabled()
            page.locator('[data-history-back]').click()
            expect(page).to_have_url('http://127.0.0.1:8146/work', timeout=3000)
            expect(page.locator('[data-history-forward]')).to_be_enabled(timeout=3000)
            page.locator('[data-history-forward]').click()
            expect(page).to_have_url('http://127.0.0.1:8146/work/customers?home=payment', timeout=3000)

            page.goto(f'http://127.0.0.1:8146/customers/{cid}?tab=services', wait_until='networkidle')
            status = page.locator('[data-customer-runtime-v143]')
            expect(status).to_be_visible()
            # Customer-level status belongs to the top customer identity area, not
            # to the Business table header.
            assert page.locator('.v023-profile-card [data-customer-runtime-v143]').count() == 1
            assert page.locator('[data-customer-panel="services"] [data-customer-runtime-v143]').count() == 0
            expect(status.locator('[data-customer-runtime-badge]')).to_have_text('已启用', timeout=3000)
            expect(status.locator('[data-customer-runtime-action]')).to_have_text('停用客户')
            expect(page.locator('#requiredCount')).to_have_text('1')
            assert page.locator(f'[data-business-row][data-service-id="{inactive_sid}"]').count() == 1

            sentinel = 'same-document-status-toggle'
            page.evaluate('(value) => window.__statusSentinel = value', sentinel)
            status.locator('[data-customer-runtime-action]').click()
            expect(status.locator('[data-customer-runtime-badge]')).to_have_text('已停用', timeout=3000)
            expect(status.locator('[data-customer-runtime-action]')).to_have_text('重新启用')
            expect(page.locator('.customer-inactive-note-v143')).to_contain_text('不参与任何缴费提醒')
            expect(page.locator('[data-payment-row]')).to_have_count(0, timeout=5000)
            assert page.evaluate('window.__statusSentinel') == sentinel, 'status toggle must not reload the document'
            expect(page.locator('[data-business-row] [data-attr-key="__payment_state__"] strong')).to_have_count(2)
            for i in range(2):
                expect(page.locator('[data-business-row] [data-attr-key="__payment_state__"] strong').nth(i)).to_have_text('客户停用', timeout=5000)

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
                assert by_id.get(inactive_sid) == 'inactive', by_id
                assert by_id.get(active_sid, 'active') == 'active', by_id

            status.locator('[data-customer-runtime-action]').click()
            expect(status.locator('[data-customer-runtime-badge]')).to_have_text('已启用', timeout=3000)
            expect(page.locator('[data-payment-row]')).to_have_count(1, timeout=5000)
            expect(page.locator(f'[data-payment-row][data-service-id="{active_sid}"]')).to_have_count(1)
            expect(page.locator(f'[data-payment-row][data-service-id="{inactive_sid}"]')).to_have_count(0)
            assert page.evaluate('window.__statusSentinel') == sentinel, 're-enable must keep the same document'
            with db() as conn:
                row = conn.execute('SELECT status FROM service_runtime_v0212 WHERE service_id=?', (inactive_sid,)).fetchone()
                assert row and row['status'] == 'inactive'
                customer_runtime = conn.execute('SELECT status FROM customer_runtime_v143 WHERE customer_id=?', (cid,)).fetchone()
                assert customer_runtime and customer_runtime['status'] == 'active'

            browser.close()

        print('v1.5.4 centered primary navigation + right-side history controls + profile-level live customer status acceptance passed')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()

