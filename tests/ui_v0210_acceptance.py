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
            ('v0210同步验收客户', 'SYNC210', 'SYNC210-TAX', 1, now, now),
        ).lastrowid)
        sid = int(conn.execute(
            '''INSERT INTO services
               (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
                payment_cycle,payment_interval_months,active_from_period,sort_order,source_row,
                payment_method,invoice_type,package_type,notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (cid, '成员', '后勤', '13800130210', '5338000020210', 88, 0,
             '1个月', 1, period, 10, 1, '微信', '普票', '同步套餐', '同步备注'),
        ).lastrowid)
        conn.execute(
            'INSERT INTO service_payment_rules (service_id,effective_period,mode,fixed_amount,created_at) VALUES(?,?,?,?,?)',
            (sid, '1900-01', 'variable', 0, now),
        )
        pid = int(conn.execute(
            '''INSERT INTO promotions(service_id,name,start_date,expiry_date,remind_days,status,notes,created_at)
               VALUES(?,?,?,?,?,?,?,?)''',
            (sid, '双击修改优惠', '', date.today().isoformat(), 60, 'active', '同步备注', now),
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


def selection(page, locator):
    return locator.evaluate('el => [el.selectionStart, el.selectionEnd, el.value.length]')


def main():
    cid, sid, pid, token = seed()
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8127'],
        cwd=ROOT,
        env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8127/health')
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8127'}])
            context.grant_permissions(['clipboard-read', 'clipboard-write'], origin='http://127.0.0.1:8127')
            page = context.new_page()
            page.goto(f'http://127.0.0.1:8127/customers/{cid}?tab=services', wait_until='networkidle')

            # 业务页属性名称只显示在统一表头；每行属性值可点击复制。
            header = page.locator('[data-business-table-header]')
            header.wait_for(state='visible')
            labels = [x.strip() for x in header.locator('.business-table-header-cell-v030').all_inner_texts()[:5]]
            assert labels == ['类型', '姓名/属性', '号码', '账号', '缴费周期（月）'], labels
            row = page.locator('[data-business-row]').first
            assert row.locator('.business-attribute small').first.evaluate("el => getComputedStyle(el).display") == 'none'
            first_value = row.locator('.business-attribute').first
            first_value.click()
            page.wait_for_timeout(100)
            assert page.evaluate('navigator.clipboard.readText()') == '成员'

            # 全局属性名称改变后，业务表头无需刷新页面就同步变化。
            row.locator('[data-open-service-editor]').click()
            dialog = page.locator('#businessAttributeDialog'); dialog.wait_for(state='visible')
            first_label = dialog.locator('.global-attribute-row-v028 .attr-label').first

            # 所有手动输入框：第一次单击全选；第二次单击取消全选，可局部编辑。
            first_label.click()
            s1 = selection(page, first_label)
            assert s1[0] == 0 and s1[1] == s1[2], s1
            first_label.click(position={'x': max(5, (first_label.bounding_box() or {'width':80})['width'] * .7), 'y': 10})
            s2 = selection(page, first_label)
            assert s2[0] == s2[1], s2

            first_label.fill('业务类型')
            dialog.locator('button[type="submit"]').click()
            dialog.wait_for(state='hidden')
            page.wait_for_timeout(150)
            assert header.locator('.business-table-header-cell-v030').first.inner_text().strip() == '业务类型'

            # 优惠名称：单击复制，双击就地修改。
            page.locator('[data-customer-tab="promotions"]').click()
            promo_btn = page.locator(`[data-promo-item][data-promo-id="{pid}"] .promo-name-copy-v028`)
            promo_btn.wait_for(state='visible')
            promo_btn.click()
            page.wait_for_timeout(360)
            assert page.evaluate('navigator.clipboard.readText()') == '双击修改优惠'

            promo_btn.dblclick()
            inline = page.locator(`[data-promo-item][data-promo-id="{pid}"] .promo-name-inline-edit-v030`)
            inline.wait_for(state='visible')
            inline.fill('优惠页改名')
            inline.press('Enter')
            page.locator(`[data-promo-item][data-promo-id="{pid}"] .promo-name-copy-v028`).wait_for(state='visible')
            assert page.locator(`[data-promo-item][data-promo-id="{pid}"] .promo-name-copy-v028 strong`).inner_text() == '优惠页改名'

            # 从优惠工作区修改后，业务完整信息编辑器读取同一条 promotions 主数据。
            page.locator('[data-customer-tab="services"]').click()
            page.locator('[data-business-row] [data-open-service-editor]').click()
            dialog.wait_for(state='visible')
            promo_name = dialog.locator(`.editor-promo-row-v029[data-promo-id="{pid}"] .editor-promo-name-v029`)
            promo_name.wait_for(state='visible')
            assert promo_name.input_value() == '优惠页改名'

            # 反向修改：业务完整信息里的优惠名称保存后，隐藏的优惠工作区 DOM 同步更新。
            promo_name.fill('业务页改名')
            dialog.locator(`.editor-promo-row-v029[data-promo-id="{pid}"] [data-editor-promo-save]`).click()
            page.wait_for_timeout(200)
            dialog.locator('[data-business-editor-close]').first.click()
            dialog.wait_for(state='hidden')
            page.locator('[data-customer-tab="promotions"]').click()
            assert page.locator(`[data-promo-item][data-promo-id="{pid}"] .promo-name-copy-v028 strong`).inner_text() == '业务页改名'

            browser.close()

        with db() as conn:
            name = conn.execute('SELECT name FROM promotions WHERE id=?', (pid,)).fetchone()['name']
            assert name == '业务页改名', name
        print('v0.2.10 interaction and synchronization acceptance passed')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
