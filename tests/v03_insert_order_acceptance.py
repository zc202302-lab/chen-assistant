from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v03-insert-order-')
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
from app.payment_v02 import current_period  # noqa: E402
from app.security import create_session  # noqa: E402


def seed():
    init_db()
    now = now_iso()
    period = current_period()
    with db() as conn:
        cid = int(conn.execute(
            'INSERT INTO customers (name,group_code,tax_id,payment_enabled,created_at,updated_at) VALUES(?,?,?,?,?,?)',
            ('插入排序测试客户', 'ORDER001', '', 1, now, now),
        ).lastrowid)
        sid = int(conn.execute(
            '''INSERT INTO services
               (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
                payment_cycle,payment_interval_months,active_from_period,sort_order,source_row,
                payment_method,invoice_type,package_type,notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (cid, '成员', '后勤', '13800000001', '5338000000001', 88, 1,
             '1个月', 1, period, 10, 1, '微信', '普票', '套餐A', '测试'),
        ).lastrowid)
        conn.execute(
            'INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at) VALUES(?,?,?,?,?)',
            (sid, '1900-01', 'fixed', 88, now),
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


def values(locator):
    result = []
    for i in range(locator.count()):
        raw = locator.nth(i).input_value().strip()
        result.append(int(raw) if raw.isdigit() else None)
    return result


def assert_insert_at(page, selector: str, position: int):
    inputs = page.locator(selector)
    before = values(inputs)
    numbered = [(i, n) for i, n in enumerate(before) if n is not None]
    assert len(numbered) >= 3, before
    hidden_index = next((i for i, n in enumerate(before) if n is None), None)
    assert hidden_index is not None, before

    old_by_order = {n: i for i, n in numbered}
    target = inputs.nth(hidden_index)
    target.fill(str(position))
    page.wait_for_timeout(350)
    after = values(inputs)

    assert after[hidden_index] == position, (before, after)
    # Existing rows before the insertion point keep their position.
    for n in range(1, position):
        if n in old_by_order:
            assert after[old_by_order[n]] == n, (n, before, after)
    # Existing row at and after insertion point shifts one place right.
    for n in range(position, min(max(old_by_order), position + 2) + 1):
        if n in old_by_order:
            assert after[old_by_order[n]] == n + 1, (n, before, after)


def main():
    cid, token = seed()
    assert TEST_DB.resolve() != (ROOT / 'data' / 'app.db').resolve()
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8133'],
        cwd=ROOT,
        env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8133/health')
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1500, 'height': 1000})
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8133'}])
            page = context.new_page()
            page.goto(f'http://127.0.0.1:8133/customers/{cid}', wait_until='networkidle')

            # Payment display settings: inserting at 1 shifts former 1/2/3 to 2/3/4.
            page.locator('[data-payment-columns-settings]').click()
            page.locator('#paymentColumnsDialog').wait_for(state='visible')
            assert_insert_at(page, '#paymentColumnsDialog [data-v03-payment-order]', 1)
            page.locator('#paymentColumnsDialog [data-payment-columns-close]').first.click()

            # Business display settings: inserting at 2 keeps former 1 and shifts 2/3.
            page.locator('[data-customer-tab="services"]').click()
            button = page.locator('[data-business-columns-settings-v0212]')
            button.wait_for(state='visible')
            button.click()
            dialog = page.locator('.business-columns-dialog-v0212')
            dialog.wait_for(state='visible')
            assert_insert_at(page, '.business-columns-dialog-v0212 [data-business-column-order-v0212]', 2)

            browser.close()

        print('v0.3 insertion-order browser acceptance passed (isolated test database)')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
