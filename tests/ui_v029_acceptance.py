from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from datetime import date
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
from app.payment_v02 import current_period  # noqa: E402
from app.security import create_session  # noqa: E402


def seed():
    init_db()
    now = now_iso()
    period = current_period()
    with db() as conn:
        cid = int(conn.execute(
            'INSERT INTO customers (name,group_code,tax_id,payment_enabled,created_at,updated_at) VALUES(?,?,?,?,?,?)',
            ('v029验收客户', 'V029', 'V029-TAX', 1, now, now),
        ).lastrowid)
        sid = int(conn.execute(
            '''INSERT INTO services
               (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
                payment_cycle,payment_interval_months,active_from_period,sort_order,source_row,
                payment_method,invoice_type,package_type,notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (cid, '成员', '后勤', '13800139029', '5338000029029', 99, 0,
             '1个月', 1, period, 10, 1, '转账', '增值税', '测试套餐', '较长备注内容'),
        ).lastrowid)
        conn.execute(
            'INSERT INTO service_payment_rules (service_id,effective_period,mode,fixed_amount,created_at) VALUES(?,?,?,?,?)',
            (sid, '1900-01', 'variable', 0, now),
        )
        pid = int(conn.execute(
            '''INSERT INTO promotions(service_id,name,start_date,expiry_date,remind_days,status,notes,created_at)
               VALUES(?,?,?,?,?,?,?,?)''',
            (sid, '原优惠', '', date.today().isoformat(), 60, 'active', '优惠备注', now),
        ).lastrowid)
    token, _, _ = create_session()
    return cid, sid, pid, token


def wait_http(url: str):
    for _ in range(80):
        try:
            if urllib.request.urlopen(url, timeout=1).status == 200:
                return
        except Exception:
            pass
        time.sleep(.2)
    raise RuntimeError('server start failed')


def main():
    cid, sid, pid, token = seed()
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8126'],
        cwd=ROOT,
        env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8126/health')
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8126'}])
            page = context.new_page()

            page.goto(f'http://127.0.0.1:8126/customers/{cid}', wait_until='networkidle')
            assert page.locator('.v029-workspace').count() == 1
            assert page.locator('[data-payment-row] .dense-id span').count() == 0, 'payment number/account still show small labels'
            assert page.locator('[data-customer-panel="payment"] .hint').count() == 0, 'payment instruction text remains'

            page.locator('[data-customer-tab="services"]').click()
            panel = page.locator('[data-customer-panel="services"]')
            assert panel.is_visible()
            assert panel.locator('.hint').count() == 0, 'business instruction text remains'
            row = panel.locator('[data-business-row]').first
            box = row.bounding_box(); assert box and box['height'] <= 58, box
            line = row.locator('.business-row-line-v029'); assert line.count() == 1
            grid = row.locator('[data-business-attrs]')
            styles = grid.evaluate("el => ({display:getComputedStyle(el).display, overflow:getComputedStyle(el).overflowX, wrap:getComputedStyle(el).flexWrap})")
            assert styles['display'] == 'flex' and styles['wrap'] == 'nowrap', styles
            first_labels = [x.strip() for x in row.locator('.business-attribute small').all_inner_texts()[:4]]
            assert first_labels[:3] == ['类型', '姓名/属性', '号码'], first_labels

            panel.locator('[data-open-service-editor]').first.click()
            dialog = page.locator('#businessAttributeDialog'); dialog.wait_for(state='visible')
            assert dialog.locator('.global-attribute-row-v028').count() >= 10, 'complete business attributes missing'
            promo_section = dialog.locator('[data-service-promotions-editor]'); assert promo_section.count() == 1
            promo_rows = promo_section.locator('.editor-promo-row-v029')
            promo_rows.first.wait_for(state='visible')
            assert promo_rows.count() == 1
            assert promo_rows.first.locator('.editor-promo-name-v029').input_value() == '原优惠'
            assert promo_rows.first.locator('.editor-promo-notes-v029').input_value() == '优惠备注'

            promo_rows.first.locator('.editor-promo-name-v029').fill('已修改优惠')
            promo_rows.first.locator('.editor-promo-expiry-v029').fill('2026/12/01')
            promo_rows.first.locator('[data-editor-promo-save]').click()
            page.wait_for_timeout(300)
            assert promo_rows.first.locator('.editor-promo-name-v029').input_value() == '已修改优惠'

            promo_section.locator('[data-add-editor-promotion]').click()
            rows = promo_section.locator('.editor-promo-row-v029'); assert rows.count() == 2
            new = rows.last
            new.locator('.editor-promo-name-v029').fill('新增优惠')
            new.locator('.editor-promo-expiry-v029').fill('2027/01/01')
            new.locator('.editor-promo-notes-v029').fill('新增备注')
            new.locator('[data-editor-promo-save]').click()
            page.wait_for_timeout(300)
            assert new.get_attribute('data-promo-id') not in ('', None)

            dialog.locator('[data-business-editor-close]').first.click(); dialog.wait_for(state='hidden')
            page.locator('[data-customer-tab="promotions"]').click()
            promo_panel = page.locator('[data-customer-panel="promotions"]')
            assert promo_panel.locator('.hint').count() == 0, 'promotion instruction text remains'

            browser.close()

        with db() as conn:
            row = conn.execute('SELECT name,expiry_date,notes FROM promotions WHERE id=?', (pid,)).fetchone()
            assert row['name'] == '已修改优惠' and row['expiry_date'] == '2026-12-01'
            count = conn.execute("SELECT COUNT(*) n FROM promotions WHERE service_id=? AND status='active'", (sid,)).fetchone()['n']
            assert count == 2, count
        print('v0.2.9 density and complete editor acceptance passed')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
