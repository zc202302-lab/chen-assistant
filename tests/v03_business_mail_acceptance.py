from __future__ import annotations

from email import policy
from email.parser import BytesParser
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v03-business-mail-')
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
os.environ.pop('PAYMENT_EMAIL_TO', None)

from app.db import db, init_db, now_iso  # noqa: E402
from app.payment_v02 import current_period  # noqa: E402
from app.security import create_session  # noqa: E402
from app.v03_routes import _ensure_v03  # noqa: E402


def seed():
    init_db()
    now = now_iso()
    period = current_period()
    with db() as conn:
        _ensure_v03(conn)
        cid = int(conn.execute(
            'INSERT INTO customers (name,group_code,tax_id,payment_enabled,created_at,updated_at) VALUES(?,?,?,?,?,?)',
            ('中泰物流有限公司', 'C0000085396', '91370305MA3MJYD44N', 1, now, now),
        ).lastrowid)
        sid = int(conn.execute(
            '''INSERT INTO services
               (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
                payment_cycle,payment_interval_months,active_from_period,sort_order,source_row,
                payment_method,invoice_type,package_type,notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (cid, '成员', '后勤', '18353386915', '5338022507454', 165, 1,
             '1个月', 1, period, 10, 1, '微信', '普票', '套餐A', '测试'),
        ).lastrowid)
        conn.execute(
            'INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at) VALUES(?,?,?,?,?)',
            (sid, '1900-01', 'fixed', 165, now),
        )
        conn.execute(
            '''INSERT INTO customer_payment_runs
               (customer_id,period,reviewed_at,notified_at,paid_at,emailed_at,email_to,email_subject,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)''',
            (cid, period, now, now, now, '', '', '', now, now),
        )
    token, _, _ = create_session()
    return cid, token


def wait_http(url):
    for _ in range(100):
        try:
            if urllib.request.urlopen(url, timeout=1).status == 200:
                return
        except Exception:
            pass
        time.sleep(.2)
    raise RuntimeError('server start failed')


def main():
    cid, token = seed()
    assert TEST_DB.resolve() != (ROOT / 'data' / 'app.db').resolve()
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8132'],
        cwd=ROOT,
        env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8132/health')
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1500, 'height': 1000}, accept_downloads=True)
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8132'}])
            page = context.new_page()
            page.goto(f'http://127.0.0.1:8132/customers/{cid}', wait_until='networkidle')

            page.locator('[data-customer-tab="services"]').click()
            shell = page.locator('[data-business-filters].v03-readable-filters')
            shell.wait_for(state='visible')
            more = shell.locator('.v03-filter-more')
            assert more.count() == 1
            assert '更多筛选' in more.locator('summary').inner_text()
            assert more.locator('.filter-line').count() >= 3
            assert not more.get_attribute('open')
            assert shell.locator('.v03-filter-primary [data-business-filter="due"]').count() >= 1
            assert shell.locator('.v03-filter-selection-summary').inner_text() == '全部业务'
            row_height = page.locator('[data-business-row]').first.evaluate('el => el.getBoundingClientRect().height')
            assert row_height >= 44, row_height
            small_display = page.locator('[data-business-row] .business-attribute small').first.evaluate('el => getComputedStyle(el).display')
            assert small_display == 'none', small_display

            page.locator('[data-customer-tab="payment"]').click()
            template_button = page.locator('[data-v03-mail-template]')
            template_button.wait_for(state='visible')
            template_button.click()
            dialog = page.locator('.v03-mail-template-dialog')
            dialog.wait_for(state='visible')
            assert '按客户长期保存' in dialog.inner_text()
            assert dialog.locator('[data-v03-foxmail-bridge-state]').count() == 1
            helper_link = dialog.locator('.v03-foxmail-helper-download')
            assert helper_link.get_attribute('href') == '/static/chen_foxmail_helper.ps1'
            dialog.locator('[data-v03-mail-recipient]').fill('colleague@example.com')
            dialog.locator('[data-v03-mail-subject]').fill('中泰物流长期缴费主题')
            dialog.locator('[data-v03-mail-body]').fill('这是长期保存的正文，也允许留空。')
            dialog.locator('button[type="submit"]').click()
            dialog.wait_for(state='hidden')

            draft = page.locator('[data-v03-foxmail-draft]')
            draft.wait_for(state='visible')
            page.wait_for_function("!document.querySelector('[data-v03-foxmail-draft]').disabled")
            # CI has no Windows bridge, so the production UI must gracefully fall back
            # to an .eml browser download.
            with page.expect_download() as info:
                draft.click()
            download = info.value
            eml_path = Path(download.path())
            raw = eml_path.read_bytes()
            msg = BytesParser(policy=policy.default).parsebytes(raw)
            assert msg['X-Unsent'] == '1'
            assert msg['To'] == 'colleague@example.com'
            assert msg['Subject'] == '中泰物流长期缴费主题'
            body = msg.get_body(preferencelist=('plain',)).get_content()
            assert '长期保存的正文' in body
            attachments = list(msg.iter_attachments())
            assert len(attachments) == 1
            assert attachments[0].get_filename().endswith('缴费.txt')
            text = attachments[0].get_payload(decode=True).decode('utf-8')
            assert '18353386915|165' in text

            # Reopen template: client values and the global recipient survive.
            template_button.click()
            dialog.wait_for(state='visible')
            assert dialog.locator('[data-v03-mail-recipient]').input_value() == 'colleague@example.com'
            assert dialog.locator('[data-v03-mail-subject]').input_value() == '中泰物流长期缴费主题'
            assert '长期保存的正文' in dialog.locator('[data-v03-mail-body]').input_value()
            browser.close()

        print('v0.3 business/mail browser acceptance passed (isolated test database)')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
