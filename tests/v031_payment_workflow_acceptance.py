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

from app import config  # noqa: E402
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


def stub_notice_transport(page):
    """Replace only the OS/browser clipboard transport used by stage 2.

    Other runtime scripts can refresh payment state asynchronously. Re-applying
    the stub immediately before each prepare click makes the state-machine test
    independent of Linux headless clipboard timing without touching production
    payment behavior.
    """
    page.evaluate('''() => {
        const actions = window.ChenPaymentWorkflowActionsV031;
        if (!actions?.prepareNotice) throw new Error('prepareNotice not loaded');
        actions.prepareNotice = async () => ({mode: 'clipboard', test_stub: true});
    }''')


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

            # Windows/Foxmail itself is outside Linux CI. Reproduce the exact
            # helper-v0.5 false negative seen in production: Simple MAPI returned
            # success (code 0), but its secondary visible-window-count probe did
            # not detect a new top-level compose window. The mature payment core
            # running inside the current app shell must accept this as a prepared/pending action.
            page.route('http://127.0.0.1:18763/compose', lambda route: route.fulfill(
                status=500,
                content_type='application/json',
                body='{"ok":false,"error":"Foxmail MAPI returned success but no compose window was detected","code":0}',
                headers={'Access-Control-Allow-Origin': 'http://127.0.0.1:8136'},
            ))
            page.route(f'**/customers/{cid}/payment-mail-compose-v031', lambda route: route.fulfill(
                status=200,
                content_type='application/json',
                body='{"ok":true,"recipient_b64":"dGVzdEBleGFtcGxlLmNvbQ==","subject_b64":"dGVzdA==","body_b64":"","attachment_filename_b64":"dGVzdC50eHQ=","attachment_content_base64":"MTM4MDAwMDAwMDF8MTA1"}',
            ))

            page.goto(f'http://127.0.0.1:8136/customers/{cid}', wait_until='networkidle')
            assert f'v{config.APP_VERSION}' in page.locator('.brand').inner_text()

            flow = page.locator('[data-v031-payment-flow]')
            flow.wait_for(state='visible')
            page.wait_for_timeout(1100)

            # Image clipboard writes are an external browser/OS integration, just
            # like Foxmail. Headless Chromium can intermittently stall on writing
            # image/png even with clipboard permission, which makes the workflow
            # state test flaky. Stub only that external transport here; the real
            # image-generation/clipboard code is still protected by contract tests.
            stub_notice_transport(page)

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

            assert fixed_row.get_attribute('data-confirmed') == '1'
            assert variable_row.get_attribute('data-confirmed') == '0'
            expect(page.locator('#pendingCount')).to_have_text('1')
            expect(review).to_have_attribute('aria-pressed', 'false')

            variable_state.click()
            expect(page.locator('#pendingCount')).to_have_text('0', timeout=3000)
            expect(review).to_have_attribute('aria-pressed', 'true', timeout=3000)
            expect(notify).to_be_enabled(timeout=3000)

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

            assert_no_dialog_while(page, lambda: fixed_input.fill('125'))
            fixed_input.press('Enter')
            expect(fixed_row).to_have_attribute('data-confirmed', '0', timeout=3000)
            expect(variable_row).to_have_attribute('data-confirmed', '1', timeout=3000)
            expect(fixed_state).to_have_text('○', timeout=3000)
            expect(review).to_have_attribute('aria-pressed', 'false', timeout=3000)
            fixed_state.click()
            expect(review).to_have_attribute('aria-pressed', 'true', timeout=3000)

            # Re-apply the test-only external transport stub immediately before
            # preparing notice. Also wait for the button itself to be actionable;
            # payment-state refreshes can briefly overlap this point in Chromium.
            stub_notice_transport(page)
            expect(notify).to_be_enabled(timeout=5000)
            assert_no_dialog_while(page, lambda: notify.click())
            expect(notify).to_contain_text('待确认', timeout=8000)
            expect(notify).to_be_enabled(timeout=5000)
            assert_no_dialog_while(page, lambda: notify.click())
            expect(notify).to_have_attribute('aria-pressed', 'true', timeout=5000)
            expect(initiate).to_be_enabled(timeout=5000)

            assert_no_dialog_while(page, lambda: initiate.click(), 700)
            expect(initiate).to_contain_text('待确认', timeout=5000)
            expect(initiate).to_be_enabled(timeout=5000)
            assert_no_dialog_while(page, lambda: initiate.click())
            expect(initiate).to_have_attribute('aria-pressed', 'true', timeout=5000)
            expect(paid).to_be_enabled(timeout=5000)

            assert_no_dialog_while(page, lambda: variable_input.fill('110'))
            variable_input.press('Enter')
            expect(variable_row).to_have_attribute('data-confirmed', '0', timeout=3000)
            expect(fixed_row).to_have_attribute('data-confirmed', '1', timeout=3000)
            expect(review).to_have_attribute('aria-pressed', 'false', timeout=3000)
            expect(notify).to_have_attribute('aria-pressed', 'false', timeout=3000)
            expect(initiate).to_have_attribute('aria-pressed', 'false', timeout=3000)

            variable_state.click()
            expect(review).to_have_attribute('aria-pressed', 'true', timeout=3000)
            stub_notice_transport(page)
            expect(notify).to_be_enabled(timeout=5000)
            assert_no_dialog_while(page, lambda: notify.click())
            expect(notify).to_contain_text('待确认', timeout=8000)
            expect(notify).to_be_enabled(timeout=5000)
            assert_no_dialog_while(page, lambda: notify.click())
            expect(notify).to_have_attribute('aria-pressed', 'true', timeout=5000)
            expect(initiate).to_be_enabled(timeout=5000)
            assert_no_dialog_while(page, lambda: initiate.click(), 700)
            expect(initiate).to_contain_text('待确认', timeout=5000)
            expect(initiate).to_be_enabled(timeout=5000)
            assert_no_dialog_while(page, lambda: initiate.click())
            expect(initiate).to_have_attribute('aria-pressed', 'true', timeout=5000)
            assert_no_dialog_while(page, lambda: paid.click())
            expect(paid).to_have_attribute('aria-pressed', 'true', timeout=5000)

            with db() as conn:
                next_period = conn.execute(
                    'SELECT next_payment_period FROM services WHERE id=?', (fixed_sid,)
                ).fetchone()['next_payment_period']
                assert next_period == add_periods(period, 2), next_period

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

        print('current app shell + mature payment MAPI/TXT/nonblocking browser acceptance passed')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
