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
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8136'}])
            page = context.new_page()
            page.goto(f'http://127.0.0.1:8136/customers/{cid}', wait_until='networkidle')

            assert 'v0.3.1' in page.locator('.brand').inner_text()
            flow = page.locator('[data-v031-payment-flow]')
            flow.wait_for(state='visible')
            labels = [x.strip() for x in flow.locator('[data-v031-flow-action]').all_inner_texts()]
            assert labels == ['1 金额核对', '2 已通知客户', '3 发起缴费', '4 完成缴费'], labels
            image_button = page.locator('[data-v031-payment-image]')
            assert image_button.count() == 1
            assert page.locator('[data-v03-mail-template]').count() == 1
            assert page.locator('[data-v03-foxmail-draft]').count() == 1

            review = flow.locator('[data-v031-flow-action="review"]')
            notify = flow.locator('[data-v031-flow-action="notify"]')
            initiate = flow.locator('[data-v031-flow-action="initiate"]')
            paid = flow.locator('[data-v031-flow-action="paid"]')

            # One variable row starts unconfirmed. This is the production regression:
            # after the final amount is entered, “金额核对” must become clickable immediately.
            assert page.locator('#pendingCount').inner_text().strip() == '1'
            assert review.is_disabled()
            variable_input = page.locator(f'[data-payment-row][data-service-id="{variable_sid}"] .quick-amount')
            variable_input.fill('105')
            variable_input.press('Enter')
            page.wait_for_timeout(450)
            assert page.locator('#pendingCount').inner_text().strip() == '0'
            assert review.is_enabled()
            assert notify.is_disabled()
            assert initiate.is_disabled()
            assert paid.is_disabled()

            review.click()
            page.wait_for_timeout(150)
            assert review.get_attribute('aria-pressed') == 'true'
            assert notify.is_enabled()
            assert image_button.is_enabled()

            accept_next_dialog(page)
            notify.click()
            page.wait_for_timeout(150)
            assert notify.get_attribute('aria-pressed') == 'true'
            assert initiate.is_enabled()
            assert not readonly(variable_input)

            # Customer disputes the amount after receiving the WeChat image.
            # Saving a changed amount must automatically invalidate review + notification.
            variable_input.fill('110')
            variable_input.press('Enter')
            page.wait_for_timeout(650)
            assert review.get_attribute('aria-pressed') == 'false'
            assert notify.get_attribute('aria-pressed') == 'false'
            assert initiate.get_attribute('aria-pressed') == 'false'
            assert review.is_enabled()
            assert notify.is_disabled()

            # Reconfirm the corrected amount and notify again.
            review.click()
            page.wait_for_timeout(140)
            accept_next_dialog(page)
            notify.click()
            page.wait_for_timeout(140)
            assert notify.get_attribute('aria-pressed') == 'true'

            accept_next_dialog(page)
            initiate.click()
            page.wait_for_timeout(150)
            assert initiate.get_attribute('aria-pressed') == 'true'
            assert paid.is_enabled()

            accept_next_dialog(page)
            paid.click()
            page.wait_for_timeout(220)
            assert paid.get_attribute('aria-pressed') == 'true'
            assert readonly(variable_input)
            with db() as conn:
                next_period = conn.execute(
                    'SELECT next_payment_period FROM services WHERE id=?', (two_month_sid,)
                ).fetchone()['next_payment_period']
                assert next_period == add_periods(period, 2), next_period

            # Undo final completion: actual payment cycle is restored, stage 3 remains completed.
            accept_next_dialog(page)
            paid.click()
            page.wait_for_timeout(220)
            assert paid.get_attribute('aria-pressed') == 'false'
            assert initiate.get_attribute('aria-pressed') == 'true'
            assert not readonly(variable_input)
            with db() as conn:
                restored = conn.execute(
                    'SELECT next_payment_period FROM services WHERE id=?', (two_month_sid,)
                ).fetchone()['next_payment_period']
                assert restored == period, restored

            initiate.click()
            page.wait_for_timeout(140)
            assert initiate.get_attribute('aria-pressed') == 'false'
            notify.click()
            page.wait_for_timeout(140)
            assert notify.get_attribute('aria-pressed') == 'false'
            assert review.get_attribute('aria-pressed') == 'true'

            browser.close()
        print('v0.3.1 four-stage browser acceptance passed (isolated test database)')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
