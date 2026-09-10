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
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v033-payment-browser-')
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
            ('v033流程验收客户', 'V033', 1, now, now),
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


def assert_no_dialog_while(page, action, wait_ms=450):
    seen = []

    def capture(dialog):
        seen.append(dialog.message)
        dialog.dismiss()

    page.on('dialog', capture)
    try:
        action()
        page.wait_for_timeout(wait_ms)
    finally:
        page.remove_listener('dialog', capture)
    assert not seen, f'此操作必须无弹窗，实际出现: {seen}'


def main():
    cid, ids, token = seed()
    assert TEST_DB.resolve() != (ROOT / 'data' / 'app.db').resolve()
    variable_sid, fixed_sid = ids
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
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1500, 'height': 1000}, accept_downloads=True)
            context.grant_permissions(['clipboard-read', 'clipboard-write'], origin='http://127.0.0.1:8136')
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8136'}])
            page = context.new_page()

            # Windows/Foxmail itself is outside Linux CI. Stub its verified native
            # compose response; all payment state endpoints remain real.
            page.route('http://127.0.0.1:18763/compose', lambda route: route.fulfill(
                status=200,
                content_type='application/json',
                body='{"ok":true,"verified":true,"mode":"foxmail-direct-mapi","state":"new-window-detected"}',
                headers={'Access-Control-Allow-Origin': 'http://127.0.0.1:8136'},
            ))
            page.route(f'**/customers/{cid}/payment-mail-compose-v031', lambda route: route.fulfill(
                status=200,
                content_type='application/json',
                body='{"ok":true,"recipient_b64":"dGVzdEBleGFtcGxlLmNvbQ==","subject_b64":"dGVzdA==","body_b64":"","attachment_filename_b64":"dGVzdC50eHQ=","attachment_content_base64":"MTM4MDAwMDAwMDF8MTA1"}',
            ))

            page.goto(f'http://127.0.0.1:8136/customers/{cid}', wait_until='networkidle')
            assert 'v0.3.3' in page.locator('.brand').inner_text()

            flow = page.locator('[data-v031-payment-flow]')
            flow.wait_for(state='visible')
            page.wait_for_timeout(1100)
            review = flow.locator('[data-v031-flow-action="review"]')
            notify = flow.locator('[data-v031-flow-action="notify"]')
            initiate = flow.locator('[data-v031-flow-action="initiate"]')
            paid = flow.locator('[data-v031-flow-action="paid"]')
            variable_row = page.locator(f'[data-payment-row][data-service-id="{variable_sid}"]')
            fixed_row = page.locator(f'[data-payment-row][data-service-id="{fixed_sid}"]')
            variable_state = variable_row.locator('[data-row-state]')
            fixed_state = fixed_row.locator('[data-row-state]')
            variable_input = variable_row.locator('.quick-amount')
            fixed_input = fixed_row.locator('.quick-amount')
            txt_button = page.locator('#paymentTxtButton')

            # Fixed row auto-confirms, variable row starts pending.
            assert fixed_row.get_attribute('data-confirmed') == '1'
            assert variable_row.get_attribute('data-confirmed') == '0'
            expect(page.locator('#pendingCount')).to_have_text('1')
            expect(review).to_have_attribute('aria-pressed', 'false')

            # Requirement 1: once every row is confirmed, stage 1 activates by itself.
            variable_state.click()
            expect(page.locator('#pendingCount')).to_have_text('0', timeout=3000)
            expect(review).to_have_attribute('aria-pressed', 'true', timeout=3000)
            expect(notify).to_be_enabled(timeout=3000)

            # The visible TXT action must create a real browser download, not merely
            # navigate to/render text. Verify the downloaded file name and payload.
            with page.expect_download(timeout=3000) as download_info:
                assert_no_dialog_while(page, lambda: txt_button.click(), 120)
            download = download_info.value
            assert download.suggested_filename.lower().endswith('.txt'), download.suggested_filename
            downloaded_path = download.path()
            assert downloaded_path is not None
            assert Path(downloaded_path).read_text(encoding='utf-8').splitlines() == [
                '13800000001|100',
                '13800000002|120',
            ]

            # A changed amount invalidates only that row; the untouched row keeps
            # its confirmation and the workflow silently falls back to stage 1.
            assert_no_dialog_while(page, lambda: fixed_input.fill('125'))
            fixed_input.press('Enter')
            expect(fixed_row).to_have_attribute('data-confirmed', '0', timeout=3000)
            expect(variable_row).to_have_attribute('data-confirmed', '1', timeout=3000)
            expect(fixed_state).to_have_text('○', timeout=3000)
            expect(review).to_have_attribute('aria-pressed', 'false', timeout=3000)
            fixed_state.click()
            expect(review).to_have_attribute('aria-pressed', 'true', timeout=3000)

            # Requirement 3: both clicks of notify are non-blocking/no-dialog.
            assert_no_dialog_while(page, lambda: notify.click())
            expect(notify).to_contain_text('待确认', timeout=3000)
            assert_no_dialog_while(page, lambda: notify.click())
            expect(notify).to_have_attribute('aria-pressed', 'true', timeout=3000)
            expect(initiate).to_be_enabled(timeout=3000)

            # Requirement 3 again for initiate; bridge result says a native MAPI
            # compose window was verified, and no confirmation alert is allowed.
            assert_no_dialog_while(page, lambda: initiate.click(), 700)
            expect(initiate).to_contain_text('待确认', timeout=3000)
            assert_no_dialog_while(page, lambda: initiate.click())
            expect(initiate).to_have_attribute('aria-pressed', 'true', timeout=3000)
            expect(paid).to_be_enabled(timeout=3000)

            # Requirement 2 at a late stage: amount edit is silent and returns to
            # review; only the edited variable row loses its confirmation.
            assert_no_dialog_while(page, lambda: variable_input.fill('110'))
            variable_input.press('Enter')
            expect(variable_row).to_have_attribute('data-confirmed', '0', timeout=3000)
            expect(fixed_row).to_have_attribute('data-confirmed', '1', timeout=3000)
            expect(review).to_have_attribute('aria-pressed', 'false', timeout=3000)
            expect(notify).to_have_attribute('aria-pressed', 'false', timeout=3000)
            expect(initiate).to_have_attribute('aria-pressed', 'false', timeout=3000)

            # Reconfirm and run through all four stages once more. Every stage is
            # non-blocking: there must be no confirm/alert dialog, including paid.
            variable_state.click()
            expect(review).to_have_attribute('aria-pressed', 'true', timeout=3000)
            assert_no_dialog_while(page, lambda: notify.click())
            assert_no_dialog_while(page, lambda: notify.click())
            expect(notify).to_have_attribute('aria-pressed', 'true', timeout=3000)
            assert_no_dialog_while(page, lambda: initiate.click(), 700)
            assert_no_dialog_while(page, lambda: initiate.click())
            expect(initiate).to_have_attribute('aria-pressed', 'true', timeout=3000)
            assert_no_dialog_while(page, lambda: paid.click())
            expect(paid).to_have_attribute('aria-pressed', 'true', timeout=3000)

            with db() as conn:
                next_period = conn.execute(
                    'SELECT next_payment_period FROM services WHERE id=?', (fixed_sid,)
                ).fetchone()['next_payment_period']
                assert next_period == add_periods(period, 2), next_period

            # Even after final completion an amount remains editable. Changing it
            # restores the pre-payment schedule and rolls all later stages back.
            assert_no_dialog_while(page, lambda: variable_input.fill('115'))
            variable_input.press('Enter')
            expect(variable_row).to_have_attribute('data-confirmed', '0', timeout=3000)
            expect(fixed_row).to_have_attribute('data-confirmed', '1', timeout=3000)
            expect(review).to_have_attribute('aria-pressed', 'false', timeout=3000)
            expect(notify).to_have_attribute('aria-pressed', 'false', timeout=3000)
            expect(initiate).to_have_attribute('aria-pressed', 'false', timeout=3000)
            expect(paid).to_have_attribute('aria-pressed', 'false', timeout=3000)
            with db() as conn:
                restored = conn.execute(
                    'SELECT next_payment_period FROM services WHERE id=?', (fixed_sid,)
                ).fetchone()['next_payment_period']
                assert restored == period, restored

            browser.close()

        print('v0.3.3 real TXT download + fully nonblocking four-stage browser acceptance passed')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
