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
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v031-legacy-')
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
from app.v03_routes import _ensure_v03  # noqa: E402
from app.v031_payment_workflow_routes import ensure_v031  # noqa: E402


def seed():
    init_db()
    now = now_iso()
    period = current_period()
    with db() as conn:
        cid = int(conn.execute(
            'INSERT INTO customers(name,group_code,payment_enabled,notified,completed,payment_period,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
            ('历史迁移客户', 'LEGACY', 1, 1, 0, period, now, now),
        ).lastrowid)
        sid = int(conn.execute(
            '''INSERT INTO services
               (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
                payment_cycle,payment_interval_months,active_from_period,sort_order,source_row,payment_method)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (cid, '成员', '历史成员', '13800009999', 'A-LEGACY', 88, 0,
             '1个月', 1, period, 10, 1, '微信'),
        ).lastrowid)
        conn.execute(
            'INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at) VALUES(?,?,?,?,?)',
            (sid, '1900-01', 'variable', 0, now),
        )
        conn.execute(
            '''INSERT INTO payment_entries(service_id,period,amount,reference_amount,source,confirmed,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?)''',
            (sid, period, 88, 88, 'manual', 1, now, now),
        )
        rid = int(conn.execute(
            '''INSERT INTO customer_payment_runs(customer_id,period,notified_at,paid_at,created_at,updated_at)
               VALUES(?,?,?,?,?,?)''',
            (cid, period, now, '', now, now),
        ).lastrowid)
        _ensure_v03(conn)
        conn.execute('UPDATE customer_payment_runs SET emailed_at=? WHERE id=?', (now, rid))
        ensure_v031(conn)
        migrated = conn.execute(
            'SELECT reviewed_at,notified_at,initiated_at,paid_at FROM customer_payment_runs WHERE id=?',
            (rid,),
        ).fetchone()
        assert migrated['reviewed_at']
        assert migrated['notified_at']
        assert migrated['initiated_at']
        assert not migrated['paid_at']
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


def accept_next_dialog(page):
    page.once('dialog', lambda dialog: dialog.accept())


def wait_stage(page, action: str, pressed: bool):
    wanted = 'true' if pressed else 'false'
    page.wait_for_function(
        "args => document.querySelector(`[data-v031-flow-action=\"${args.action}\"]`)?.getAttribute('aria-pressed') === args.wanted",
        {'action': action, 'wanted': wanted},
        timeout=5000,
    )


def main():
    cid, token = seed()
    assert TEST_DB.resolve() != (ROOT / 'data' / 'app.db').resolve()
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8137'],
        cwd=ROOT,
        env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8137/health')
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1500, 'height': 1000})
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8137'}])
            page = context.new_page()
            page.goto(f'http://127.0.0.1:8137/customers/{cid}', wait_until='networkidle')
            page.wait_for_timeout(1250)

            root = page.locator('.v0211-workspace')
            assert root.get_attribute('data-v031-workflow-ready') == '1'
            flow = page.locator('[data-v031-payment-flow]')
            labels = [x.strip() for x in flow.locator('[data-v031-flow-action]').all_inner_texts()]
            assert labels == ['✓ 1 金额核对', '✓ 2 通知客户', '✓ 3 发起缴费', '4 完成缴费'], labels

            amount = page.locator('.quick-amount').first
            assert not bool(amount.evaluate('el => el.readOnly'))

            initiate = flow.locator('[data-v031-flow-action="initiate"]')
            notify = flow.locator('[data-v031-flow-action="notify"]')
            review = flow.locator('[data-v031-flow-action="review"]')
            assert initiate.is_enabled()

            accept_next_dialog(page)
            initiate.click()
            wait_stage(page, 'initiate', False)
            assert initiate.get_attribute('aria-pressed') == 'false'
            page.wait_for_function(
                "() => !document.querySelector('[data-v031-flow-action=\"notify\"]')?.disabled",
                timeout=5000,
            )
            assert notify.is_enabled()

            accept_next_dialog(page)
            notify.click()
            wait_stage(page, 'notify', False)
            assert notify.get_attribute('aria-pressed') == 'false'
            page.wait_for_function(
                "() => !document.querySelector('[data-v031-flow-action=\"review\"]')?.disabled",
                timeout=5000,
            )
            assert review.is_enabled()

            review.click()
            wait_stage(page, 'review', False)
            assert review.get_attribute('aria-pressed') == 'false'

            browser.close()
        print('v0.3.1 legacy-customer runtime ownership acceptance passed (isolated test database)')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
