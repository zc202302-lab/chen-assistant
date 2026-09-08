from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = ROOT / 'data' / 'app.db'
for suffix in ('', '-wal', '-shm'):
    p = Path(str(DB) + suffix)
    if p.exists():
        p.unlink()

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
            'INSERT INTO customers (name,group_code,tax_id,payment_enabled,created_at,updated_at) VALUES(?,?,?,?,?,?)',
            ('v0212验收客户', 'V0212', 'V0212-TAX', 1, now, now),
        ).lastrowid)
        specs = [
            ('月缴', '甲', '13800131201', 'A1201', 1, '', '微信'),
            ('年缴', '乙', '13800131202', 'A1202', 12, add_periods(period, 6), '转账'),
            ('双月缴', '丙', '13800131203', 'A1203', 2, period, '支付宝'),
        ]
        ids = []
        for idx, (typ, holder, number, account, months, nxt, method) in enumerate(specs, 1):
            sid = int(conn.execute(
                '''INSERT INTO services
                   (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
                    payment_cycle,payment_interval_months,next_payment_period,active_from_period,
                    sort_order,source_row,payment_method,invoice_type,package_type,notes)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (cid, typ, holder, number, account, 100 + idx, 0,
                 f'{months}个月', months, nxt, period, idx * 10, idx,
                 method, '普票', f'套餐{idx}', f'备注{idx}'),
            ).lastrowid)
            ids.append(sid)
            conn.execute(
                'INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at) VALUES(?,?,?,?,?)',
                (sid, '1900-01', 'variable', 0, now),
            )
    token, _, _ = create_session()
    return cid, ids, token


def wait_http(url):
    for _ in range(80):
        try:
            if urllib.request.urlopen(url, timeout=1).status == 200:
                return
        except Exception:
            pass
        time.sleep(.2)
    raise RuntimeError('server start failed')


def set_business_orders(editor, orders):
    rows = editor.locator('.global-attribute-row-v028')
    for i in range(rows.count()):
        row = rows.nth(i)
        key = row.get_attribute('data-key') or ''
        inp = row.locator('[data-business-display-order]')
        assert inp.count() == 1, key
        inp.fill(str(orders[key]) if key in orders else '')


def header_labels(page):
    page.wait_for_timeout(120)
    return [x.strip() for x in page.locator('[data-business-table-header] .business-table-header-cell-v030').all_inner_texts()]


def main():
    cid, (monthly, annual, every_two), token = seed()
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8129'],
        cwd=ROOT,
        env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8129/health')
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1500, 'height': 1000})
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8129'}])
            page = context.new_page()
            page.goto(f'http://127.0.0.1:8129/customers/{cid}', wait_until='networkidle')

            # Strict due schedule: annual future row must not leak into payment.
            ids = page.locator('[data-payment-row]').evaluate_all('rows => rows.map(r => Number(r.dataset.serviceId))')
            assert ids == [monthly, every_two], ids
            assert annual not in ids

            # Payment amount remains a core payment function and payment display selection is independent.
            headers = page.locator('[data-payment-column-head]')
            labels = [x.strip() for x in headers.locator('span').all_inner_texts()]
            assert '缴费金额' in labels, labels
            amount_head = page.locator('[data-payment-column-head][data-payment-attr-key="payment_amount"]')
            assert amount_head.get_attribute('draggable') == 'true'
            page.locator('[data-payment-columns-settings]').click()
            payment_dialog = page.locator('#paymentColumnsDialog')
            payment_dialog.wait_for(state='visible')
            values = payment_dialog.locator('select option').evaluate_all('opts => opts.map(o => o.value)')
            assert 'payment_amount' not in values, values
            payment_dialog.locator('[data-payment-columns-close]').first.click()

            page.locator('[data-customer-tab="services"]').click()
            row = page.locator(f'[data-business-row][data-service-id="{monthly}"]')
            row.locator('[data-open-service-editor]').click()
            editor = page.locator('#businessAttributeDialog')
            editor.wait_for(state='visible')
            editor.locator('[data-business-status-v0212]').wait_for(state='visible')
            editor.locator('.global-attribute-row-v028[data-key="__payment_state__"]').wait_for(state='visible')

            # Checkbox-based visibility is gone. Each attribute has a manual display-order number.
            page.wait_for_timeout(100)
            assert editor.locator('[data-business-visible-v0212]').count() == 0
            order_inputs = editor.locator('[data-business-display-order]')
            assert order_inputs.count() >= 6

            # Only numbered attributes show; numeric order controls actual business-column order.
            # Payment state is deliberately left blank to prove it is no longer a fixed column.
            set_business_orders(editor, {
                'payment_method': 1,
                'service_type': 2,
                'account': 3,
            })
            url_before = page.url
            editor.locator('[data-business-attribute-form] button[type="submit"]').click()
            editor.wait_for(state='hidden')
            assert page.url == url_before  # no page navigation/reload required
            assert header_labels(page) == ['付款方式', '类型', '账号'], header_labels(page)

            business_text = row.locator('[data-business-attrs]').inner_text()
            assert '微信' in business_text and '月缴' in business_text and 'A1201' in business_text
            assert '缴费状态' not in business_text

            # Payment module kept its own column selection; business display order did not overwrite it.
            page.locator('[data-customer-tab="payment"]').click()
            payment_header_text = page.locator('.v0211-payment-header').inner_text()
            assert '账号' in payment_header_text, payment_header_text

            # Payment state behaves like an ordinary business display attribute: give it an order and it appears immediately.
            page.locator('[data-customer-tab="services"]').click()
            row.locator('[data-open-service-editor]').click()
            editor.wait_for(state='visible')
            set_business_orders(editor, {
                '__payment_state__': 1,
                'account': 2,
            })
            editor.locator('[data-business-attribute-form] button[type="submit"]').click()
            editor.wait_for(state='hidden')
            assert header_labels(page) == ['缴费状态', '账号'], header_labels(page)
            assert '本月应缴' in row.locator('[data-business-attrs]').inner_text()

            # Deferral updates the derived payment-state attribute through the shared runtime data.
            page.locator('[data-customer-tab="payment"]').click()
            monthly_row = page.locator(f'[data-payment-row][data-service-id="{monthly}"]')
            monthly_row.locator('[data-defer-payment-v0212]').click()
            defer_input = monthly_row.locator('.payment-defer-input-v0212')
            defer_input.fill('1')
            defer_input.press('Enter')
            page.locator(f'[data-payment-row][data-service-id="{monthly}"]').wait_for(state='detached', timeout=5000)
            assert page.locator(f'[data-payment-row][data-service-id="{monthly}"]').count() == 0

            page.locator('[data-customer-tab="services"]').click()
            monthly_business = page.locator(f'[data-business-row][data-service-id="{monthly}"]')
            assert '延期至' in monthly_business.inner_text()

            # Business status still controls payment eligibility.
            two_business = page.locator(f'[data-business-row][data-service-id="{every_two}"]')
            two_business.locator('[data-open-service-editor]').click()
            editor.wait_for(state='visible')
            status = editor.locator('[data-business-status-v0212]')
            status.select_option('inactive')
            editor.locator('[data-business-attribute-form] button[type="submit"]').click()
            editor.wait_for(state='hidden')
            page.reload(wait_until='networkidle')
            assert page.locator(f'[data-payment-row][data-service-id="{every_two}"]').count() == 0

            # Hard delete remains available from the business editor.
            page.locator('[data-customer-tab="services"]').click()
            annual_row = page.locator(f'[data-business-row][data-service-id="{annual}"]')
            annual_row.locator('[data-open-service-editor]').click()
            editor.wait_for(state='visible')
            assert editor.locator('[data-delete-service-v0212]').count() == 1
            page.once('dialog', lambda d: d.accept())
            editor.locator('[data-delete-service-v0212]').click()
            page.wait_for_load_state('networkidle')
            assert page.locator(f'[data-business-row][data-service-id="{annual}"]').count() == 0

            browser.close()

        with db() as conn:
            assert conn.execute('SELECT id FROM services WHERE id=?', (annual,)).fetchone() is None
            runtime = conn.execute(
                'SELECT status,deferred_until_period FROM service_runtime_v0212 WHERE service_id=?',
                (monthly,),
            ).fetchone()
            assert runtime and runtime['deferred_until_period'] == add_periods(current_period(), 1)
            two_runtime = conn.execute(
                'SELECT status FROM service_runtime_v0212 WHERE service_id=?', (every_two,)
            ).fetchone()
            assert two_runtime and two_runtime['status'] == 'inactive'

        print('v0.2.12 browser acceptance passed')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
