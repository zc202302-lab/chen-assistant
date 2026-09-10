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


def assert_no_dialog_while(page, action):
    seen = []

    def capture(dialog):
        seen.append(dialog.message)
        dialog.dismiss()

    page.on('dialog', capture)
    try:
        action()
        page.wait_for_timeout(350)
    finally:
        page.remove_listener('dialog', capture)
    assert not seen, f'amount editing must be silent, got dialog: {seen}'


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
        from playwright.sync_api import expect, sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(base_url='http://127.0.0.1:8136')
            context.add_cookies([{
                'name': 'session',
                'value': token,
                'url': 'http://127.0.0.1:8136',
            }])
            page = context.new_page()
            page.goto(f'/customers/{cid}')
            page.wait_for_load_state('networkidle')

            assert 'v0.3.2' in page.locator('.brand').inner_text()
            flow = page.locator('[data-v031-payment-flow]')
            flow.wait_for(state='visible')
            page.wait_for_timeout(1100)
            labels = [x.strip() for x in flow.locator('[data-v031-flow-action]').all_inner_texts()]
            assert labels == ['1 金额核对', '2 通知客户', '3 发起缴费', '4 完成缴费'], labels

            image_button = page.locator('[data-v031-payment-image]')
            foxmail_button = page.locator('[data-v03-foxmail-draft]')
            assert image_button.count() == 1 and image_button.is_hidden()
            assert foxmail_button.count() == 1 and foxmail_button.is_hidden()
            assert page.locator('[data-v03-mail-template]').count() == 1

            review = flow.locator('[data-v031-flow-action="review"]')
            notify = flow.locator('[data-v031-flow-action="notify"]')
            initiate = flow.locator('[data-v031-flow-action="initiate"]')
            paid = flow.locator('[data-v031-flow-action="paid"]')
            variable_row = page.locator(f'[data-payment-row][data-service-id="{variable_sid}"]')
            fixed_row = page.locator(f'[data-payment-row][data-service-id="{two_month_sid}"]')
            variable_state = variable_row.locator('[data-row-state]')
            fixed_state = fixed_row.locator('[data-row-state]')
            variable_input = variable_row.locator('.quick-amount')
            fixed_input = fixed_row.locator('.quick-amount')

            # Fixed rows start automatic; one variable row starts pending.
            assert fixed_row.get_attribute('data-confirmed') == '1'
            assert fixed_state.inner_text().strip() == '✓'
            assert fixed_state.is_disabled()
            assert variable_row.get_attribute('data-confirmed') == '0'
            assert page.locator('#pendingCount').inner_text().strip() == '1'
            assert review.get_attribute('aria-pressed') == 'false'

            # Confirming the last pending row automatically completes stage 1.
            variable_state.click()
            expect(page.locator('#pendingCount')).to_have_text('0', timeout=3000)
            expect(review).to_have_attribute('aria-pressed', 'true', timeout=3000)
            expect(notify).to_be_enabled(timeout=3000)

            # Editing a fixed amount invalidates only that row, despite fixed rows
            # normally being automatic confirmations.
            fixed_input.fill('125')
            fixed_input.press('Enter')
            expect(fixed_row).to_have_attribute('data-confirmed', '0', timeout=3000)
            expect(variable_row).to_have_attribute('data-confirmed', '1', timeout=3000)
            expect(fixed_state).to_have_text('○', timeout=3000)
            expect(fixed_state).to_be_enabled(timeout=3000)
            expect(page.locator('#pendingCount')).to_have_text('1', timeout=3000)
            expect(review).to_have_attribute('aria-pressed', 'false', timeout=3000)
            fixed_state.click()
            expect(fixed_row).to_have_attribute('data-confirmed', '1', timeout=3000)
            expect(review).to_have_attribute('aria-pressed', 'true', timeout=3000)
            expect(notify).to_be_enabled(timeout=3000)

            # Stage 2: first click prepares image; second confirms the real WeChat send.
            accept_next_dialog(page)
            notify.click()
            expect(notify).to_have_attribute('aria-pressed', 'false', timeout=3000)
            expect(notify).to_contain_text('待确认', timeout=3000)
            assert initiate.is_disabled()
            accept_next_dialog(page)
            notify.click()
            expect(notify).to_have_attribute('aria-pressed', 'true', timeout=3000)
            expect(initiate).to_be_enabled(timeout=3000)

            # Stage 3: first opens Foxmail; second confirms the real email send.
            accept_next_dialog(page)
            initiate.click()
            expect(initiate).to_have_attribute('aria-pressed', 'false', timeout=3000)
            expect(initiate).to_contain_text('待确认', timeout=3000)
            accept_next_dialog(page)
            initiate.click()
            expect(initiate).to_have_attribute('aria-pressed', 'true', timeout=3000)
            expect(paid).to_be_enabled(timeout=3000)

            # Editing after initiation is silent. Only the changed row becomes
            # pending; every untouched row keeps its confirmation.
            assert_no_dialog_while(page, lambda: variable_input.fill('110'))
            variable_input.press('Enter')
            expect(variable_row).to_have_attribute('data-confirmed', '0', timeout=3000)
            expect(fixed_row).to_have_attribute('data-confirmed', '1', timeout=3000)
            expect(review).to_have_attribute('aria-pressed', 'false', timeout=3000)
            expect(notify).to_have_attribute('aria-pressed', 'false', timeout=3000)
            expect(initiate).to_have_attribute('aria-pressed', 'false', timeout=3000)
            expect(page.locator('#pendingCount')).to_have_text('1', timeout=3000)

            # Reconfirm just that row; stage 1 completes automatically again.
            variable_state.click()
            expect(variable_row).to_have_attribute('data-confirmed', '1', timeout=3000)
            expect(fixed_row).to_have_attribute('data-confirmed', '1', timeout=3000)
            expect(review).to_have_attribute('aria-pressed', 'true', timeout=3000)
            expect(notify).to_be_enabled(timeout=3000)

            # Re-do stages 2 and 3, then complete payment. Wait for each external
            # preparation to reach its explicit awaiting-confirm state before
            # registering the confirmation dialog handler; this mirrors real use
            # and avoids two one-shot handlers racing the same preparation alert.
            accept_next_dialog(page)
            notify.click()
            expect(notify).to_contain_text('待确认', timeout=3000)
            accept_next_dialog(page)
            notify.click()
            expect(notify).to_have_attribute('aria-pressed', 'true', timeout=3000)
            accept_next_dialog(page)
            initiate.click()
            expect(initiate).to_contain_text('待确认', timeout=3000)
            accept_next_dialog(page)
            initiate.click()
            expect(initiate).to_have_attribute('aria-pressed', 'true', timeout=3000)
            accept_next_dialog(page)
            paid.click()
            expect(paid).to_have_attribute('aria-pressed', 'true', timeout=3000)

            # Amounts remain editable even after stage 4. The two-month schedule
            # has advanced at payment completion.
            expect(variable_input).not_to_have_attribute('readonly', '', timeout=3000)
            assert not readonly(variable_input)
            with db() as conn:
                next_period = conn.execute(
                    'SELECT next_payment_period FROM services WHERE id=?', (two_month_sid,)
                ).fetchone()['next_payment_period']
            assert next_period == add_periods(period, 2), (next_period, add_periods(period, 2))

            # Editing after completion silently reopens stage 4 and rolls the
            # schedule back before invalidating downstream workflow stages.
            assert_no_dialog_while(page, lambda: fixed_input.fill('130'))
            fixed_input.press('Enter')
            expect(fixed_row).to_have_attribute('data-confirmed', '0', timeout=3000)
            expect(variable_row).to_have_attribute('data-confirmed', '1', timeout=3000)
            expect(paid).to_have_attribute('aria-pressed', 'false', timeout=3000)
            expect(review).to_have_attribute('aria-pressed', 'false', timeout=3000)
            expect(notify).to_have_attribute('aria-pressed', 'false', timeout=3000)
            expect(initiate).to_have_attribute('aria-pressed', 'false', timeout=3000)
            with db() as conn:
                rolled_back_period = conn.execute(
                    'SELECT next_payment_period FROM services WHERE id=?', (two_month_sid,)
                ).fetchone()['next_payment_period']
            assert rolled_back_period == period, (rolled_back_period, period)

            browser.close()
        print('v0.3.2 automatic review + row-preserving rollback browser acceptance passed')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


if __name__ == '__main__':
    main()
