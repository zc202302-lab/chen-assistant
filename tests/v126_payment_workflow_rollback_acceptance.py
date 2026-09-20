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
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-v126-')
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
            'INSERT INTO customers(name,group_code,payment_enabled,created_at,updated_at) VALUES(?,?,?,?,?)',
            ('流程回退验收客户', 'ROLLBACK', 1, now, now),
        ).lastrowid)
        sid = int(conn.execute(
            '''INSERT INTO services
               (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
                payment_cycle,payment_interval_months,next_payment_period,active_from_period,
                sort_order,source_row,payment_method)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (cid, '成员', '成员1', '13800008888', 'RB-001', 100, 0,
             '1个月', 1, '', period, 10, 1, '微信'),
        ).lastrowid)
        conn.execute(
            'INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at) VALUES(?,?,?,?,?)',
            (sid, '1900-01', 'variable', 0, now),
        )
        conn.execute(
            '''INSERT INTO payment_entries(service_id,period,amount,reference_amount,source,confirmed,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?)''',
            (sid, period, 100, 100, 'manual', 1, now, now),
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
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8146'],
        cwd=ROOT, env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8146/health')
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1450, 'height': 950})
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8146'}])
            page = context.new_page()
            page.goto(f'http://127.0.0.1:8146/customers/{cid}', wait_until='networkidle')
            page.wait_for_timeout(1200)

            review = page.locator('[data-v031-flow-action="review"]')
            notify = page.locator('[data-v031-flow-action="notify"]')
            initiate = page.locator('[data-v031-flow-action="initiate"]')

            # Stage 1 is derived from row truth and starts automatically complete.
            expect(review).to_have_attribute('aria-pressed', 'true', timeout=5000)
            expect(review).to_be_disabled()

            # External actions are stubbed: this test verifies workflow state only.
            page.evaluate('''() => {
                const a = window.ChenPaymentWorkflowActionsV031;
                a.prepareNotice = async () => ({mode:'clipboard', test:true});
                a.prepareInitiate = async () => ({mode:'test', verified:true});
            }''')

            # Notify is two-step: prepare, then confirm. Once completed it MUST be
            # reversible while no downstream stage has been completed.
            notify.click()
            expect(notify).to_contain_text('待确认', timeout=5000)
            notify.click()
            expect(notify).to_have_attribute('aria-pressed', 'true', timeout=5000)
            expect(notify).to_contain_text('✓', timeout=5000)

            notify.click()
            expect(notify).to_have_attribute('aria-pressed', 'false', timeout=5000)
            expect(notify).not_to_contain_text('✓', timeout=5000)
            expect(review).to_have_attribute('aria-pressed', 'true', timeout=5000)
            with db() as conn:
                row = conn.execute(
                    'SELECT notified_at,initiated_at,paid_at FROM customer_payment_runs WHERE customer_id=? AND period=?',
                    (cid, current_period()),
                ).fetchone()
                assert not row['notified_at'] and not row['initiated_at'] and not row['paid_at']

            # The stage can be completed again after rollback. Wait for the
            # prepared state before confirming so the test is runner-speed independent.
            notify.click()
            expect(notify).to_contain_text('待确认', timeout=5000)
            notify.click()
            expect(notify).to_have_attribute('aria-pressed', 'true', timeout=5000)

            # Complete stage 3. Stage 2 is now protected by dependency order.
            initiate.click()
            expect(initiate).to_contain_text('待确认', timeout=5000)
            initiate.click()
            expect(initiate).to_have_attribute('aria-pressed', 'true', timeout=5000)
            expect(notify).to_be_disabled(timeout=5000)

            # Reverse-order rollback: stage 3 first, then stage 2.
            initiate.click()
            expect(initiate).to_have_attribute('aria-pressed', 'false', timeout=5000)
            expect(notify).to_be_enabled(timeout=5000)
            expect(notify).to_have_attribute('aria-pressed', 'true', timeout=5000)
            notify.click()
            expect(notify).to_have_attribute('aria-pressed', 'false', timeout=5000)
            expect(review).to_have_attribute('aria-pressed', 'true', timeout=5000)

            browser.close()
        print('v1.2.6 payment workflow rollback acceptance passed')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
