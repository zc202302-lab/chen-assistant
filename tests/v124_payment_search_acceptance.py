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
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-v124-')
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
    cases = [
        ('回车确认-金额不变', 'G-A', 'variable', 100.0, 100.0),
        ('回车确认-金额修改', 'G-B', 'variable', 120.0, 125.0),
        ('回车确认-固定金额修改', 'G-C', 'fixed', 88.0, 90.0),
        ('回车确认-零元', 'G-D', 'variable', 20.0, 0.0),
    ]
    seeded = []
    with db() as conn:
        for idx, (name, group_code, mode, old_amount, entered_amount) in enumerate(cases, 1):
            cid = int(conn.execute(
                '''INSERT INTO customers(name,group_code,payment_enabled,created_at,updated_at)
                   VALUES(?,?,?,?,?)''',
                (name, group_code, 1, now, now),
            ).lastrowid)
            sid = int(conn.execute(
                '''INSERT INTO services
                   (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
                    payment_cycle,payment_interval_months,next_payment_period,active_from_period,
                    sort_order,source_row,payment_method)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (cid, '成员', f'使用人{idx}', f'1390000000{idx}', f'ACC-{idx}', old_amount,
                 1 if mode == 'fixed' else 0, '1个月', 1, '', period, idx * 10, idx, '微信'),
            ).lastrowid)
            # Add a second service to one customer so table search/filter behavior can
            # prove it hides nonmatching rows rather than merely finding a single row.
            extra_sid = None
            if idx == 2:
                extra_sid = int(conn.execute(
                    '''INSERT INTO services
                       (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
                        payment_cycle,payment_interval_months,next_payment_period,active_from_period,
                        sort_order,source_row,payment_method)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (cid, '专线', '备用业务', '05331234567', 'BACKUP-ACC', 50, 0,
                     '1个月', 1, '', period, 999, 999, '转账'),
                ).lastrowid)
                conn.execute(
                    '''INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at)
                       VALUES(?,?,?,?,?)''',
                    (extra_sid, '1900-01', 'variable', 0, now),
                )
                conn.execute(
                    '''INSERT INTO payment_entries(service_id,period,amount,reference_amount,source,confirmed,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?)''',
                    (extra_sid, period, 50, 50, 'inherited', 0, now, now),
                )
            conn.execute(
                '''INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at)
                   VALUES(?,?,?,?,?)''',
                (sid, '1900-01', mode, old_amount if mode == 'fixed' else 0, now),
            )
            # Deliberately start every case unconfirmed, including fixed. Snapshot
            # repair may auto-confirm fixed before the page is rendered; Enter must
            # still leave it confirmed after a real amount change.
            conn.execute(
                '''INSERT INTO payment_entries(service_id,period,amount,reference_amount,source,confirmed,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)''',
                (sid, period, old_amount, old_amount, 'inherited' if mode == 'variable' else 'fixed', 0, now, now),
            )
            seeded.append((cid, sid, entered_amount, mode, extra_sid))
    token, _, _ = create_session()
    return seeded, token


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
    seeded, token = seed()
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8144'],
        cwd=ROOT, env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8144/health')
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1500, 'height': 1000})
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8144'}])
            page = context.new_page()

            for cid, sid, entered, mode, _ in seeded:
                page.goto(f'http://127.0.0.1:8144/customers/{cid}', wait_until='networkidle')
                row = page.locator(f'[data-payment-row][data-service-id="{sid}"]')
                row.wait_for(state='visible')
                amount = row.locator('.quick-amount')
                amount.fill(str(entered))
                amount.press('Enter')
                expect(row).to_have_attribute('data-confirmed', '1', timeout=5000)
                expect(row.locator('[data-row-state]')).to_have_text('✓', timeout=5000)
                if mode == 'variable' and len(page.locator('[data-payment-row]').all()) == 1:
                    expect(page.locator('#pendingCount')).to_have_text('0', timeout=5000)
                assert page.locator('[data-v124-payment-tools]').count() == 1
                assert page.locator('.v124-payment-total-row #paymentGrandTotal').count() == 1

            # Customer B has two rows: exercise payment search and status filters.
            cid, sid, _, _, extra_sid = seeded[1]
            page.goto(f'http://127.0.0.1:8144/customers/{cid}', wait_until='networkidle')
            search = page.locator('[data-v124-payment-search]')
            search.fill('BACKUP-ACC')
            expect(page.locator(f'[data-payment-row][data-service-id="{extra_sid}"]')).to_be_visible()
            expect(page.locator(f'[data-payment-row][data-service-id="{sid}"]')).to_be_hidden()
            search.fill('')

            # Exact number search must skip an intermediate results page and land on
            # the matching business tab + row. This is the work-home search contract.
            number = '13900000002'
            page.goto(f'http://127.0.0.1:8144/search?q={number}', wait_until='networkidle')
            assert f'/customers/{cid}' in page.url, page.url
            assert 'tab=services' in page.url and f'focus_service={sid}' in page.url, page.url
            target = page.locator(f'[data-business-row][data-service-id="{sid}"]')
            expect(target).to_be_visible(timeout=5000)
            expect(target).to_have_class(__import__('re').compile(r'v124-focus-hit'), timeout=5000)
            assert page.locator('[data-v124-business-search]').count() == 1

            # Group-code search remains available and returns the customer.
            page.goto('http://127.0.0.1:8144/search?q=G-B', wait_until='networkidle')
            expect(page.locator('section.card').filter(has_text='客户')).to_contain_text('回车确认-金额修改')

            browser.close()
        print('v1.2.4 payment Enter-confirm + totals + work search/table filters acceptance passed')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
