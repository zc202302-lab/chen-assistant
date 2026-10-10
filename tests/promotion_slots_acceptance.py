"""Exercise the actual free-text editor, numbered ordering and compact overview."""
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from promotion_slots_contract import ROOT, seed, db, xlsx_rows
from playwright.sync_api import sync_playwright


def main():
    cid, ids, _, token, _ = seed()
    server = subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8791'],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen('http://127.0.0.1:8791/health',timeout=1)
                break
            except Exception:
                time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True)
            context.add_cookies([{'name':'session_token','value':token,'url':'http://127.0.0.1:8791'}])
            page = context.new_page()
            page.goto(f'http://127.0.0.1:8791/customers/{cid}?tab=services')
            with page.expect_response(lambda r:'/promotions-editor-v029' in r.url and r.request.method=='GET'):
                page.locator(f'[data-business-row][data-service-id="{ids[0]}"] [data-open-service-editor]').click()
            dialog = page.locator('#businessAttributeDialog')
            dialog.wait_for(state='visible')
            dialog.locator('.editor-promo-empty-v029').wait_for(state='visible')
            page.locator('[data-add-editor-promotion]').click()
            row = dialog.locator('.editor-promo-row-v029').last
            row.locator('.editor-promo-slot').fill('2')
            row.locator('.editor-promo-name-v029').fill('第二优惠')
            expiry=row.locator('.editor-promo-expiry-v029')
            expiry.fill('2026/1//2')
            expiry.press('End');expiry.press('Backspace');expiry.press('2')
            assert expiry.input_value()=='2026/1//2', 'manual slash editing was rewritten'
            with page.expect_response(lambda r:'/promotions-editor-v029' in r.url and r.request.method=='POST') as response:
                row.locator('[data-editor-promo-save]').click()
            assert response.value.ok, response.value.text()
            pid=response.value.json()['id']
            page.locator('[data-add-editor-promotion]').click()
            newrow=dialog.locator('.editor-promo-row-v029').last
            newrow.locator('.editor-promo-slot').fill('5')
            newrow.locator('.editor-promo-name-v029').fill('第五优惠')
            newrow.locator('.editor-promo-expiry-v029').fill('2027/3/4')
            with page.expect_response(lambda r:'/promotions-editor-v029' in r.url and r.request.method=='POST') as response:
                newrow.locator('[data-editor-promo-save]').click()
            assert response.value.ok
            row=dialog.locator(f'[data-promo-id="{pid}"]')
            row.locator('.editor-promo-slot').fill('4')
            with page.expect_response(lambda r:'/promotions-editor-v029' in r.url and r.request.method=='POST'):
                row.locator('[data-editor-promo-save]').click()
            page.wait_for_function("() => document.querySelector('.editor-promo-row-v029 .editor-promo-slot')?.value === '4'")
            assert dialog.locator('.editor-promo-slot').evaluate_all('(els)=>els.map(el=>el.value)')==['4','5']
            dialog.locator('[data-business-editor-close]').first.click()
            page.locator('[data-customer-tab="promotions"]').click()
            full=page.locator('[data-full-promotions]')
            assert not full.evaluate('(el)=>el.open')
            with page.expect_response(lambda r:r.url.endswith('/promotions/table')):
                full.locator('summary').click()
            table=full.locator('table')
            page.wait_for_function("() => document.querySelector('[data-full-promotions] tbody')?.textContent.includes('第二优惠')")
            def cells():
                return table.locator('tr').evaluate_all('(rows)=>rows.map(row=>[...row.querySelectorAll("th,td")].map(cell=>cell.textContent))')
            current=cells()
            assert len(current[0])==11 and current[2][1:7]==['']*6
            assert current[2][7:11]==['第二优惠','2026/1//2','第五优惠','2027/3/4']
            with page.expect_download() as download:
                full.locator('a[download]').click()
            assert xlsx_rows(Path(download.value.path()).read_bytes())==current
            assert table.locator('tbody td').first.evaluate('(el)=>parseFloat(getComputedStyle(el).paddingTop)')<=4
            out=ROOT/'data/ui-screenshots';out.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(out/'promotion-slots-desktop.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(out/'promotion-slots-mobile.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            page.reload()
            assert not page.locator('[data-full-promotions]').evaluate('(el)=>el.open')
            with db() as conn:
                stored=conn.execute('SELECT slot_number,expiry_date FROM promotions WHERE id=?',(pid,)).fetchone()
                assert stored['slot_number']==4 and stored['expiry_date']=='2026/1//2'
            browser.close()
        print('promotion slots browser acceptance passed: editing, sort, gaps, folding, Excel parity and mobile layout')
    finally:
        server.terminate();server.wait(timeout=10)

if __name__=='__main__':
    main()
