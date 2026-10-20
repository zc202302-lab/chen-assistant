"""Work entry grid, pointer reorder, cross-zone movement, cancel and persisted layout."""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from cryptography.fernet import Fernet
os.environ['APP_ENCRYPTION_KEY'] = Fernet.generate_key().decode()
from v162_number_inbox_contract import ROOT, create_session, db, init_db
from app.v162_number_inbox import ensure_number_inbox_schema


def main():
    init_db()
    with db() as conn:ensure_number_inbox_schema(conn)
    session, _, _ = create_session()
    base = 'http://127.0.0.1:8184'
    proc = subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8184'],cwd=ROOT,env=os.environ.copy())
    try:
        for _ in range(100):
            try:
                if urllib.request.urlopen(base+'/health',timeout=1).status == 200:break
            except Exception:pass
            time.sleep(.2)
        else:raise RuntimeError('server startup failed')
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser=p.chromium.launch()
            context=browser.new_context(viewport={'width':1440,'height':1000})
            context.add_cookies([{'name':'session_token','value':session,'url':base}])
            page=context.new_page(); errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(base+'/work',wait_until='networkidle')
            previews=ROOT/'artifacts'/'number-inbox-batch';previews.mkdir(parents=True,exist_ok=True)
            for width in [1440,768,390,320]:
                page.set_viewport_size({'width':width,'height':1000})
                tiles=page.locator('.work-entry-tile');expect(tiles).to_have_count(10)
                expect(page.locator('[data-entry-key=processes] a')).to_have_attribute('href', '/work/processes')
                boxes=[t.bounding_box() for t in tiles.all()]
                for box in boxes:assert box and abs(box['width']-box['height'])<2 and box['width']<=146
                assert len(set(round(b['width']) for b in boxes))==1
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
                h=page.locator('[data-history-nav]').bounding_box();r=page.locator('.reminder-entry').bounding_box();s=page.locator('.search-link').bounding_box()
                n=page.locator('.global-primary-nav').bounding_box();b=page.locator('[data-history-back]').bounding_box();f=page.locator('[data-history-forward]').bounding_box()
                assert b['x']+b['width']<=n['x'] and f['x']>=n['x']+n['width']
                assert abs(b['y']+b['height']/2-(n['y']+n['height']/2))<2
                assert abs(f['y']+f['height']/2-(n['y']+n['height']/2))<2
                page.screenshot(path=str(previews/f'work-entries-{width}.png'),full_page=True)
            page.set_viewport_size({'width':1440,'height':1000})
            page.get_by_role('button',name='编辑模块').click()
            expect(page.locator('[data-entry-handle]').first).to_be_visible()
            # Real pointer capture drag: move customer management to auxiliary.
            handle=page.locator('[data-entry-key=customers] [data-entry-handle]');a=handle.bounding_box()
            target=page.locator('[data-entry-key=products]');b=target.bounding_box()
            page.mouse.move(a['x']+a['width']/2,a['y']+a['height']/2);page.mouse.down()
            page.mouse.move(b['x']+8,b['y']+b['height']/2,steps=8);page.mouse.up()
            expect(page.locator('[data-entry-zone=auxiliary] [data-entry-key=customers]')).to_have_count(1)
            page.get_by_role('button',name='取消',exact=True).click()
            expect(page.locator('[data-entry-zone=common] [data-entry-key=customers]')).to_have_count(1)
            page.get_by_role('button',name='编辑模块').click()
            handle=page.locator('[data-entry-key=numbers] [data-entry-handle]')
            handle.focus();handle.press('Space');handle.press('ArrowLeft')
            expect(page.locator('[data-entry-zone=common] [data-entry-key=numbers]')).to_have_count(1)
            page.get_by_role('button',name='保存布局').click()
            expect(page.locator('[data-entry-feedback]')).to_have_text('布局已保存')
            page.reload(wait_until='networkidle')
            keys=page.locator('[data-entry-zone=common] [data-entry-key]').evaluate_all('(els)=>els.map(e=>e.dataset.entryKey)')
            assert keys==['customers','library','numbers','lists'],keys
            # Saved layout survives a fresh browser session.
            fresh=browser.new_context();fresh.add_cookies([{'name':'session_token','value':session,'url':base}])
            fresh_page=fresh.new_page();fresh_page.goto(base+'/work',wait_until='networkidle')
            assert fresh_page.locator('[data-entry-zone=common] [data-entry-key]').evaluate_all('(els)=>els.map(e=>e.dataset.entryKey)')==keys
            page.get_by_role('button',name='编辑模块').click()
            handle=page.locator('[data-entry-key=numbers] [data-entry-handle]');handle.focus();handle.press('ArrowLeft')
            page.route('**/work/entry-layout',lambda route:route.abort())
            page.get_by_role('button',name='保存布局').click()
            expect(page.get_by_role('button',name='保存布局')).to_be_enabled()
            expect(page.locator('[data-work-entries]')).to_have_class(__import__('re').compile('is-editing'))
            page.get_by_role('button',name='取消',exact=True).click()
            page.locator('[data-entry-key=numbers] a').click()
            expect(page).to_have_url(base+'/work/number-inbox')
            assert not errors,errors
            browser.close()
        print('work entry square grid, left header, pointer cross-zone drag, keyboard sorting, cancel, save failure and fresh-session persistence passed')
    finally:
        proc.terminate();proc.wait(timeout=10)


if __name__=='__main__':main()
