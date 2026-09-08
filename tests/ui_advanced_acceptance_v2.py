from __future__ import annotations
import os, subprocess, sys, time, urllib.request
from datetime import date
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT)); DB=ROOT/'data'/'app.db'
for s in ('','-wal','-shm'):
    p=Path(str(DB)+s)
    if p.exists(): p.unlink()
os.environ.update({'APP_USERNAME':'ui-test','APP_PASSWORD_SALT':'dGVzdHNhbHQ=','APP_PASSWORD_HASH':'x','APP_SESSION_SECRET':'ui-test-session-secret','APP_ENCRYPTION_KEY':'x','APP_SECURE_COOKIE':'0'})
from app.db import db,init_db,now_iso
from app.payment_v02 import current_period
from app.security import create_session

def seed():
    init_db(); now=now_iso(); period=current_period(); out=[]
    with db() as c:
        for n in (1,2):
            cid=int(c.execute('INSERT INTO customers (name,group_code,tax_id,payment_enabled,created_at,updated_at) VALUES(?,?,?,?,?,?)',(f'高级客户{n}',f'G{n}','T',1,now,now)).lastrowid)
            sid=int(c.execute('''INSERT INTO services (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,payment_cycle,payment_interval_months,active_from_period,sort_order,source_row) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(cid,'成员',f'姓名{n}',f'1390000000{n}',f'5338999000{n}',100,0,'1个月',1,period,10,1)).lastrowid)
            c.execute('INSERT INTO service_payment_rules (service_id,effective_period,mode,fixed_amount,created_at) VALUES(?,?,?,?,?)',(sid,'1900-01','variable',0,now)); out.append((cid,sid))
        for name in ('优惠甲','优惠乙'):
            c.execute('INSERT INTO promotions (service_id,name,start_date,expiry_date,remind_days,status,notes,created_at) VALUES(?,?,?,?,?,?,?,?)',(out[0][1],name,'',date.today().isoformat(),60,'active','',now))
    return out[0][0],out[1][0],create_session()[0]

def wait(url):
    for _ in range(80):
        try:
            if urllib.request.urlopen(url,timeout=1).status==200:return
        except Exception: pass
        time.sleep(.2)
    raise RuntimeError('server start failed')

def main():
    c1,c2,token=seed(); proc=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8124'],cwd=ROOT,env=os.environ.copy())
    try:
        wait('http://127.0.0.1:8124/health')
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b=p.chromium.launch(); ctx=b.new_context(viewport={'width':1440,'height':1000}); ctx.add_cookies([{'name':'session_token','value':token,'url':'http://127.0.0.1:8124'}]); page=ctx.new_page()
            page.goto(f'http://127.0.0.1:8124/customers/{c1}?tab=services',wait_until='networkidle')
            page.locator('[data-customer-panel="services"] [data-open-service-editor]').first.click(); dlg=page.locator('#businessAttributeDialog'); dlg.wait_for(state='visible')
            page.locator('[data-add-global-attribute]').click(); r=page.locator('.global-attribute-row-v028').last; r.locator('.attr-label').fill('全局排序属性'); r.locator('.attr-value').fill('A值'); page.locator('[data-business-attribute-form] button[type="submit"]').click(); dlg.wait_for(state='hidden')
            page.locator('[data-customer-panel="services"] [data-open-service-editor]').first.click(); dlg.wait_for(state='visible')
            key=page.locator('.global-attribute-row-v028').evaluate_all("rs=>rs.find(r=>r.querySelector('.attr-label')?.value==='全局排序属性')?.dataset.key||''"); assert key
            source=page.locator(f'.global-attribute-row-v028[data-key="{key}"] .global-attribute-handle'); target=page.locator('.global-attribute-row-v028').first
            source.drag_to(target,target_position={'x':20,'y':2}); page.wait_for_timeout(200); assert page.locator('.global-attribute-row-v028').first.locator('.attr-label').input_value()=='全局排序属性'
            page.locator('[data-business-attribute-form] button[type="submit"]').click(); dlg.wait_for(state='hidden'); assert page.locator('.business-attribute small').first.inner_text().strip()=='全局排序属性'
            page.goto(f'http://127.0.0.1:8124/customers/{c2}?tab=services',wait_until='networkidle'); page.locator('[data-customer-panel="services"] [data-open-service-editor]').first.click(); dlg.wait_for(state='visible'); assert page.locator('.global-attribute-row-v028').first.locator('.attr-label').input_value()=='全局排序属性'
            page.locator('.global-attribute-row-v028').first.locator('.global-attribute-delete').click(); page.locator('[data-business-attribute-form] button[type="submit"]').click(); dlg.wait_for(state='hidden')
            page.goto(f'http://127.0.0.1:8124/customers/{c1}?tab=services',wait_until='networkidle'); assert page.locator('.business-attribute').filter(has_text='全局排序属性').count()==0
            page.goto(f'http://127.0.0.1:8124/customers/{c1}?tab=promotions',wait_until='networkidle'); group=page.locator('.promo-column-v028.state-expired .promo-number-group-v028').first; items=group.locator('.promo-item-v028'); assert items.count()==2
            names=lambda:[x.strip() for x in items.locator('.promo-name-copy-v028 strong').all_inner_texts()]; assert names()==['优惠甲','优惠乙']; items.nth(1).locator('.promo-drag-handle').drag_to(items.nth(0),target_position={'x':20,'y':2}); page.wait_for_timeout(250); assert names()[0]=='优惠乙'; page.reload(wait_until='networkidle'); group=page.locator('.promo-column-v028.state-expired .promo-number-group-v028').first; assert group.locator('.promo-name-copy-v028 strong').all_inner_texts()[0].strip()=='优惠乙'
            d=page.locator('[data-customer-panel="promotions"] details').first; d.locator('summary').click(); f=d.locator('form[action*="promotions-v027"]'); f.locator('input[name="number"]').fill('13900000001'); f.locator('input[name="name"]').fill('手输新增优惠'); f.locator('input[name="expiry_date"]').fill(date.today().strftime('%Y/%m/%d'))
            with page.expect_navigation(wait_until='networkidle'): f.locator('button[type="submit"],button.primary').click()
            if not page.locator('[data-customer-panel="promotions"]').is_visible(): page.locator('[data-customer-tab="promotions"]').click()
            expired=page.locator('.promo-column-v028.state-expired'); assert expired.locator('.promo-number-group-v028').count()==1; assert expired.get_by_text('手输新增优惠',exact=True).count()==1
            b.close()
        print('advanced UI acceptance passed')
    finally:
        proc.terminate(); proc.wait(timeout=5)
if __name__=='__main__': main()
