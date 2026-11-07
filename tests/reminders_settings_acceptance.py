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
      window.uiPush={sub:null,permissions:[],tests:[],badge:0,notifications:[],closed:[]};
      const makeSub=()=>({endpoint:subscription.endpoint,options:{},toJSON:()=>subscription,unsubscribe:async()=>{window.uiPush.sub=null;localStorage.removeItem('ui-sub');return true;}});
      if(localStorage.getItem('ui-sub'))window.uiPush.sub=makeSub();
      const reg={update:async()=>{},getNotifications:async()=>window.uiPush.notifications,addEventListener:()=>{},pushManager:{
        getSubscription:async()=>window.uiPush.sub,subscribe:async()=>{window.uiPush.sub=makeSub();localStorage.setItem('ui-sub','1');return window.uiPush.sub;}}};
      navigator.setAppBadge=async count=>{uiPush.badge=count;};
      navigator.clearAppBadge=async()=>{uiPush.badge=0;};
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
            # An ordinary website can manage both destinations without requesting permission.
            website=browser.new_context(viewport={'width':1440,'height':900})
            website.add_init_script(stub)
            website.add_cookies([{'name':'session_token','value':token,'url':base}])
            web=website.new_page();web.goto(base+'/reminders#settings',wait_until='networkidle')
            expect(web.locator('#push-enable')).not_to_be_visible()
            computer=web.get_by_role('switch',name='电脑提醒',exact=True)
            with web.expect_response(lambda r:r.url.endswith('/api/reminders/preferences') and r.request.method=='POST'):
                computer.uncheck()
            web.reload(wait_until='networkidle')
            expect(computer).not_to_be_checked()
            expect(web.get_by_role('switch',name='手机接收提醒',exact=True)).to_be_checked()
            with web.expect_response(lambda r:r.url.endswith('/api/reminders/preferences') and r.request.method=='POST'):
                computer.check()
            assert web.evaluate('uiPush.permissions')==[]
            assert web.evaluate('uiPush.sub') is None
            expect(computer).to_be_enabled()
            web.evaluate('scrollTo(0,0)')
            web.screenshot(path=str(previews/'website-1440.png'),full_page=True)
            website.close()
            safari=browser.new_context(user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148')
            safari.add_init_script(stub.replace("'standalone',{value:true}","'standalone',{value:false}"))
            safari.add_cookies([{'name':'session_token','value':token,'url':base}])
            safari_page=safari.new_page();safari_page.goto(base+'/reminders#settings',wait_until='networkidle')
            expect(safari_page.locator('#push-enable')).not_to_be_visible()
            assert safari_page.evaluate('uiPush.permissions')==[]
            assert safari_page.evaluate('uiPush.sub') is None
            safari.close()
            for width in [1440,390]:
                context=browser.new_context(viewport={'width':width,'height':900},is_mobile=width==390,user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148')
                context.add_init_script(stub)
                context.add_cookies([{'name':'session_token','value':token,'url':base}])
                page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base+'/reminders',wait_until='networkidle')
                page.locator('[data-reminder-tab=settings]').click()
                panel=page.locator('[data-reminder-panel=settings]')
                expect(panel).to_be_visible()
                advanced=page.locator('#reminder-advanced-settings')
                assert not advanced.evaluate('(node)=>node.open')
                expect(page.locator('#reminder-devices')).not_to_be_visible()
                expect(page.locator('#push-test')).not_to_be_visible()
                headings=panel.locator(':scope > section h2').all_text_contents()
                assert headings==['通知总开关','手机提醒','电脑提醒'],headings
                # Each setting group stays inside its owning phone section.
                phone_card=panel.locator('.reminder-phone-card')
                expect(phone_card.locator('#reminder-modes')).to_be_visible()
                expect(phone_card.locator('#reminder-preferences')).to_be_visible()
                assert panel.get_by_text('iPhone：',exact=False).count()==0
                master=page.get_by_role('button',name='连接手机通知',exact=True)
                expect(master).to_be_enabled()
                master.click();expect(master).not_to_be_visible()
                assert page.evaluate('uiPush.permissions')==[True]
                instant=page.get_by_role('switch',name='即时提醒',exact=True)
                instant.uncheck();expect(instant).not_to_be_checked()
                instant.check();expect(instant).to_be_checked()
                for value in ['09:00','18:00']:
                    page.locator('#reminder-schedule-time').fill(value)
                    page.locator('#reminder-schedule-add').click()
                    expect(page.get_by_label('删除 '+value,exact=True)).to_be_visible()
                with page.expect_response(lambda r:r.url.endswith('/api/reminders/schedule') and r.request.method=='POST'):
                    page.locator('#reminder-repeat-kind').select_option('weekly')
                expect(page.get_by_label('周一',exact=True)).to_be_checked()
                page.get_by_label('周二',exact=True).uncheck()
                page.get_by_label('周四',exact=True).uncheck()
                scheduled=page.get_by_role('switch',name='定时提醒',exact=True)
                scheduled.uncheck();expect(page.locator('#reminder-timing-card')).not_to_be_visible()
                scheduled.check();expect(page.locator('#reminder-timing-card')).to_be_visible()
                peer=context.new_page();peer.goto(base+'/reminders#settings',wait_until='networkidle')
                total=page.get_by_role('switch',name='通知总开关',exact=True)
                total.uncheck();expect(peer.get_by_role('switch',name='通知总开关',exact=True)).not_to_be_checked(timeout=9000)
                peer.get_by_role('switch',name='通知总开关',exact=True).check();expect(total).to_be_checked(timeout=9000)
                phone=page.get_by_role('switch',name='手机接收提醒',exact=True)
                def keep_unread(route):
                    response=route.fetch()
                    route.fulfill(response=response,json=response.json() | {'unread_count':1,'active_notification_ids':[123]})
                page.route('**/api/reminders',keep_unread)
                page.evaluate("""() => {
                    uiPush.notifications = ['chen-reminder-123','unrelated'].map(tag => ({
                        tag, close: () => uiPush.closed.push(tag)
                    }));
                }""")
                page.wait_for_function('uiPush.badge === 1')
                phone.uncheck();expect(peer.get_by_role('switch',name='手机接收提醒',exact=True)).not_to_be_checked(timeout=9000)
                expect(total).to_be_checked()
                page.wait_for_function("uiPush.badge === 0 && uiPush.closed.includes('chen-reminder-123')")
                assert 'unrelated' not in page.evaluate('uiPush.closed')
                expect(page.locator('[data-reminder-badge]')).to_have_text('1')
                page.unroute('**/api/reminders',keep_unread)
                page.reload(wait_until='networkidle');page.locator('[data-reminder-tab=settings]').click()
                expect(phone).not_to_be_checked()
                with page.expect_response(lambda r:r.url.endswith('/api/reminders/preferences') and r.request.method=='POST'):
                    phone.check()
                expect(phone).to_be_checked()
                peer.close()
                page.reload(wait_until='networkidle');page.locator('[data-reminder-tab=settings]').click()
                expect(page.get_by_label('删除 09:00',exact=True)).to_be_visible()
                expect(page.get_by_label('周二',exact=True)).not_to_be_checked()
                expect(page.get_by_label('周四',exact=True)).not_to_be_checked()
                expect(master).not_to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                assert not page.locator('#push-delivery').is_visible()
                page.evaluate('scrollTo(0,0)')
                page.screenshot(path=str(previews/f'settings-{width}.png'),full_page=True)
                advanced.locator(':scope > summary').click()
                expect(page.locator('#reminder-devices')).to_be_visible()
                expect(page.locator('#reminder-devices')).to_contain_text('连接于')
                expect(page.locator('#reminder-devices')).to_contain_text('最近提交推送')
                expect(page.locator('#reminder-devices')).to_contain_text('（这部手机）')
                # A registered device can still be paused and resumed from advanced settings.
                device_switch=page.locator('#reminder-devices [role=switch]').first
                with page.expect_response(lambda r:'/api/reminders/devices/' in r.url and r.request.method=='POST'):
                    device_switch.click()
                expect(device_switch).to_have_attribute('aria-checked','false')
                with page.expect_response(lambda r:'/api/reminders/devices/' in r.url and r.request.method=='POST'):
                    device_switch.click()
                expect(device_switch).to_have_attribute('aria-checked','true')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                page.evaluate('scrollTo(0,0)')
                page.screenshot(path=str(previews/f'advanced-{width}.png'),full_page=True)
                advanced.get_by_text('测试手机通知',exact=True).click()
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
                page.get_by_role('switch',name='手机接收提醒',exact=True).uncheck();expect(page.get_by_role('switch',name='手机接收提醒',exact=True)).not_to_be_checked()
                # Explicitly removing the phone connection still unsubscribes it.
                with page.expect_response(lambda r:'/api/reminders/devices/' in r.url and r.request.method=='POST'):
                    page.locator('#reminder-devices .reminder-remove').first.click()
                expect(master).to_be_visible()
                assert page.evaluate('uiPush.sub') is None
                assert not errors,errors
                context.close()
            browser.close()
    finally:
        process.terminate();process.wait(timeout=10)
    print('Reminder settings UI passed: mobile/desktop, subscriptions, permission gesture, switches, schedule persistence/delete, failure retention, no overflow')

if __name__=='__main__':main()
