"""Real browser coverage for sparse overview, double-click edits and copy details."""
from datetime import date
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

from promotion_slots_contract import ROOT, seed, db, xlsx_rows
from playwright.sync_api import sync_playwright, expect


def main():
    cid, ids, _, token, _ = seed()
    long_name = '完整优惠内容-含中文与符号<测试>/' + '长内容' * 40
    with db() as conn:
        pid = conn.execute('INSERT INTO promotions(service_id,name,expiry_date,status,slot_number) VALUES(?,?,?,?,?)',
                           (ids[0], long_name, date.today().isoformat(), 'active', 2)).lastrowid
        conn.execute('INSERT INTO promotions(service_id,name,expiry_date,status,slot_number) VALUES(?,?,?,?,?)',
                     (ids[1], '排序在前优惠', date.today().isoformat(), 'active', 5))
    server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8792'],
                              cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen('http://127.0.0.1:8792/health', timeout=1)
                break
            except Exception:
                time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width':1440, 'height':1000}, accept_downloads=True,
                                          permissions=['clipboard-read', 'clipboard-write'])
            context.add_cookies([{'name':'session_token', 'value':token, 'url':'http://127.0.0.1:8792'}])
            page = context.new_page()
            page.goto(f'http://127.0.0.1:8792/customers/{cid}?tab=promotions', wait_until='networkidle')
            full = page.locator('[data-full-promotions]')
            assert not full.evaluate('(el)=>el.open')
            full.locator('summary').click()
            table = full.locator('table')
            expect(table.locator('tbody tr')).to_have_count(2)
            def cells():
                return table.locator('tr').evaluate_all('(rows)=>rows.map(row=>[...row.querySelectorAll("th,td")].map(cell=>cell.textContent))')
            values = cells()
            assert [r[0] for r in values[1:]] == ['13800000002', '001234567890123456789']
            assert values[2][1:3] == ['', ''] and values[2][3] == long_name
            widths = table.locator('thead th').evaluate_all('(els)=>els.map(el=>el.getBoundingClientRect().width)')
            assert max(widths)-min(widths)<1
            content = table.locator('tbody tr').nth(1).locator('td').nth(3).locator('span')
            assert content.evaluate('(el)=>el.scrollWidth>el.clientWidth && getComputedStyle(el).textOverflow==="ellipsis"')
            assert table.locator('tbody td').first.evaluate('(el)=>getComputedStyle(el).textAlign') == 'center'
            assert table.locator('tbody tr').first.bounding_box()['height'] <= 31
            with page.expect_download() as download:
                full.locator('a[download]').click()
            assert xlsx_rows(Path(download.value.path()).read_bytes()) == values

            table.locator(f'[data-service-id="{ids[0]}"]').dblclick()
            dialog = page.locator('#businessAttributeDialog')
            expect(dialog).to_be_visible()
            expect(dialog.locator(f'[data-promo-id="{pid}"]')).to_be_visible()
            dialog.locator('[data-key="number"] .attr-value').fill('0088888888888')
            dialog.locator('[data-key="holder_name"] .attr-value').fill('全局同步属性')
            with page.expect_response(lambda r:'/status-v03' in r.url and r.request.method=='POST'):
                dialog.locator('[data-business-attribute-form] button[type="submit"]').click()
            full = page.locator('[data-full-promotions]')
            table = full.locator('table')
            assert full.evaluate('(el)=>el.open')
            expect(table.locator(f'[data-service-id="{ids[0]}"]')).to_have_text('0088888888888')
            number = page.locator(f'.promo-number-copy-v028[data-service-id="{ids[0]}"]')
            expect(number.locator('strong')).to_have_text('0088888888888')
            expect(number.locator('small')).to_contain_text('全局同步属性')

            name = page.locator(f'[data-promo-id="{pid}"] .promo-name-copy-v028')
            name.click()
            popover = page.locator('#promotionContentPopover')
            expect(popover).to_be_visible()
            expect(popover).to_have_text(long_name)
            assert page.evaluate('navigator.clipboard.readText()') == long_name
            name.click(); expect(popover).to_be_hidden()
            name.click(); expect(popover).to_be_visible()
            page.locator('[data-full-promotions] summary').click(); expect(popover).to_be_hidden()
            name.click(); expect(popover).to_be_visible()
            page.keyboard.press('Escape'); expect(popover).to_be_hidden()
            # Keep the previously supported double-click inline rename.
            name.dblclick()
            inline = page.locator('.promo-name-inline-edit-v030')
            expect(inline).to_be_visible(); inline.press('Escape')
            number.dblclick()
            expect(dialog).to_be_visible()
            expect(dialog.locator('[data-key="number"] .attr-value')).to_have_value('0088888888888')
            dialog.locator('[data-key="account"] .attr-value').fill('同步账号')
            with page.expect_response(lambda r:'/status-v03' in r.url and r.request.method=='POST'):
                dialog.locator('[data-business-attribute-form] button[type="submit"]').click()
            page.locator('[data-customer-tab="payment"]').click()
            expect(page.locator(f'[data-payment-row][data-service-id="{ids[0]}"]')).to_contain_text('0088888888888')
            page.locator('[data-customer-tab="services"]').click()
            expect(page.locator(f'[data-business-row][data-service-id="{ids[0]}"]')).to_contain_text('全局同步属性')
            page.locator('[data-customer-tab="promotions"]').click()
            full = page.locator('[data-full-promotions]')
            if not full.evaluate('(el)=>el.open'): full.locator('summary').click()
            with page.expect_download() as download:
                full.locator('a[download]').click()
            assert xlsx_rows(Path(download.value.path()).read_bytes()) == cells()
            out=ROOT/'artifacts/number-inbox-batch'; out.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(out/'promotion-overview-desktop.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(out/'promotion-overview-mobile.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            # Narrow screen full-content box stays inside viewport.
            page.locator(f'[data-promo-id="{pid}"] .promo-name-copy-v028').click()
            expect(popover).to_be_visible()
            box=popover.bounding_box(); assert box['x']>=0 and box['x']+box['width']<=391
            with db() as conn:
                service=conn.execute('SELECT number,account,holder_name FROM services WHERE id=?',(ids[0],)).fetchone()
                assert tuple(service)==('0088888888888','同步账号','全局同步属性')
            browser.close()
        print('promotion overview acceptance passed: filtering, clipping, equal widths, copy details, both editors, global sync and XLSX parity')
    finally:
        server.terminate(); server.wait(timeout=10)


if __name__=='__main__':
    main()
