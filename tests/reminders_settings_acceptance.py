"""Real settings page with an isolated DB and simulated browser push APIs."""
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TMP=tempfile.TemporaryDirectory(prefix='chen-reminders-ui-')
os.environ.update(APP_DB_PATH=str(Path(TMP.name)/'app.db'),APP_USERNAME='ui-test',
    APP_PASSWORD_SALT='dGVzdHNhbHQ=',APP_PASSWORD_HASH='x',APP_SESSION_SECRET='reminder-ui-test',
    APP_ENCRYPTION_KEY=Fernet.generate_key().decode(),APP_SECURE_COOKIE='0')
from app.db import init_db
from app.security import create_session
from app.reminders import ensure_reminder_schema


def main():
    init_db();ensure_reminder_schema()
    token,_,_=create_session()
    key=ec.generate_private_key(ec.SECP256R1())
    b64=lambda raw:base64.urlsafe_b64encode(raw).rstrip(b'=').decode()
    subscription={'endpoint':'https://web.push.apple.com/ui-test-only','keys':{
        'auth':b64(os.urandom(16)), 'p256dh':b64(key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint))}}
    stub='''(() => {
      const subscription=SUBSCRIPTION;
      window.uiPush={sub:null,permissions:[],tests:[]};
      const makeSub=()=>({endpoint:subscription.endpoint,options:{},toJSON:()=>subscription,unsubscribe:async()=>{window.uiPush.sub=null;localStorage.removeItem('ui-sub');return true;}});
      if(localStorage.getItem('ui-sub'))window.uiPush.sub=makeSub();
      const reg={update:async()=>{},getNotifications:async()=>[],addEventListener:()=>{},pushManager:{
        getSubscription:async()=>window.uiPush.sub,subscribe:async()=>{window.uiPush.sub=makeSub();localStorage.setItem('ui-sub','1');return window.uiPush.sub;}}};
      Object.defineProperty(navigator,'standalone',{value:true});
      Object.defineProperty(navigator,'serviceWorker',{value:{register:async()=>reg,ready:Promise.resolve(reg),controller:null,addEventListener:()=>{}}});
      window.PushManager=class {};
      window.Notification=class {};
      Notification.permission='granted';
      Notification.requestPermission=()=>{window.uiPush.permissions.push(navigator.userActivation.isActive);return Promise.resolve('granted');};
    })();'''.replace('SUBSCRIPTION',json.dumps(subscription))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    process=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=os.environ.copy(),stdout=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                with urlopen(base+'/health',timeout=1):break
            except OSError:time.sleep(.2)
        else:raise RuntimeError('UI server did not start')
        from playwright.sync_api import sync_playwright,expect
        previews=ROOT/'artifacts/reminders-settings';previews.mkdir(parents=True,exist_ok=True)
        with sync_playwright() as pw:
            browser=pw.chromium.launch()
            for width in [1440,390]:
                context=browser.new_context(viewport={'width':width,'height':900},is_mobile=width==390)
                context.add_init_script(stub)
                context.add_cookies([{'name':'session_token','value':token,'url':base}])
                page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base+'/reminders',wait_until='networkidle')
                page.locator('[data-reminder-tab=settings]').click()
                panel=page.locator('[data-reminder-panel=settings]')
                expect(panel).to_be_visible()
                assert panel.get_by_text('iPhone：',exact=False).count()==0
                master=page.get_by_role('switch',name='本机通知',exact=True)
                expect(master).to_be_enabled()
                master.click();expect(master).to_have_attribute('aria-checked','true')
                assert page.evaluate('uiPush.permissions')==[True]
                instant=page.get_by_role('switch',name='即时提醒',exact=True)
                instant.uncheck();expect(instant).not_to_be_checked()
                instant.check();expect(instant).to_be_checked()
                for value in ['09:00','18:00']:
                    page.locator('#reminder-schedule-time').fill(value)
                    page.locator('#reminder-schedule-add').click()
                    expect(page.get_by_label('删除 '+value,exact=True)).to_be_visible()
                page.reload(wait_until='networkidle');page.locator('[data-reminder-tab=settings]').click()
                expect(page.get_by_label('删除 09:00',exact=True)).to_be_visible()
                expect(master).to_have_attribute('aria-checked','true')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                assert not page.locator('#push-delivery').is_visible()
                page.screenshot(path=str(previews/f'settings-{width}.png'),full_page=True)
                page.route('**/api/reminders/test',lambda route:route.fulfill(json={'ok':True}))
                with page.expect_request(lambda r:r.url.endswith('/api/reminders/test')) as sent:
                    page.locator('#push-test-lock').click()
                assert sent.value.post_data_json['delay']==20
                page.get_by_label('删除 18:00',exact=True).click()
                expect(page.get_by_label('删除 18:00',exact=True)).to_have_count(0)
                page.route('**/api/reminders/schedule',lambda route:route.fulfill(status=500,json={'detail':'保存失败'}))
                page.locator('#reminder-schedule-time').fill('08:45');page.locator('#reminder-schedule-add').click()
                expect(page.locator('#reminder-feedback')).to_have_text('保存失败')
                expect(page.locator('#reminder-schedule-time')).to_have_value('08:45')
                page.unroute('**/api/reminders/schedule')
                page.get_by_label('删除 09:00',exact=True).click()
                master.click();expect(master).to_have_attribute('aria-checked','false')
                assert not errors,errors
                context.close()
            browser.close()
    finally:
        process.terminate();process.wait(timeout=10)
    print('Reminder settings UI passed: mobile/desktop, subscriptions, permission gesture, switches, schedule persistence/delete, failure retention, no overflow')

if __name__=='__main__':main()
