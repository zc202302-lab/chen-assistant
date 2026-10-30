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

os.environ.setdefault('APP_USERNAME', 'ui-test')
os.environ.setdefault('APP_PASSWORD_SALT', 'dGVzdHNhbHQ=')
os.environ.setdefault('APP_PASSWORD_HASH', 'not-used-by-this-test')
os.environ.setdefault('APP_SESSION_SECRET', 'ui-test-session-secret')
os.environ.setdefault('APP_ENCRYPTION_KEY', 'not-used-by-this-test')
os.environ.setdefault('APP_SECURE_COOKIE', '0')

from app.db import db, init_db, now_iso  # noqa: E402
from app.payment_v02 import current_period  # noqa: E402
from app.security import create_session  # noqa: E402


def month_add(d: date, months: int) -> date:
    idx = d.year * 12 + d.month - 1 + months
    year, month0 = divmod(idx, 12)
    return date(year, month0 + 1, 15)


def add_customer(conn, name: str, suffix: int):
    now = now_iso(); period = current_period()
    cid = int(conn.execute(
        'INSERT INTO customers (name,group_code,tax_id,payment_enabled,created_at,updated_at) VALUES(?,?,?,?,?,?)',
        (name, f'C000{suffix}', f'TEST-TAX-{suffix}', 1, now, now),
    ).lastrowid)
    service_ids = []
    for idx, amount in enumerate((100, 200), 1):
        sid = int(conn.execute(
            '''INSERT INTO services
               (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
                payment_cycle,payment_interval_months,active_from_period,sort_order,source_row,payment_method)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (cid, '成员', f'测试{idx}', f'1380000{suffix:02d}{idx:03d}', f'5338000{suffix:02d}{idx:03d}',
             amount, 0, '1个月', 1, period, idx * 10, idx, '微信'),
        ).lastrowid)
        service_ids.append(sid)
        conn.execute(
            'INSERT INTO service_payment_rules (service_id,effective_period,mode,fixed_amount,created_at) VALUES(?,?,?,?,?)',
            (sid, '1900-01', 'variable', 0, now),
        )
    return cid, service_ids


def seed():
    init_db(); now = now_iso()
    with db() as conn:
        c1, services = add_customer(conn, 'UI测试客户A', 1)
        c2, _ = add_customer(conn, 'UI测试客户B', 2)
        for name, expiry in (
            ('已到期优惠', date.today().isoformat()),
            ('即将到期优惠', month_add(date.today(), 2).isoformat()),
            ('后续优惠不显示', month_add(date.today(), 4).isoformat()),
        ):
            conn.execute(
                '''INSERT INTO promotions(service_id,name,start_date,expiry_date,remind_days,status,notes,created_at)
                   VALUES(?,?,?,?,?,?,?,?)''',
                (services[0], name, '', expiry, 60, 'active', '', now),
            )
    token, _, _ = create_session()
    return c1, c2, token


def wait_http(url: str, timeout: float = 15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as r:
                if r.status == 200:
                    return
        except Exception:
            pass
        time.sleep(.2)
    raise RuntimeError('server did not start')


def column_width(page, key: str) -> float:
    box = page.locator(f'[data-payment-column-head][data-payment-attr-key="{key}"]').bounding_box()
    assert box and box['width'] > 0, (key, box)
    return float(box['width'])


def near(a: float, b: float, tol: float, msg: str):
    assert abs(a - b) <= tol, f'{msg}: {a} vs {b}'


def clipboard(page):
    return page.evaluate('navigator.clipboard.readText()')


def main():
    cid, cid2, token = seed()
    server = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8123'],
        cwd=ROOT, env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        wait_http('http://127.0.0.1:8123/health')
        from playwright.sync_api import sync_playwright
        page_errors = []
        request_failures = []
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.grant_permissions(['clipboard-read', 'clipboard-write'], origin='http://127.0.0.1:8123')
            context.add_cookies([{'name':'session_token','value':token,'url':'http://127.0.0.1:8123'}])
            page = context.new_page()
            page.on('pageerror', lambda exc: page_errors.append(str(exc)))
            page.on('requestfailed', lambda req: request_failures.append(f'{req.method} {req.url}: {req.failure}'))

            page.goto(f'http://127.0.0.1:8123/customers/{cid}', wait_until='networkidle')
            assert page.locator('.v0211-workspace').count() == 1
            hrefs = page.locator('link[rel="stylesheet"]').evaluate_all("els=>els.map(x=>x.getAttribute('href'))")
            css_names = [x.split('?',1)[0].rsplit('/',1)[-1] for x in hrefs]
            assert css_names == ['app.css','v028.css','layout-refinement.css'], css_names

            header_box = page.locator('.v0211-payment-header').bounding_box()
            first_row_box = page.locator('[data-payment-row]').first.bounding_box()
            assert header_box and first_row_box
            assert header_box['y'] + header_box['height'] <= first_row_box['y'] + 2

            # 常用复制仍然工作。
            hero_copies = page.locator('.v023-profile-card .copy-btn')
            for i, value in enumerate(['UI测试客户A', 'C0001', 'TEST-TAX-1']):
                hero_copies.nth(i).click(); page.wait_for_timeout(60)
                assert clipboard(page) == value
                assert page.locator('.app-toast.show').count() == 1

            # 动态缴费列默认五列，且“金额”已经正式更名为“本月缴费”。
            labels = [x.strip() for x in page.locator('[data-payment-column-head] > span').all_inner_texts()]
            assert labels == ['类型','姓名/属性','号码','账号','本月缴费'], labels
            assert page.locator('[data-resize-payment-col]').count() == 5
            assert page.locator('#displayAttributeDialog').count() == 0
            assert page.locator('#paymentColumnsDialog').count() == 1

            # 号码/账号复制仍不抢走正在输入本月缴费的焦点。
            first_payment = page.locator('[data-payment-row]').first
            amount = first_payment.locator('.quick-amount')
            amount.click()
            ids = first_payment.locator('.identifier-copy')
            assert ids.count() == 2
            for i in range(2):
                value = ids.nth(i).get_attribute('data-copy')
                ids.nth(i).click(); page.wait_for_timeout(60)
                assert clipboard(page) == value
                assert amount.evaluate('el => document.activeElement === el')

            # 动态列宽可独立调整、按客户保存，并且不泄漏到另一个客户。
            before = column_width(page, 'number')
            type_before = column_width(page, 'service_type')
            handle = page.locator('[data-resize-payment-col="number"]').first
            box = handle.bounding_box(); assert box and box['width'] >= 16
            x, y = box['x'] + box['width']/2, box['y'] + box['height']/2
            page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x + 90, y, steps=8); page.mouse.up()
            page.wait_for_timeout(550)
            after = column_width(page, 'number')
            assert after >= before + 55, (before, after)
            near(column_width(page, 'service_type'), type_before, 4, 'resizing number changed another column')
            page.reload(wait_until='networkidle')
            near(column_width(page, 'number'), after, 4, 'dynamic payment width did not persist')
            page.goto(f'http://127.0.0.1:8123/customers/{cid2}', wait_until='networkidle')
            near(column_width(page, 'number'), before, 5, 'dynamic width leaked to another customer')

            # 客户各模块仍然保持单面板切换。
            page.goto(f'http://127.0.0.1:8123/customers/{cid}', wait_until='networkidle')
            for tab in ('services','promotions','contacts','tasks','visits','payment'):
                page.locator(f'[data-customer-tab="{tab}"]').click(); page.wait_for_timeout(60)
                assert page.locator(f'[data-customer-panel="{tab}"]').is_visible()
                assert page.locator('[data-customer-panel]:visible').count() == 1

            # 业务完整编辑器与全局属性模板仍可正常新增并保存。
            page.locator('[data-customer-tab="services"]').click()
            page.locator('[data-customer-panel="services"] [data-open-service-editor]').first.click()
            dialog = page.locator('#businessAttributeDialog'); dialog.wait_for(state='visible')
            page.locator('[data-add-global-attribute]').click()
            row = page.locator('.global-attribute-row-v028').last
            row.locator('.attr-label').fill('全局测试属性')
            row.locator('.attr-value').fill('A值')
            page.locator('[data-business-attribute-form] button[type="submit"]').click()
            dialog.wait_for(state='hidden')
            assert page.locator('.business-attribute').filter(has_text='A值').count() >= 1

            # 优惠继续保持两列、复制和后续优惠过滤。
            page.locator('[data-customer-tab="promotions"]').click()
            cols = page.locator('.promo-column-v028'); assert cols.count() == 2
            left, right = cols.nth(0).bounding_box(), cols.nth(1).bounding_box()
            assert left and right and right['x'] > left['x'] + left['width'] * .65
            assert page.get_by_text('后续优惠不显示', exact=True).count() == 0
            number_btn = page.locator('.promo-number-copy-v028').first
            number = number_btn.get_attribute('data-copy-silent')
            number_btn.click(); page.wait_for_timeout(70); assert clipboard(page) == number
            name_btn = page.locator('.promo-name-copy-v028').first
            promo_name = name_btn.get_attribute('data-copy-silent')
            name_btn.click(); page.wait_for_timeout(70); assert clipboard(page) == promo_name

            page.goto('http://127.0.0.1:8123/?home=promos', wait_until='networkidle')
            assert page.locator('[data-home-panel="promos"]').is_visible()
            home_cols = page.locator('.home-promo-column-v030'); assert home_cols.count() == 2
            assert page.locator('.home-promo-column-v030.state-expired').get_by_text('UI测试客户A', exact=True).count() == 1
            assert page.locator('.home-promo-column-v030.state-soon').get_by_text('UI测试客户A', exact=True).count() == 1
            browser.close()

        assert not page_errors, 'browser page errors: ' + ' | '.join(page_errors)
        assert not request_failures, 'browser request failures: ' + ' | '.join(request_failures)
        print('UI acceptance passed')
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == '__main__':
    main()
