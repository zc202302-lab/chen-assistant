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
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v031-browser-')
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
from app.payment_v02 import add_periods, current_period  # noqa: E402
from app.security import create_session  # noqa: E402


def seed():
    init_db()
    now = now_iso()
    period = current_period()
    with db() as conn:
        cid = int(conn.execute(
            'INSERT INTO customers(name,group_code,payment_enabled,created_at,updated_at) VALUES(?,?,?,?,?)',
            ('v031流程验收客户', 'V031', 1, now, now),
        ).lastrowid)
        ids = []
        for idx, amount in enumerate((100, 120), 1):
            variable = idx == 1
            sid = int(conn.execute(
                '''INSERT INTO services
                   (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
                    payment_cycle,payment_interval_months,next_payment_period,active_from_period,
                    sort_order,source_row,payment_method)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (cid, '成员', f'成员{idx}', f'1380000000{idx}', f'A00{idx}', amount, 0 if variable else 1,
                 '1个月' if idx == 1 else '2个月', 1 if idx == 1 else 2,
                 '' if idx == 1 else period, period, idx * 10, idx, '微信'),
            ).lastrowid)
            ids.append(sid)
            conn.execute(
                'INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at) VALUES(?,?,?,?,?)',
                (sid, '1900-01', 'variable' if variable else 'fixed', 0 if variable else amount, now),
            )
    token, _, _ = create_session()
    return cid, ids, token


def wait_http(url):
    for _ in range(100):
        try:
            if urllib.request.urlopen(url, timeout=1).status == 200:
                return
        except Exception:
            pass
        time.sleep(.2)
    raise RuntimeError('server start failed')


def accept_next_dialog(page):
    page.once('dialog', lambda dialog: dialog.accept())


def readonly(locator):
    return bool(locator.evaluate('el => el.readOnly'))


def main():
    cid, ids, token = seed()
    assert TEST_DB.resolve() != (ROOT / 'data' / 'app.db').resolve()
    variable_sid, two_month_sid = ids
    period = current_period()
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8136'],
        cwd=ROOT,
        env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8136/health')
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1500, 'height': 1000})
            context.grant_permissions(['clipboard-read', 'clipboard-write'], origin='http://127.0.0.1:8136')
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8136'}])
            page = context.new_page()

            # The browser acceptance does not run the Windows helper. Stub only the
            # external bridge and compose payload; product state endpoints stay real.
            page.route('http://127.0.0.1:18763/health', lambda route: route.fulfill(
                status=200, content_type='application/json',
                body='{"ok":true,"verified_dispatch":true,"version":"test"}',
                headers={'Access-Control-Allow-Origin': 'http://127.0.0.1:8136'},
            ))
            page.route('http://127.0.0.1:18763/compose', lambda route: route.fulfill(
                status=200, content_type='application/json',
                body='{"ok":true,"verified":true,"mode":"test"}',
                headers={'Access-Control-Allow-Origin': 'http://127.0.0.1:8136'},
            ))
            page.route(f'**/customers/{cid}/payment-mail-compose-v031', lambda route: route.fulfill(
                status=200, content_type='application/json',
                body='{"ok":true,"recipient_b64":"dGVzdEBleGFtcGxlLmNvbQ==","subject_b64":"dGVzdA==","body_b64":"","attachment_filename_b64":"dGVzdC50eHQ=","attachment_content_base64":"MTM4MDAwMDAwMDF8MTA1"}',
            ))

            page.goto(f'http://127.0.0.1:8136/customers/{cid}', wait_until='networkidle')

            assert 'v0.3.1' in page.locator('.brand').inner_text()
            flow = page.locator('[data-v031-payment-flow]')
            flow.wait_for(state='visible')
            page.wait_for_timeout(1100)
            labels = [x.strip() for x in flow.locator('[data-v031-flow-action]').all_inner_texts()]
            assert labels == ['1 金额核对', '2 通知客户', '3 发起缴费', '4 完成缴费'], labels

            # Standalone action buttons are retired; actions now live inside stages 2 and 3.
            image_button = page.locator('[data-v031-payment-image]')
            foxmail_button = page.locator('[data-v03-foxmail-draft]')
            assert image_button.count() == 1 and image_button.is_hidden()
            assert foxmail_button.count() == 1 and foxmail_button.is_hidden()
            assert page.locator('[data-v03-mail-template]').count() == 1

            review = flow.locator('[data-v031-flow-action="review"]')
            notify = flow.locator('[data-v031-flow-action="notify"]')
            initiate = flow.locator('[data-v031-flow-action="initiate"]')
            paid = flow.locator('[data-v031-flow-action="paid"]')

            # Fixed amount is auto-confirmed and not manually toggleable.
            fixed_row = page.locator(f'[data-payment-row][data-service-id="{two_month_sid}"]')
            assert fixed_row.get_attribute('data-confirmed') == '1'
            assert fixed_row.locator('[data-row-state]').inner_text().strip() == '✓'
            assert fixed_row.locator('[data-row-state]').is_disabled()

            # One variable row starts unconfirmed; entering it enables stage 1.
            assert page.locator('#pendingCount').inner_text().strip() == '1'
            assert review.is_disabled()
            variable_input = page.locator(f'[data-payment-row][data-service-id="{variable_sid}"] .quick-amount')
            variable_input.fill('105')
            variable_input.press('Enter')
            page.wait_for_timeout(450)
            assert page.locator('#pendingCount').inner_text().strip() == '0'
            assert review.is_enabled()

            review.click()
            page.wait_for_timeout(180)
            assert review.get_attribute('aria-pressed') == 'true'
            assert notify.is_enabled()

            # Stage 2 first click only prepares/copies image; it must NOT complete the stage.
            accept_next_dialog(page)
            notify.click()
            page.wait_for_timeout(220)
            assert notify.get_attribute('aria-pressed') == 'false'
            assert '待确认' in notify.inner_text()
            assert 'awaiting-confirm' in (notify.get_attribute('class') or '')
            assert initiate.is_disabled()

            # Second click is the explicit human confirmation that WeChat send happened.
            accept_next_dialog(page)
            notify.click()
            page.wait_for_timeout(180)
            assert notify.get_attribute('aria-pressed') == 'true'
            assert initiate.is_enabled()
            assert not readonly(variable_input)

            # Customer disputes the amount after receiving the WeChat image.
            variable_input.fill('110')
            variable_input.press('Enter')
            page.wait_for_timeout(650)
            assert review.get_attribute('aria-pressed') == 'false'
            assert notify.get_attribute('aria-pressed') == 'false'
            assert initiate.get_attribute('aria-pressed') == 'false'
            assert fixed_row.get_attribute('data-confirmed') == '1'
            assert fixed_row.locator('[data-row-state]').inner_text().strip() == '✓'

            # Reconfirm corrected amount and perform stage 2 again.
            review.click()
            page.wait_for_timeout(160)
            accept_next_dialog(page)
            notify.click()
            page.wait_for_timeout(180)
            assert notify.get_attribute('aria-pressed') == 'false'
            assert '待确认' in notify.inner_text()
            accept_next_dialog(page)
            notify.click()
            page.wait_for_timeout(180)
            assert notify.get_attribute('aria-pressed') == 'true'

            # Stage 3 first click opens Foxmail but still stays incomplete.
            accept_next_dialog(page)
            initiate.click()
            page.wait_for_timeout(220)
            assert initiate.get_attribute('aria-pressed') == 'false'
            assert '待确认' in initiate.inner_text()
            assert paid.is_disabled()

            # User returns after actually sending the email and confirms it.
            accept_next_dialog(page)
            initiate.click()
            page.wait_for_timeout(180)
            assert initiate.get_attribute('aria-pressed') == 'true'
            assert paid.is_enabled()

            accept_next_dialog(page)
            paid.click()
            page.wait_for_timeout(240)
            assert paid.get_attribute('aria-pressed') == 'true'
            assert readonly(variable_input)
            with db() as conn:
                next_period = conn.execute(
                    'SELECT next_payment_period FROM services WHERE id=?', (two_month_sid,)
                ).fetchone()['next_payment_period']
                assert next_period == add_periods(period, 2), next_period

            # Undo final completion: payment cycle restores, stage 3 remains completed.
            accept_next_dialog(page)
            paid.click()
            page.wait_for_timeout(240)
            assert paid.get_attribute('aria-pressed') == 'false'
            assert initiate.get_attribute('aria-pressed') == 'true'
            assert not readonly(variable_input)
            with db() as conn:
                restored = conn.execute(
                    'SELECT next_payment_period FROM services WHERE id=?', (two_month_sid,)
                ).fetchone()['next_payment_period']
                assert restored == period, restored

            accept_next_dialog(page)
            initiate.click()
            page.wait_for_timeout(160)
            assert initiate.get_attribute('aria-pressed') == 'false'
            accept_next_dialog(page)
            notify.click()
            page.wait_for_timeout(160)
            assert notify.get_attribute('aria-pressed') == 'false'
            assert review.get_attribute('aria-pressed') == 'true'

            browser.close()
        print('v0.3.1 integrated four-stage browser acceptance passed (isolated test database)')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
