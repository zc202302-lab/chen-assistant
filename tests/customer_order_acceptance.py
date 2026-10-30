"""Real mouse/touch card sorting, reload, cancellation, failure rollback and links."""
import os
import subprocess
import sys
import time
import urllib.request
from customer_order_contract import ROOT, seed, create_session, order


def main():
    seed()
    token, _, _ = create_session()
    base = 'http://127.0.0.1:8184'
    server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8184'], cwd=ROOT, env=os.environ.copy(), stdout=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + '/health', timeout=1)
                break
            except OSError:
                time.sleep(.2)
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for width in (1440, 390):
                context = browser.new_context(viewport={'width':width, 'height':1000}, has_touch=width == 390)
                context.add_cookies([{'name':'session_token', 'value':token, 'url':base}])
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base + '/customers', wait_until='networkidle')
                rows = page.locator('[data-customer-order-id]')
                def ids():
                    return rows.evaluate_all('els => els.map(el => Number(el.dataset.customerOrderId))')
                before = ids()
                handle = rows.first.locator('.customer-sort-handle')
                handle.scroll_into_view_if_needed()
                start = handle.bounding_box()
                target = rows.nth(2).bounding_box()
                x, y = start['x']+18, start['y']+20
                tx, ty = target['x']+target['width']/2, target['y']+target['height']/2
                with page.expect_response(lambda r: r.url.endswith('/customers/order') and r.request.method == 'POST') as saved:
                    if width == 1440:
                        page.mouse.move(x, y); page.mouse.down()
                        page.mouse.move(tx, ty, steps=20); page.mouse.up()
                    else:
                        cdp = context.new_cdp_session(page)
                        cdp.send('Input.dispatchTouchEvent', {'type':'touchStart', 'touchPoints':[{'x':x, 'y':y, 'id':1}]})
                        for step in range(1, 13):
                            cdp.send('Input.dispatchTouchEvent', {'type':'touchMove', 'touchPoints':[{'x':x+(tx-x)*step/12, 'y':y+(ty-y)*step/12, 'id':1}]})
                        cdp.send('Input.dispatchTouchEvent', {'type':'touchEnd', 'touchPoints':[]})
                assert saved.value.ok
                expect(handle).to_be_enabled()
                assert ids() != before
                assert ids() == order()[0]
                page.reload(wait_until='networkidle')
                assert ids() == order()[0]
                # Keyboard reordering is available without dragging.
                before = ids()
                with page.expect_response('**/customers/order') as saved:
                    rows.first.locator('.customer-sort-handle').press('ArrowDown')
                assert saved.value.ok
                expect(page.locator('.customer-sort-handle').first).to_be_enabled()
                assert ids()[:2] == [before[1], before[0]]
                # Cancel a physical drag with Escape: no persistence.
                before = ids()
                a = rows.first.locator('.customer-sort-handle').bounding_box()
                b = rows.nth(1).bounding_box()
                page.mouse.move(a['x']+18,a['y']+20); page.mouse.down()
                page.mouse.move(b['x']+b['width']/2,b['y']+b['height']/2,steps=10)
                page.keyboard.press('Escape'); page.mouse.up()
                assert ids() == before and order()[0] == before
                # Failed persistence restores the original order and reports failure.
                page.route('**/customers/order', lambda route: route.fulfill(status=500, content_type='application/json', body='{"detail":"排序保存失败"}'))
                rows.first.locator('.customer-sort-handle').press('ArrowDown')
                expect(page.locator('.customer-order-status')).to_have_text('排序保存失败')
                assert ids() == before and order()[0] == before
                page.unroute('**/customers/order')
                # Filtering retains server order and card navigation remains a link.
                page.goto(base + '/customers?q=Alpha', wait_until='networkidle')
                expect(rows).to_have_count(1)
                expect(rows.locator('.customer-sort-handle')).to_be_visible()
                href = rows.locator('a.customer-card-v161').get_attribute('href')
                rows.locator('a.customer-card-v161').click()
                page.wait_for_url(base + href)
                page.goto(base + '/customers', wait_until='networkidle')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                out = ROOT / 'artifacts/customer-order'; out.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(out / f'customers-{width}.png'), full_page=True)
                assert not errors, errors
                context.close()
            browser.close()
        print('customer order browser passed: real mouse/touch, reload, keyboard, cancellation, failure rollback, navigation')
    finally:
        server.terminate(); server.wait(timeout=10)


if __name__ == '__main__':
    main()
