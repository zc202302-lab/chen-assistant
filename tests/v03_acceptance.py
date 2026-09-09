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
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v03-acceptance-')
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
for key in (
    'SMTP_HOST', 'SMTP_PORT', 'SMTP_USERNAME', 'SMTP_PASSWORD', 'SMTP_FROM',
    'PAYMENT_EMAIL_TO', 'PAYMENT_EMAIL_SUBJECT_TEMPLATE',
):
    os.environ.pop(key, None)

from app.db import db, init_db, now_iso  # noqa: E402
from app.payment_v02 import add_periods, current_period  # noqa: E402
from app.security import create_session  # noqa: E402


def seed():
    init_db()
    now = now_iso()
    period = current_period()
    with db() as conn:
        cid = int(conn.execute(
            'INSERT INTO customers (name,group_code,tax_id,payment_enabled,created_at,updated_at) VALUES(?,?,?,?,?,?)',
            ('中泰物流有限公司', 'C0000085396', '91370305MA3MJYD44N', 1, now, now),
        ).lastrowid)
        specs = [
            ('成员', '甲', '18353386915', '5338022507454', 1, '', '微信', 165),
            ('成员', '乙', '18353386686', '5338011455645', 1, '', '微信', 205),
            ('专线', '丙', '13589500198', '5338020648139', 2, period, '转账', 115),
        ]
        ids = []
        for idx, (typ, holder, number, account, months, nxt, method, amount) in enumerate(specs, 1):
            sid = int(conn.execute(
                '''INSERT INTO services
                   (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
                    payment_cycle,payment_interval_months,next_payment_period,active_from_period,
                    sort_order,source_row,payment_method,invoice_type,package_type,notes)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (cid, typ, holder, number, account, amount, 1,
                 f'{months}个月', months, nxt, period, idx * 10, idx,
                 method, '普票', f'套餐{idx}', f'备注{idx}'),
            ).lastrowid)
            ids.append(sid)
            conn.execute(
                'INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at) VALUES(?,?,?,?,?)',
                (sid, '1900-01', 'fixed', amount, now),
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


def main():
    cid, ids, token = seed()
    assert TEST_DB.resolve() != (ROOT / 'data' / 'app.db').resolve()
    monthly1, monthly2, every_two = ids
    period = current_period()
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8130'],
        cwd=ROOT,
        env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8130/health')
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1500, 'height': 1000})
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8130'}])
            page = context.new_page()

            # Home search is a primary mobile-friendly entry point.
            page.goto('http://127.0.0.1:8130/', wait_until='networkidle')
            search = page.locator('[data-v03-search-input]')
            search.wait_for(state='visible')
            search.fill('18353386915')
            page.locator('[data-v03-search-result]').first.wait_for(state='visible')
            assert '中泰物流有限公司' in page.locator('[data-v03-search-result]').first.inner_text()
            page.set_viewport_size({'width': 390, 'height': 844})
            box_width = page.locator('.v03-home-search-box').evaluate('el => el.getBoundingClientRect().width')
            assert box_width <= 390, box_width

            page.set_viewport_size({'width': 1500, 'height': 1000})
            page.goto(f'http://127.0.0.1:8130/customers/{cid}', wait_until='networkidle')

            # Workflow steps live in the title area; the old dedicated row is gone.
            assert page.locator('.payment-run-card').count() == 0
            flow = page.locator('[data-v03-payment-flow]')
            flow.wait_for(state='visible')
            assert flow.locator('[data-v03-flow-action]').count() == 3

            # Payment list no longer has a visible drag handle and auto-fits the page.
            payment_list = page.locator('#paymentSortable')
            payment_list.wait_for(state='visible')
            drag_display = page.locator('[data-payment-row]').first.locator(':scope > .drag-handle').evaluate('el => getComputedStyle(el).display')
            assert drag_display == 'none', drag_display
            dims = payment_list.evaluate('el => ({client:el.clientWidth, scroll:el.scrollWidth})')
            assert dims['scroll'] <= dims['client'] + 2, dims

            # Payment display settings use the same numeric-order model as business.
            page.locator('[data-payment-columns-settings]').click()
            payment_dialog = page.locator('#paymentColumnsDialog')
            payment_dialog.wait_for(state='visible')
            order_rows = payment_dialog.locator('[data-v03-payment-column-key]')
            assert order_rows.count() >= 6
            assert payment_dialog.locator('[data-v03-payment-column-key="payment_amount"] [data-v03-payment-order]').count() == 1
            assert payment_dialog.locator('select').count() == 0
            payment_dialog.locator('[data-payment-columns-close]').first.click()

            # Centered, compact payment data and amount box.
            cell_align = page.locator('[data-payment-business-cell]').first.evaluate('el => getComputedStyle(el).textAlign')
            assert cell_align == 'center', cell_align
            amount_width = page.locator('.quick-amount').first.evaluate('el => el.getBoundingClientRect().width')
            assert amount_width <= 84, amount_width

            # Business overview has its own display-attribute button and centered table.
            page.locator('[data-customer-tab="services"]').click()
            page.locator('[data-business-columns-settings-v0212]').wait_for(state='visible')
            page.locator('[data-business-columns-settings-v0212]').click()
            business_columns = page.locator('.business-columns-dialog-v0212')
            business_columns.wait_for(state='visible')
            assert business_columns.locator('[data-business-column-order-v0212]').count() >= 6
            business_columns.locator('[data-business-columns-close-v0212]').first.click()

            first_business_cell = page.locator('[data-business-row]').first.locator('.business-attribute').first
            align = first_business_cell.evaluate('el => getComputedStyle(el).textAlign')
            assert align == 'center', align

            # Double-click any business field opens editor. Top is business status;
            # lower attribute area remains the normal business-attribute editor.
            first_business_cell.dblclick()
            editor = page.locator('#businessAttributeDialog')
            editor.wait_for(state='visible')
            panel = editor.locator('[data-v03-business-status-panel]')
            panel.wait_for(state='visible')
            assert panel.locator('[data-v03-business-enabled]').count() == 1
            assert panel.locator('[data-v03-payment-state]').count() == 1
            assert editor.locator('[data-global-attribute-list] .global-attribute-row-v028').count() >= 6
            assert editor.locator('[data-business-display-order]').count() == 0
            editor.locator('[data-business-editor-close]').first.click()

            # Reversible workflow: review can be toggled, and paid undo restores cycle.
            page.locator('[data-customer-tab="payment"]').click()
            review = page.locator('[data-v03-flow-action="review"]')
            notify = page.locator('[data-v03-flow-action="notify"]')
            paid = page.locator('[data-v03-flow-action="paid"]')
            review.click()
            page.wait_for_timeout(120)
            assert review.get_attribute('aria-pressed') == 'true'
            review.click()
            page.wait_for_timeout(120)
            assert review.get_attribute('aria-pressed') == 'false'

            review.click(); page.wait_for_timeout(80)
            notify.click(); page.wait_for_timeout(80)
            paid.click(); page.wait_for_timeout(120)
            assert paid.get_attribute('aria-pressed') == 'true'
            with db() as conn:
                changed = conn.execute('SELECT next_payment_period FROM services WHERE id=?', (every_two,)).fetchone()['next_payment_period']
                assert changed == add_periods(period, 2), changed

            page.once('dialog', lambda d: d.accept())
            paid.click(); page.wait_for_timeout(160)
            assert paid.get_attribute('aria-pressed') == 'false'
            with db() as conn:
                restored = conn.execute('SELECT next_payment_period FROM services WHERE id=?', (every_two,)).fetchone()['next_payment_period']
                assert restored == period, restored

            # Legacy SMTP node remains hidden/disabled for compatibility only.
            email_button = page.locator('[data-v03-send-email]')
            assert email_button.is_disabled()

            browser.close()

        print('v0.3 browser acceptance passed (isolated test database)')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
