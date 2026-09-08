from __future__ import annotations

import os, subprocess, sys, time, urllib.request
from datetime import date
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
DB=ROOT/'data'/'app.db'
for suffix in ('','-wal','-shm'):
    p=Path(str(DB)+suffix)
    if p.exists(): p.unlink()

os.environ.setdefault('APP_USERNAME','ui-test')
os.environ.setdefault('APP_PASSWORD_SALT','dGVzdHNhbHQ=')
os.environ.setdefault('APP_PASSWORD_HASH','not-used-by-this-test')
os.environ.setdefault('APP_SESSION_SECRET','ui-test-session-secret')
os.environ.setdefault('APP_ENCRYPTION_KEY','not-used-by-this-test')
os.environ.setdefault('APP_SECURE_COOKIE','0')

from app.db import db,init_db,now_iso  # noqa:E402
from app.payment_v02 import current_period  # noqa:E402
from app.security import create_session  # noqa:E402


def seed():
    init_db(); now=now_iso(); period=current_period()
    with db() as conn:
        ids=[]
        for n in (1,2):
            cur=conn.execute('INSERT INTO customers (name,group_code,tax_id,payment_enabled,created_at,updated_at) VALUES(?,?,?,?,?,?)',(f'高级测试客户{n}',f'G{n}','T',1,now,now))
            cid=int(cur.lastrowid)
            cur=conn.execute('''INSERT INTO services (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,payment_cycle,payment_interval_months,active_from_period,sort_order,source_row) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(cid,'成员',f'姓名{n}',f'1390000000{n}',f'5338999000{n}',100,0,'1个月',1,period,10,1))
            sid=int(cur.lastrowid)
            conn.execute('INSERT INTO service_payment_rules (service_id,effective_period,mode,fixed_amount,created_at) VALUES(?,?,?,?,?)',(sid,'1900-01','variable',0,now))
            ids.append((cid,sid))
        for name in ('优惠甲','优惠乙'):
            conn.execute('''INSERT INTO promotions (service_id,name,start_date,expiry_date,remind_days,status,notes,created_at) VALUES(?,?,?,?,?,?,?,?)''',(ids[0][1],name,'',date.today().isoformat(),60,'active','',now))
    token,_,_=create_session(); return ids[0][0],ids[1][0],token


def wait_http(url,timeout=15):
    end=time.time()+timeout
    while time.time()<end:
        try:
            with urllib.request.urlopen(url,timeout=1) as r:
                if r.status==200:return
        except Exception:pass
        time.sleep(.2)
    raise RuntimeError('server did not start')


def main():
    c1,c2,token=seed()
    server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8124'],cwd=ROOT,env=os.environ.copy(),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    try:
        wait_http('http://127.0.0.1:8124/health')
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser=p.chromium.launch(); context=browser.new_context(viewport={'width':1440,'height':1000})
            context.add_cookies([{'name':'session_token','value':token,'url':'http://127.0.0.1:8124'}])
            page=context.new_page()

            page.goto(f'http://127.0.0.1:8124/customers/{c1}?tab=services',wait_until='networkidle')
            page.locator('[data-customer-panel="services"] [data-open-service-editor]').first.click()
            dlg=page.locator('#businessAttributeDialog'); dlg.wait_for(state='visible')
            page.locator('[data-add-global-attribute]').click()
            new=page.locator('.global-attribute-row-v028').last
            new.locator('.attr-label').fill('排序删除测试属性'); new.locator('.attr-value').fill('客户1值')
            page.locator('[data-business-attribute-form] button[type="submit"]').click(); dlg.wait_for(state='hidden')

            page.locator('[data-customer-panel="services"] [data-open-service-editor]').first.click(); dlg.wait_for(state='visible')
            custom_key=page.locator('.global-attribute-row-v028').evaluate_all("rows=>rows.find(r=>r.querySelector('.attr-label')?.value==='排序删除测试属性')?.dataset.key||''")
            assert custom_key
            source=page.locator(f'.global-attribute-row-v028[data-key="{custom_key}"] .global-attribute-handle')
            target=page.locator('.global-attribute-row-v028').first
            source.drag_to(target); page.wait_for_timeout(150)
            first_label=page.locator('.global-attribute-row-v028').first.locator('.attr-label').input_value()
            assert first_label=='排序删除测试属性',first_label
            page.locator('[data-business-attribute-form] button[type="submit"]').click(); dlg.wait_for(state='hidden')
            assert page.locator('.business-attribute small').first.inner_text().strip()=='排序删除测试属性'

            page.goto(f'http://127.0.0.1:8124/customers/{c2}?tab=services',wait_until='networkidle')
            page.locator('[data-customer-panel="services"] [data-open-service-editor]').first.click(); dlg.wait_for(state='visible')
            assert page.locator('.global-attribute-row-v028').first.locator('.attr-label').input_value()=='排序删除测试属性'

            page.locator('.global-attribute-row-v028').first.locator('.global-attribute-delete').click()
            page.locator('[data-business-attribute-form] button[type="submit"]').click(); dlg.wait_for(state='hidden')
            page.goto(f'http://127.0.0.1:8124/customers/{c1}?tab=services',wait_until='networkidle')
            assert page.locator('.business-attribute').filter(has_text='排序删除测试属性').count()==0
            page.locator('[data-customer-panel="services"] [data-open-service-editor]').first.click(); dlg.wait_for(state='visible')
            labels=page.locator('.attr-label').evaluate_all('xs=>xs.map(x=>x.value)')
            assert '排序删除测试属性' not in labels
            page.locator('[data-business-editor-close]').first.click(); dlg.wait_for(state='hidden')

            page.goto(f'http://127.0.0.1:8124/customers/{c1}?tab=promotions',wait_until='networkidle')
            expired=page.locator('.promo-column-v028.state-expired')
            group=expired.locator('.promo-number-group-v028').first
            items=group.locator('.promo-item-v028'); assert items.count()==2
            names=lambda:[x.strip() for x in items.locator('.promo-name-copy-v028 strong').all_inner_texts()]
            before=names(); assert before==['优惠甲','优惠乙'],before
            items.nth(1).locator('.promo-drag-handle').drag_to(items.nth(0)); page.wait_for_timeout(300)
            assert names()[0]=='优惠乙',names()
            page.reload(wait_until='networkidle')
            expired=page.locator('.promo-column-v028.state-expired'); group=expired.locator('.promo-number-group-v028').first
            persisted=[x.strip() for x in group.locator('.promo-name-copy-v028 strong').all_inner_texts()]
            assert persisted[0]=='优惠乙',persisted

            details=page.locator('[data-customer-panel="promotions"] details').first
            details.locator('summary').click()
            form=details.locator('form[action*="promotions-v027"]')
            form.locator('input[name="number"]').fill('13900000001')
            form.locator('input[name="name"]').fill('手输号码新增优惠')
            form.locator('input[name="expiry_date"]').fill(date.today().strftime('%Y/%m/%d'))
            with page.expect_navigation(wait_until='networkidle'):
                form.locator('button[type="submit"],button.primary').click()
            if not page.locator('[data-customer-panel="promotions"]').is_visible():
                page.locator('[data-customer-tab="promotions"]').click(); page.wait_for_timeout(80)
            expired=page.locator('.promo-column-v028.state-expired')
            assert expired.locator('.promo-number-group-v028').count()==1
            assert expired.get_by_text('手输号码新增优惠',exact=True).count()==1
            browser.close()
        print('advanced UI acceptance passed')
    finally:
        server.terminate()
        try:server.wait(timeout=5)
        except subprocess.TimeoutExpired:server.kill()


if __name__=='__main__':main()
