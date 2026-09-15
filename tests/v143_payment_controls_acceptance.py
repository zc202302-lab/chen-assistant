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
TMP = tempfile.TemporaryDirectory(prefix='chen-v143-payment-controls-')
TEST_DB = Path(TMP.name) / 'app.db'

os.environ.update({
    'APP_DB_PATH': str(TEST_DB),
    'APP_USERNAME': 'ui-test',
    'APP_PASSWORD_SALT': 'dGVzdHNhbHQ=',
    'APP_PASSWORD_HASH': 'x',
    'APP_SESSION_SECRET': 'v143-payment-controls-session',
    'APP_ENCRYPTION_KEY': 'x',
    'APP_SECURE_COOKIE': '0',
})

from app.db import db, init_db, now_iso  # noqa: E402
from app.payment_v02 import current_period  # noqa: E402
from app.security import create_session  # noqa: E402
from app.v031_payment_workflow_routes import ensure_v031  # noqa: E402


def add_completed_customer(conn, name: str, code: str, number: str) -> tuple[int, int]:
    now = now_iso()
    period = current_period()
    cid = int(conn.execute(
        '''INSERT INTO customers
           (name,group_code,payment_enabled,payment_period,notified,completed,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?)''',
        (name, code, 1, period, 1, 1, now, now),
    ).lastrowid)
    sid = int(conn.execute(
        '''INSERT INTO services
           (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
            payment_cycle,payment_interval_months,next_payment_period,active_from_period,
            sort_order,source_row,payment_method,last_payment_date)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (cid, '成员', name, number, f'{code}-ACC', 100, 1, '1个月', 1, '', period, 10, 1, '微信', now[:10]),
    ).lastrowid)
    conn.execute(
        '''INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at)
           VALUES(?,?,?,?,?)''',
        (sid, '1900-01', 'fixed', 100, now),
    )
    conn.execute(
        '''INSERT INTO payment_entries
           (service_id,period,amount,reference_amount,source,confirmed,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?)''',
        (sid, period, 100, 100, 'fixed', 1, now, now),
    )
    ensure_v031(conn)
    conn.execute(
        '''INSERT INTO customer_payment_runs
           (customer_id,period,reviewed_at,notified_at,initiated_at,paid_at,emailed_at,email_to,email_subject,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
        (cid, period, now, now, now, now, '', '', '', now, now),
    )
    # Intentionally do not create payment_run_service_snapshots_v03 rows. This
    # reproduces completed records created before the snapshot rollback feature.
    return cid, sid


def seed():
    init_db()
    with db() as conn:
        flow = add_completed_customer(conn, '旧记录流程客户', 'V143-FLOW', '13800002101')
        fixed = add_completed_customer(conn, '旧记录固定切换客户', 'V143-FIX', '13800002102')
        review = add_completed_customer(conn, '旧记录核对切换客户', 'V143-REV', '13800002103')
    token, _, _ = create_session()
    return flow, fixed, review, token


def wait_http(url: str):
    for _ in range(120):
        try:
            if urllib.request.urlopen(url, timeout=1).status == 200:
                return
        except Exception:
            pass
        time.sleep(.2)
    raise RuntimeError(f'server start failed: {url}')


def main():
    flow_case, fixed_case, review_case, token = seed()
    period = current_period()
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8154'],
        cwd=ROOT, env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8154/health')
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1450, 'height': 950})
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8154'}])
            page = context.new_page()

            # 1) The visible four-stage payment status must be manually reversible
            # even for an old paid record that has no historical schedule snapshot.
            cid, sid = flow_case
            page.goto(f'http://127.0.0.1:8154/customers/{cid}', wait_until='networkidle')
            page.wait_for_timeout(1000)
            flow = page.locator('[data-v031-payment-flow]')
            paid = flow.locator('[data-v031-flow-action="paid"]')
            initiated = flow.locator('[data-v031-flow-action="initiate"]')
            notified = flow.locator('[data-v031-flow-action="notify"]')
            reviewed = flow.locator('[data-v031-flow-action="review"]')
            expect(paid).to_have_attribute('aria-pressed', 'true')
            expect(paid).to_be_enabled()
            paid.click()
            expect(paid).to_have_attribute('aria-pressed', 'false', timeout=4000)
            expect(initiated).to_have_attribute('aria-pressed', 'true')
            expect(notified).to_have_attribute('aria-pressed', 'true')
            expect(reviewed).to_have_attribute('aria-pressed', 'true')
            with db() as conn:
                run = conn.execute(
                    'SELECT reviewed_at,notified_at,initiated_at,paid_at FROM customer_payment_runs WHERE customer_id=? AND period=?',
                    (cid, period),
                ).fetchone()
                assert run['reviewed_at'] and run['notified_at'] and run['initiated_at'] and run['paid_at'] == ''

            # 2) Fixed/variable is a working control, not a locked label. It can be
            # changed directly from a completed old record and rolls the flow back.
            cid, sid = fixed_case
            page.goto(f'http://127.0.0.1:8154/customers/{cid}', wait_until='networkidle')
            page.wait_for_timeout(1000)
            row = page.locator(f'[data-payment-row][data-service-id="{sid}"]')
            fixed_toggle = row.locator('[data-fixed-toggle]')
            expect(fixed_toggle).to_be_enabled(timeout=3000)
            expect(fixed_toggle).to_have_text('固')
            fixed_toggle.click()
            expect(fixed_toggle).to_have_text('变', timeout=4000)
            expect(row).to_have_attribute('data-mode', 'variable', timeout=4000)
            expect(row).to_have_attribute('data-confirmed', '0', timeout=4000)
            expect(page.locator('[data-v031-flow-action="review"]')).to_have_attribute('aria-pressed', 'false', timeout=4000)
            with db() as conn:
                rule = conn.execute(
                    '''SELECT mode FROM service_payment_rules WHERE service_id=? AND effective_period<=?
                       ORDER BY effective_period DESC,id DESC LIMIT 1''',
                    (sid, period),
                ).fetchone()
                assert rule['mode'] == 'variable'
                run = conn.execute(
                    'SELECT reviewed_at,notified_at,initiated_at,paid_at FROM customer_payment_runs WHERE customer_id=? AND period=?',
                    (cid, period),
                ).fetchone()
                assert run['reviewed_at'] == '' and run['notified_at'] == '' and run['initiated_at'] == '' and run['paid_at'] == ''

            # Toggle back to fixed: current amount is preserved and the row becomes
            # confirmed again; stage 1 follows the actual row state automatically.
            fixed_toggle.click()
            expect(fixed_toggle).to_have_text('固', timeout=4000)
            expect(row).to_have_attribute('data-mode', 'fixed', timeout=4000)
            expect(row).to_have_attribute('data-confirmed', '1', timeout=4000)
            expect(page.locator('[data-v031-flow-action="review"]')).to_have_attribute('aria-pressed', 'true', timeout=4000)

            # 3) Row review status itself is manually adjustable after completion.
            cid, sid = review_case
            page.goto(f'http://127.0.0.1:8154/customers/{cid}', wait_until='networkidle')
            page.wait_for_timeout(1000)
            row = page.locator(f'[data-payment-row][data-service-id="{sid}"]')
            review_toggle = row.locator('[data-review-toggle]')
            expect(review_toggle).to_be_enabled(timeout=3000)
            expect(row).to_have_attribute('data-confirmed', '1')
            review_toggle.click()
            expect(row).to_have_attribute('data-confirmed', '0', timeout=4000)
            expect(review_toggle).to_have_text('○', timeout=4000)
            expect(page.locator('#pendingCount')).to_have_text('1', timeout=4000)
            expect(page.locator('[data-v031-flow-action="review"]')).to_have_attribute('aria-pressed', 'false', timeout=4000)
            with db() as conn:
                entry = conn.execute(
                    'SELECT confirmed,source FROM payment_entries WHERE service_id=? AND period=?',
                    (sid, period),
                ).fetchone()
                assert int(entry['confirmed']) == 0
                assert entry['source'] == 'manual_unchecked'

            page.reload(wait_until='networkidle')
            page.wait_for_timeout(800)
            row = page.locator(f'[data-payment-row][data-service-id="{sid}"]')
            expect(row).to_have_attribute('data-confirmed', '0')
            row.locator('[data-review-toggle]').click()
            expect(row).to_have_attribute('data-confirmed', '1', timeout=4000)

            browser.close()
        print('v1.4.3 payment controls acceptance passed: legacy paid rollback + fixed toggle + manual review')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
