"""Real Chromium coverage of standalone enhancements without production data."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HTML = '''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/static/pwa-experience.css"></head><body data-pwa-scope="test-session"><nav class="bottom-nav"><a href="/customers/new">新建</a></nav><form method="get"><input name="q" id="serviceFilter"></form><form method="post" data-pwa-draft="customer" data-pwa-success="customer"><input name="name"><textarea name="note"></textarea><input type="hidden" name="csrf" value="fresh-csrf"><input type="hidden" name="revision" value="9"><input type="password" name="password"><input type="checkbox" name="pinned" value="1"><button type="submit">保存</button></form><div style="height:2000px"></div><script src="/static/pwa-experience.js"></script></body></html>'''

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path=self.path.split('?')[0]
        if path in ['/static/pwa-experience.js','/static/pwa-experience.css']:
            data=(ROOT/'app'/path.lstrip('/')).read_bytes()
            content='application/javascript' if path.endswith('.js') else 'text/css'
        else:
            data=HTML.encode();content='text/html; charset=utf-8'
        self.send_response(200);self.send_header('Content-Type',content);self.end_headers();self.wfile.write(data)
    def log_message(self,*args):
        pass


def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            normal=browser.new_page();normal.goto(base+'/customers/new')
            assert normal.locator('.pwa-draft-bar').count()==0
            assert normal.locator('html').get_attribute('class') is None
            normal.close()
            context=browser.new_context(viewport={'width':390,'height':844})
            context.add_init_script('''Object.defineProperty(navigator,'standalone',{value:true});
            window.testActivation=0;window.testReloadListener=false;
            const registration={waiting:{postMessage:()=>window.testActivation++},addEventListener(){},update:async()=>{}};
            Object.defineProperty(navigator,'serviceWorker',{value:{register:async()=>registration,addEventListener:()=>window.testReloadListener=true}});''')
            page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(base+'/customers/new')
            assert page.locator('.bottom-nav a').get_attribute('aria-current')=='page'
            page.locator('input[name=name]').fill('草稿客户')
            page.locator('textarea[name=note]').fill('临时备注')
            page.locator('input[name=pinned]').check()
            page.locator('input[name=password]').fill('never-store-password')
            raw=page.evaluate('JSON.stringify({...sessionStorage})')
            assert '草稿客户' in raw and 'never-store-password' not in raw and 'fresh-csrf' not in raw
            page.reload()
            assert page.locator('input[name=name]').input_value()==''
            page.get_by_role('button',name='恢复草稿').click()
            assert page.locator('input[name=name]').input_value()=='草稿客户'
            assert page.locator('input[name=pinned]').is_checked()
            assert page.locator('input[name=revision]').input_value()=='9'
            assert page.locator('input[name=password]').input_value()==''
            page.locator('#pwa-update').get_by_role('button',name='更新',exact=True).click()
            assert page.evaluate('window.testActivation')==0
            assert '请先保存' in page.locator('#pwa-update').inner_text()
            # Explicit history return restores a list's local filter and scroll.
            page.locator('#serviceFilter').fill('筛选客户')
            page.evaluate('window.scrollTo(0,900)')
            page.goto(base+'/work')
            page.evaluate("sessionStorage.setItem('chen-assistant:history-nav:v1432',JSON.stringify({pending:{target:'/customers/new'}}))")
            page.goto(base+'/customers/new')
            assert page.locator('#serviceFilter').input_value()=='筛选客户'
            page.wait_for_function('window.scrollY>800')
            # A clean view can activate a waiting worker, but never automatically.
            assert page.evaluate('window.testActivation')==0
            page.locator('#pwa-update').get_by_role('button',name='更新',exact=True).click()
            assert page.evaluate('window.testActivation')==1
            # Failed validation keeps a draft; successful detail redirect clears it.
            page.locator('input[name=name]').fill('成功客户')
            page.evaluate("document.querySelector('form[method=post]').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))")
            page.goto(base+'/customers/new')
            assert page.get_by_role('button',name='恢复草稿').is_visible()
            page.get_by_role('button',name='恢复草稿').click()
            page.evaluate("document.querySelector('form[method=post]').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))")
            page.goto(base+'/customers/123',referer=base+'/customers/new')
            raw=page.evaluate('JSON.stringify({...sessionStorage})')
            assert '成功客户' not in raw
            # Broken storage must not disable all enhancements or page navigation.
            page.evaluate("sessionStorage.setItem('chen-assistant:history-nav:v1432','bad-json')")
            page.goto(base+'/work')
            assert page.locator('#pwa-update').is_visible()
            assert not errors,errors
            context.close();browser.close()
    finally:
        server.shutdown();server.server_close()
    print('PWA experience passed: desktop isolation, explicit draft restore, private-field exclusion, filter/scroll recovery, validation failure, successful save, update protection, storage tolerance')

if __name__=='__main__':
    main()
