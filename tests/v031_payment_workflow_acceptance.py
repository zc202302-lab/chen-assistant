from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
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
        conn.execute('''CREATE TABLE IF NOT EXISTS customer_mail_templates_v03 (
            customer_id INTEGER PRIMARY KEY REFERENCES customers(id) ON DELETE CASCADE,
            recipient TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '', attachment_filename TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        )''')
        conn.execute(
            '''INSERT INTO customer_mail_templates_v03
               (customer_id,recipient,subject,body,attachment_filename,updated_at)
               VALUES(?,?,?,?,?,?)''',
            (cid, 'test@example.com', '测试缴费邮件', '请处理附件缴费明细。', '验收客户缴费清单.txt', now),
        )
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
        seen.append(dialog.message); dialog.dismiss()
    page.on('dialog', capture)
    try:
        action(); page.wait_for_timeout(wait_ms)
    finally:
        page.remove_listener('dialog', capture)
    assert not seen, f'此操作必须无弹窗，实际出现: {seen}'


def stub_notice_transport(page):
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
        cwd=ROOT, env=os.environ.copy(),
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

            # CI has no real Windows desktop/Foxmail process. Stub the current v0.9
            # helper contract faithfully: Foxmail draft verified, exact TXT prepared,
            # Explorer selection dispatched, but attachment/send remain manual.
            page.route('http://127.0.0.1:18763/health', lambda route: route.fulfill(
                status=200, content_type='application/json',
                body='{"ok":true,"version":"0.9","launch_mode":"foxmail-exe-mailto-file-ready","attachment_mode":"manual-file-selection","auto_send":false,"mapi_required":false}',
                headers={'Access-Control-Allow-Origin': 'http://127.0.0.1:8136'},
            ))
            page.route('http://127.0.0.1:18763/compose', lambda route: route.fulfill(
                status=200, content_type='application/json',
                body='{"ok":true,"mode":"foxmail-exe-mailto-file-ready","verified":true,"launch_verified":true,"attachment_file_verified":true,"explorer_dispatched":true,"attachment_filename_exact":true,"state":"draft-open-file-selected"}',
                headers={'Access-Control-Allow-Origin': 'http://127.0.0.1:8136'},
            ))
            page.route(f'**/customers/{cid}/payment-mail-compose-v031', lambda route: route.fulfill(
                status=200, content_type='application/json',
                body='{"ok":true,"recipient_b64":"dGVzdEBleGFtcGxlLmNvbQ==","subject_b64":"dGVzdA==","body_b64":"","attachment_filename_b64":"dGVzdC50eHQ=","attachment_content_base64":"MTM4MDAwMDAwMDF8MTA1"}',
            ))

            page.goto(f'http://127.0.0.1:8136/customers/{cid}', wait_until='networkidle')
            assert f'v{config.APP_VERSION}' in page.locator('.brand').inner_text()
            flow = page.locator('[data-v031-payment-flow]'); flow.wait_for(state='visible'); page.wait_for_timeout(1100)
            stub_notice_transport(page)

            review = flow.locator('[data-v031-flow-action="review"]')
            notify = flow.locator('[data-v031-flow-action="notify"]')
            initiate = flow.locator('[data-v031-flow-action="initiate"]')
            paid = flow.locator('[data-v031-flow-action="paid"]')
            variable_row = page.locator(f'[data-payment-row][data-service-id="{variable_sid}"]')
            fixed_row = page.locator(f'[data-payment-row][data-service-id="{fixed_sid}"]')
            variable_state = variable_row.locator('[data-row-state]')
            variable_input = variable_row.locator('.quick-amount')
            fixed_input = fixed_row.locator('.quick-amount')
            excel_button = page.locator('#paymentExcelButton')
            txt_button = page.locator('#paymentTxtButton')

            assert fixed_row.get_attribute('data-confirmed') == '1'
            assert variable_row.get_attribute('data-confirmed') == '0'
            expect(page.locator('#pendingCount')).to_have_text('1')
            variable_state.click()
            expect(page.locator('#pendingCount')).to_have_text('0', timeout=3000)
            expect(review).to_have_attribute('aria-pressed', 'true', timeout=3000)
            # Export availability is updated asynchronously with the row review.
            # Wait for both controls before clicking on slower self-hosted runners.
            expect(excel_button).to_have_attribute('aria-disabled', 'false', timeout=5000)
            expect(txt_button).to_have_attribute('aria-disabled', 'false', timeout=5000)

            with page.expect_download(timeout=3000) as excel_download_info:
                assert_no_dialog_while(page, lambda: excel_button.click(), 120)
            excel_download = excel_download_info.value
            assert excel_download.suggested_filename == '验收客户缴费清单.xlsx', excel_download.suggested_filename
            excel_path = excel_download.path(); assert excel_path is not None
            with zipfile.ZipFile(excel_path) as archive:
                shared = archive.read('xl/sharedStrings.xml').decode('utf-8')
                sheet = archive.read('xl/worksheets/sheet1.xml').decode('utf-8')
            for value in ('类型', '姓名/属性', '号码', '账号', '金额', '成员1', '成员2', '13800000001', '13800000002', 'A001', 'A002'):
                assert value in shared, value
            assert '<v>100</v>' in sheet and '<v>120</v>' in sheet
            assert page.locator('.payment-export-actions a').all_inner_texts() == ['生成缴费EXCEL', '生成缴费TXT']

            with page.expect_download(timeout=3000) as download_info:
                assert_no_dialog_while(page, lambda: txt_button.click(), 120)
            download = download_info.value
            assert download.suggested_filename == '验收客户缴费清单.txt', download.suggested_filename
            downloaded_path = download.path(); assert downloaded_path is not None
            assert Path(downloaded_path).read_text(encoding='utf-8').splitlines() == ['13800000001|100', '13800000002|120']

            assert_no_dialog_while(page, lambda: fixed_input.fill('125')); fixed_input.press('Enter')
            expect(fixed_row).to_have_attribute('data-confirmed', '1', timeout=3000)
            expect(variable_row).to_have_attribute('data-confirmed', '1', timeout=3000)
            expect(review).to_have_attribute('aria-pressed', 'true', timeout=3000)

            stub_notice_transport(page); expect(notify).to_be_enabled(timeout=5000)
            assert_no_dialog_while(page, lambda: notify.click()); expect(notify).to_contain_text('待确认', timeout=8000)
            assert_no_dialog_while(page, lambda: notify.click()); expect(notify).to_have_attribute('aria-pressed', 'true', timeout=5000)
            expect(initiate).to_be_enabled(timeout=5000)
            assert_no_dialog_while(page, lambda: initiate.click(), 700)
            expect(initiate).to_have_attribute('aria-pressed', 'false', timeout=3000)
            expect(initiate).to_contain_text('待确认', timeout=3000)
            assert_no_dialog_while(page, lambda: initiate.click()); expect(initiate).to_have_attribute('aria-pressed', 'true', timeout=5000)
            expect(paid).to_be_enabled(timeout=5000)

            assert_no_dialog_while(page, lambda: variable_input.fill('110')); variable_input.press('Enter')
            expect(variable_row).to_have_attribute('data-confirmed', '1', timeout=3000)
            expect(fixed_row).to_have_attribute('data-confirmed', '1', timeout=3000)
            expect(review).to_have_attribute('aria-pressed', 'true', timeout=3000)
            expect(notify).to_have_attribute('aria-pressed', 'false', timeout=3000)
            expect(initiate).to_have_attribute('aria-pressed', 'false', timeout=3000)

            stub_notice_transport(page); expect(notify).to_be_enabled(timeout=5000)
            assert_no_dialog_while(page, lambda: notify.click()); expect(notify).to_contain_text('待确认', timeout=8000)
            assert_no_dialog_while(page, lambda: notify.click()); expect(notify).to_have_attribute('aria-pressed', 'true', timeout=5000)
            expect(initiate).to_be_enabled(timeout=5000)
            assert_no_dialog_while(page, lambda: initiate.click(), 700)
            expect(initiate).to_have_attribute('aria-pressed', 'false', timeout=3000)
            expect(initiate).to_contain_text('待确认', timeout=3000)
            assert_no_dialog_while(page, lambda: initiate.click()); expect(initiate).to_have_attribute('aria-pressed', 'true', timeout=5000)
            assert_no_dialog_while(page, lambda: paid.click()); expect(paid).to_have_attribute('aria-pressed', 'true', timeout=5000)

            with db() as conn:
                next_period = conn.execute('SELECT next_payment_period FROM services WHERE id=?', (fixed_sid,)).fetchone()['next_payment_period']
                assert next_period == add_periods(period, 2), next_period

            assert_no_dialog_while(page, lambda: variable_input.fill('115')); variable_input.press('Enter')
            expect(variable_row).to_have_attribute('data-confirmed', '1', timeout=3000)
            expect(fixed_row).to_have_attribute('data-confirmed', '1', timeout=3000)
            expect(review).to_have_attribute('aria-pressed', 'true', timeout=3000)
            expect(notify).to_have_attribute('aria-pressed', 'false', timeout=3000)
            expect(initiate).to_have_attribute('aria-pressed', 'false', timeout=3000)
            expect(paid).to_have_attribute('aria-pressed', 'false', timeout=3000)
            with db() as conn:
                restored = conn.execute('SELECT next_payment_period FROM services WHERE id=?', (fixed_sid,)).fetchone()['next_payment_period']
                assert restored == period, restored
            browser.close()

        print('current app shell + mature payment template-TXT/manual-mail-preparation/nonblocking acceptance passed')
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill()


if __name__ == '__main__':
    main()
