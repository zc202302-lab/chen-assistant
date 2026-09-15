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
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v141-browser-')
TEST_DB = Path(_TMPDIR.name) / 'app.db'
os.environ['APP_DB_PATH'] = str(TEST_DB)
os.environ.update({
    'APP_USERNAME': 'ui-test',
    'APP_PASSWORD_SALT': 'dGVzdHNhbHQ=',
    'APP_PASSWORD_HASH': 'x',
    'APP_SESSION_SECRET': 'v141-browser-session',
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
            ('v141核对验收客户', 'V141', 1, now, now),
        ).lastrowid)
        ids = []
        for idx, (mode, amount) in enumerate((('variable', 100), ('fixed', 120)), 1):
            sid = int(conn.execute(
                '''INSERT INTO services
                   (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
                    payment_cycle,payment_interval_months,next_payment_period,active_from_period,
                    sort_order,source_row,payment_method)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (cid, '成员', f'成员{idx}', f'1380000010{idx}', f'V141-{idx}', amount,
                 1 if mode == 'fixed' else 0, '1个月', 1, period, period, idx * 10, idx, '微信'),
            ).lastrowid)
            ids.append(sid)
            conn.execute(
                'INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at) VALUES(?,?,?,?,?)',
                (sid, '1900-01', mode, amount if mode == 'fixed' else 0, now),
            )
    token, _, _ = create_session()
    return cid, ids, token


def wait_http(url: str):
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
    variable_sid, fixed_sid = ids
    period = current_period()
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8144'],
        cwd=ROOT, env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8144/health')
        from playwright.sync_api import expect, sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1450, 'height': 950})
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8144'}])
            page = context.new_page()

            # The top-left control is a deterministic parent-level navigation.
            # This must test the actual click, not only the fallback attribute.
            page.goto('http://127.0.0.1:8144/work/customers?home=payment', wait_until='networkidle')
            back = page.locator('[data-global-back]')
            expect(back).to_have_attribute('data-back-fallback', '/work')
            back.click()
            expect(page).to_have_url('http://127.0.0.1:8144/work', timeout=3000)

            page.goto(f'http://127.0.0.1:8144/customers/{cid}', wait_until='networkidle')
            flow = page.locator('[data-v031-payment-flow]')
            flow.wait_for(state='visible')
            page.wait_for_timeout(1200)

            review = flow.locator('[data-v031-flow-action="review"]')
            notify = flow.locator('[data-v031-flow-action="notify"]')
            initiate = flow.locator('[data-v031-flow-action="initiate"]')
            variable_row = page.locator(f'[data-payment-row][data-service-id="{variable_sid}"]')
            fixed_row = page.locator(f'[data-payment-row][data-service-id="{fixed_sid}"]')
            variable_state = variable_row.locator('[data-review-toggle]')
            fixed_state = fixed_row.locator('[data-review-toggle]')

            # Fixed rows start auto-confirmed; variable row starts pending.
            expect(fixed_row).to_have_attribute('data-confirmed', '1')
            expect(variable_row).to_have_attribute('data-confirmed', '0')
            variable_state.click()
            expect(variable_row).to_have_attribute('data-confirmed', '1', timeout=3000)
            expect(fixed_row).to_have_attribute('data-confirmed', '1', timeout=3000)
            expect(review).to_have_attribute('aria-pressed', 'true', timeout=3000)

            # Simulate already completed communication stages. A later manual row
            # uncheck must invalidate them without touching any other row review.
            with db() as conn:
                run = conn.execute(
                    'SELECT id FROM customer_payment_runs WHERE customer_id=? AND period=?',
                    (cid, period),
                ).fetchone()
                assert run, 'payment run missing after stage-1 auto completion'
                now = now_iso()
                conn.execute(
                    '''UPDATE customer_payment_runs
                       SET reviewed_at=?,notified_at=?,initiated_at=?,updated_at=? WHERE id=?''',
                    (now, now, now, now, int(run['id'])),
                )
            page.evaluate('() => window.ChenPaymentWorkflowRuntimeV031.refresh()')
            expect(notify).to_have_attribute('aria-pressed', 'true', timeout=3000)
            expect(initiate).to_have_attribute('aria-pressed', 'true', timeout=3000)

            # A confirmed fixed row must be manually clickable. Only this row
            # becomes pending; the variable row stays confirmed; the whole flow
            # rolls back to amount review.
            expect(fixed_state).to_be_enabled(timeout=3000)
            fixed_state.click()
            expect(fixed_row).to_have_attribute('data-confirmed', '0', timeout=3000)
            expect(variable_row).to_have_attribute('data-confirmed', '1', timeout=3000)
            expect(page.locator('#pendingCount')).to_have_text('1', timeout=3000)
            expect(review).to_have_attribute('aria-pressed', 'false', timeout=3000)
            expect(notify).to_have_attribute('aria-pressed', 'false', timeout=3000)
            expect(initiate).to_have_attribute('aria-pressed', 'false', timeout=3000)
            expect(fixed_state).to_have_text('○', timeout=3000)

            with db() as conn:
                rows = conn.execute(
                    'SELECT service_id,confirmed,source FROM payment_entries WHERE period=? ORDER BY service_id',
                    (period,),
                ).fetchall()
                by_id = {int(row['service_id']): row for row in rows}
                assert int(by_id[variable_sid]['confirmed']) == 1
                assert int(by_id[fixed_sid]['confirmed']) == 0
                assert by_id[fixed_sid]['source'] == 'manual_unchecked'
                run = conn.execute(
                    'SELECT reviewed_at,notified_at,initiated_at FROM customer_payment_runs WHERE customer_id=? AND period=?',
                    (cid, period),
                ).fetchone()
                assert run['reviewed_at'] == '' and run['notified_at'] == '' and run['initiated_at'] == ''

            # Refresh must not auto-repair the deliberately unchecked fixed row.
            page.reload(wait_until='networkidle')
            page.wait_for_timeout(1000)
            fixed_row = page.locator(f'[data-payment-row][data-service-id="{fixed_sid}"]')
            variable_row = page.locator(f'[data-payment-row][data-service-id="{variable_sid}"]')
            fixed_state = fixed_row.locator('[data-review-toggle]')
            expect(fixed_row).to_have_attribute('data-confirmed', '0')
            expect(variable_row).to_have_attribute('data-confirmed', '1')

            # Clicking the same marker confirms it again and auto-completes stage 1.
            fixed_state.click()
            expect(fixed_row).to_have_attribute('data-confirmed', '1', timeout=3000)
            expect(variable_row).to_have_attribute('data-confirmed', '1', timeout=3000)
            expect(page.locator('[data-v031-flow-action="review"]')).to_have_attribute('aria-pressed', 'true', timeout=3000)

            # Variable rows are equally manual: unchecking one does not alter fixed row.
            variable_row.locator('[data-review-toggle]').click()
            expect(variable_row).to_have_attribute('data-confirmed', '0', timeout=3000)
            expect(fixed_row).to_have_attribute('data-confirmed', '1', timeout=3000)
            expect(page.locator('[data-v031-flow-action="review"]')).to_have_attribute('aria-pressed', 'false', timeout=3000)

            browser.close()

        print('v1.4.1 navigation + manual row review rollback acceptance passed')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
