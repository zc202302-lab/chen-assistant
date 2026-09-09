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
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v03-review-reset-')
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
            ('固定金额自动确认测试', 'C-RESET', 'RESET-TAX', 1, now, now),
        ).lastrowid)
        ids = []
        for idx in range(2):
            amount = 40 + idx * 10
            sid = int(conn.execute(
                '''INSERT INTO services
                   (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
                    payment_cycle,payment_interval_months,next_payment_period,active_from_period,
                    sort_order,source_row,payment_method,invoice_type,package_type,notes)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (cid, '成员', f'成员{idx + 1}', f'1580000000{idx}', f'53380000000{idx}', amount, 1,
                 '1个月', 1, '', period, (idx + 1) * 10, idx + 1,
                 '微信', '普票', '', ''),
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


def wait_review_state(page, pressed: bool):
    wanted = 'true' if pressed else 'false'
    page.wait_for_function(
        "wanted => document.querySelector('[data-v031-flow-action=\"review\"]')?.getAttribute('aria-pressed') === wanted",
        arg=wanted,
        timeout=5000,
    )


def main():
    cid, ids, token = seed()
    assert TEST_DB.resolve() != (ROOT / 'data' / 'app.db').resolve()
    period = current_period()
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
            page.wait_for_timeout(1100)

            review = page.locator('[data-v031-flow-action="review"]')
            review.wait_for(state='visible')
            rows = page.locator('[data-payment-row]')
            assert rows.count() == 2
            for i in range(2):
                row = rows.nth(i)
                assert row.get_attribute('data-confirmed') == '1'
                assert row.locator('[data-row-state]').inner_text().strip() == '✓'
                assert row.locator('[data-row-state]').is_disabled()
            assert page.locator('#pendingCount').inner_text().strip() == '0'

            review.click()
            wait_review_state(page, True)
            assert review.get_attribute('aria-pressed') == 'true'

            # Undoing stage 1 must NOT undo fixed amount confirmations.
            review.click()
            wait_review_state(page, False)
            assert review.get_attribute('aria-pressed') == 'false'
            for i in range(2):
                row = rows.nth(i)
                assert row.get_attribute('data-confirmed') == '1'
                assert row.locator('[data-row-state]').inner_text().strip() == '✓'
                assert row.locator('[data-row-state]').is_disabled()
            assert page.locator('#pendingCount').inner_text().strip() == '0'

            with db() as conn:
                entries = conn.execute(
                    '''SELECT pe.service_id,pe.confirmed,pe.source
                       FROM payment_entries pe JOIN services s ON s.id=pe.service_id
                       WHERE s.customer_id=? AND pe.period=? ORDER BY pe.service_id''',
                    (cid, period),
                ).fetchall()
                assert len(entries) == 2
                assert all(int(row['confirmed']) == 1 for row in entries)
                assert all(row['source'] != 'fixed_review_reset' for row in entries)

            # Automatic confirmation survives reload and stage 1 remains immediately available.
            page.reload(wait_until='networkidle')
            page.wait_for_timeout(1100)
            rows = page.locator('[data-payment-row]')
            for i in range(2):
                assert rows.nth(i).get_attribute('data-confirmed') == '1'
                assert rows.nth(i).locator('[data-row-state]').inner_text().strip() == '✓'
            review = page.locator('[data-v031-flow-action="review"]')
            assert review.is_enabled()

            review.click()
            wait_review_state(page, True)
            assert review.get_attribute('aria-pressed') == 'true'
            for i in range(2):
                assert rows.nth(i).get_attribute('data-confirmed') == '1'

            browser.close()
        print('v0.3.1 fixed amount auto-confirm acceptance passed (isolated test database)')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
