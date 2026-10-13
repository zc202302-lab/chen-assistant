"""Real business editor: free dates, override persistence and one-line status."""
from payment_next_date_contract import ROOT, db, init_db, now_iso, create_session, _template
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request


def main():
    init_db()
    with db() as conn:
        now = now_iso()
        cid = conn.execute('INSERT INTO customers(name,payment_enabled,created_at,updated_at) VALUES(?,1,?,?)', ('日期浏览器测试', now, now)).lastrowid
        sid = conn.execute('''INSERT INTO services(customer_id,service_type,number,payment_interval_months,payment_cycle,last_payment_date,monthly_fee,fixed_fee)
            VALUES(?,?,?,?,?,?,?,?)''', (cid, '成员', '15800000001', 12, '12个月', '2025-07-12', 20, 1)).lastrowid
        _template(conn)
    token, _, _ = create_session()
    base = 'http://127.0.0.1:8176'
    proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8176'], cwd=ROOT, env=os.environ.copy())
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + '/health', timeout=1)
                break
            except Exception:
                time.sleep(.2)
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width':1440, 'height':900})
            context.add_cookies([{'name':'session_token', 'value':token, 'url':base}])
            page = context.new_page()
            page.goto(base + f'/customers/{cid}?tab=services', wait_until='networkidle')
            page.locator('[data-customer-tab="services"]').click()
            page.locator(f'[data-business-row][data-service-id="{sid}"] .business-attribute').first.dblclick()
            dialog = page.locator('#businessAttributeDialog')
            expect(dialog).to_be_visible()
            next_date = dialog.locator('[data-key="next_payment_date"] .attr-value')
            last_date = dialog.locator('[data-key="last_payment_date"] .attr-value')
            expect(next_date).to_have_value('2026-07-12')
            next_date.fill('2030年10月12日')
            last_date.fill('日期待确认')
            last_date.press('Tab')
            expect(last_date).to_have_value('日期待确认')
            expect(next_date).to_have_value('2030年10月12日')
            assert last_date.evaluate('el => el.validity.valid')
            dialog.locator('.attribute-dialog-actions button[type="submit"]').click()
            expect(dialog).not_to_be_visible()
            page.reload(wait_until='networkidle')
            page.locator('[data-customer-tab="services"]').click()
            page.locator(f'[data-business-row][data-service-id="{sid}"] .business-attribute').first.dblclick()
            expect(next_date).to_have_value('2030年10月12日')
            expect(last_date).to_have_value('日期待确认')
            output = ROOT / 'artifacts' / 'list-compact'
            output.mkdir(parents=True, exist_ok=True)
            for width, height in [(1440,900), (390,844)]:
                page.set_viewport_size({'width':width, 'height':height})
                status = dialog.locator('[data-v03-business-status-panel]')
                heading = status.locator('.v03-business-status-head>b').bounding_box()
                state = status.locator('[data-v03-payment-state]').bounding_box()
                assert abs((heading['y'] + heading['height']/2) - (state['y'] + state['height']/2)) < 8
                value_width = dialog.locator('[data-key="number"] .attr-value').bounding_box()['width']
                assert value_width >= 125, value_width
                assert dialog.locator('[data-key="number"]').bounding_box()['height'] < 60
                page.screenshot(path=str(output / f'payment-attributes-{width}.png'))
            browser.close()
        print('payment date browser acceptance passed')
    finally:
        proc.terminate()
        proc.wait(timeout=10)


if __name__ == '__main__':
    main()
