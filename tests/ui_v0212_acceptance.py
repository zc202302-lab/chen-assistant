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

            # Payment amount is a core payment function: shown in table, absent from attribute chooser.
            headers = page.locator('[data-payment-column-head]')
            labels = [x.strip() for x in headers.locator('span').all_inner_texts()]
            assert '缴费金额' in labels, labels
            amount_head = page.locator('[data-payment-column-head][data-payment-attr-key="payment_amount"]')
            assert amount_head.get_attribute('draggable') == 'true'
            page.locator('[data-payment-columns-settings]').click()
            dialog = page.locator('#paymentColumnsDialog')
            dialog.wait_for(state='visible')
            values = dialog.locator('select option').evaluate_all('opts => opts.map(o => o.value)')
            assert 'payment_amount' not in values, values
            assert dialog.locator('[data-payment-column-row]').count() == 4
            dialog.locator('[data-payment-columns-close]').first.click()

            # Business module has independent visibility controls and an always-visible schedule state.
            page.locator('[data-customer-tab="services"]').click()
            row = page.locator(f'[data-business-row][data-service-id="{monthly}"]')
            assert '本月应缴' in row.inner_text()
            row.locator('[data-open-service-editor]').click()
            editor = page.locator('#businessAttributeDialog')
            editor.wait_for(state='visible')
            editor.locator('[data-business-status-v0212]').wait_for(state='visible')
            checks = editor.locator('[data-business-visible-v0212]')
            assert checks.count() >= 5

            account_row = editor.locator('.global-attribute-row-v028[data-key="account"]')
            method_row = editor.locator('.global-attribute-row-v028[data-key="payment_method"]')
            account_check = account_row.locator('[data-business-visible-v0212]')
            method_check = method_row.locator('[data-business-visible-v0212]')
            if account_check.is_checked():
                account_check.uncheck()
            if not method_check.is_checked():
                method_check.check()
            editor.locator('[data-business-attribute-form] button[type="submit"]').click()
            page.wait_for_load_state('networkidle')

            page.locator('[data-customer-tab="services"]').click()
            header_text = page.locator('[data-business-table-header]').inner_text()
            assert '缴费状态' in header_text
            assert '付款方式' in header_text
            assert '账号' not in header_text

            # Payment module kept its own selection; business visibility did not overwrite it.
            page.locator('[data-customer-tab="payment"]').click()
            payment_header_text = page.locator('.v0211-payment-header').inner_text()
            assert '账号' in payment_header_text, payment_header_text

            # Deferral: 1 means current month skipped; row immediately leaves payment workbench.
            monthly_row = page.locator(f'[data-payment-row][data-service-id="{monthly}"]')
            monthly_row.locator('[data-defer-payment-v0212]').click()
            defer_input = monthly_row.locator('.payment-defer-input-v0212')
            defer_input.fill('1')
            defer_input.press('Enter')
            page.wait_for_load_state('networkidle')
            assert page.locator(f'[data-payment-row][data-service-id="{monthly}"]').count() == 0

            page.locator('[data-customer-tab="services"]').click()
            monthly_business = page.locator(f'[data-business-row][data-service-id="{monthly}"]')
            assert '延期至' in monthly_business.inner_text()

            # Business status controls whether a due row is allowed into payment.
            two_business = page.locator(f'[data-business-row][data-service-id="{every_two}"]')
            two_business.locator('[data-open-service-editor]').click()
            editor.wait_for(state='visible')
            status = editor.locator('[data-business-status-v0212]')
            status.select_option('inactive')
            editor.locator('[data-business-attribute-form] button[type="submit"]').click()
            page.wait_for_load_state('networkidle')
            page.locator('[data-customer-tab="payment"]').click()
            assert page.locator(f'[data-payment-row][data-service-id="{every_two}"]').count() == 0

            # Hard delete from business editor.
            page.locator('[data-customer-tab="services"]').click()
            annual_row = page.locator(f'[data-business-row][data-service-id="{annual}"]')
            annual_row.locator('[data-open-service-editor]').click()
            editor.wait_for(state='visible')
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
