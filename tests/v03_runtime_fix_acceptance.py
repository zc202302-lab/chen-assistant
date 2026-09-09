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
from app import v0212_routes as core  # noqa: E402


def seed():
    init_db()
    now = now_iso()
    period = current_period()
    with db() as conn:
        cid = int(conn.execute(
            'INSERT INTO customers(name,group_code,tax_id,payment_enabled,created_at,updated_at) VALUES(?,?,?,?,?,?)',
            ('流程修复测试客户', 'C-V03-FIX', 'TAX-V03-FIX', 1, now, now),
        ).lastrowid)
        ids = []
        for idx, number in enumerate(('18000000001', '18000000002'), 1):
            sid = int(conn.execute(
                '''INSERT INTO services
                   (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
                    payment_cycle,payment_interval_months,next_payment_period,active_from_period,
                    sort_order,source_row,payment_method)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (cid, '成员', f'成员{idx}', number, f'A{idx}', 100 + idx, 1,
                 '1个月', 1, '', period, idx * 10, idx, '微信'),
            ).lastrowid)
            ids.append(sid)
            conn.execute(
                'INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at) VALUES(?,?,?,?,?)',
                (sid, '1900-01', 'fixed', 100 + idx, now),
            )
        core._save_runtime(conn, ids[1], deferred_until_period=add_periods(period, 1))
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
    normal_sid, deferred_sid = ids
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8131'],
        cwd=ROOT,
        env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8131/health')
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1500, 'height': 1000})
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8131'}])
            page = context.new_page()
            page.goto(f'http://127.0.0.1:8131/customers/{cid}', wait_until='networkidle')

            # Regression from production screenshot: the three pills must never be blank.
            flow = page.locator('[data-v03-payment-flow]')
            flow.wait_for(state='visible')
            labels = [x.strip() for x in flow.locator('[data-v03-flow-action]').all_inner_texts()]
            assert labels == ['1 金额核对', '2 通知客户', '3 完成缴费'], labels

            review = flow.locator('[data-v03-flow-action="review"]')
            review.click()
            page.wait_for_timeout(120)
            assert review.get_attribute('aria-pressed') == 'true'
            review.click()
            page.wait_for_timeout(120)
            assert review.get_attribute('aria-pressed') == 'false'

            # Business editor exposes an editable payment-state select for a deferred service.
            page.locator('[data-customer-tab="services"]').click()
            row = page.locator(f'[data-business-row][data-service-id="{deferred_sid}"]')
            row.locator('.business-attribute').first.dblclick()
            editor = page.locator('#businessAttributeDialog')
            editor.wait_for(state='visible')
            payment_mode = editor.locator('[data-v031-payment-mode]')
            payment_mode.wait_for(state='visible')
            assert payment_mode.input_value() == 'deferred'
            assert '延期至' in payment_mode.locator('option[value="deferred"]').inner_text()

            page.once('dialog', lambda d: d.accept())
            payment_mode.select_option('normal')
            page.wait_for_timeout(180)
            assert payment_mode.input_value() == 'normal'
            assert '本月应缴' in editor.locator('[data-v03-payment-state]').inner_text()
            with db() as conn:
                runtime = core._runtime_for(conn, deferred_sid)
                assert runtime['deferred_until_period'] == '', runtime

            editor.locator('[data-business-editor-close]').first.click()
            page.locator('[data-customer-tab="payment"]').click()
            page.wait_for_load_state('networkidle')
            assert page.locator(f'[data-payment-row][data-service-id="{normal_sid}"]').count() == 1
            assert page.locator(f'[data-payment-row][data-service-id="{deferred_sid}"]').count() == 1

            browser.close()
        print('v0.3 runtime fix browser acceptance passed')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
