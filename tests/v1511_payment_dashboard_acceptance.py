from __future__ import annotations
import os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v1511-dashboard-')
TEST_DB = Path(_TMPDIR.name) / 'app.db'
os.environ['APP_DB_PATH'] = str(TEST_DB)
os.environ.update({'APP_USERNAME':'ui-test','APP_PASSWORD_SALT':'dGVzdHNhbHQ=','APP_PASSWORD_HASH':'x','APP_SESSION_SECRET':'v1511-dashboard-session','APP_ENCRYPTION_KEY':'x','APP_SECURE_COOKIE':'0'})
from app.db import db, init_db, now_iso
from app.payment_v02 import current_period
from app.security import create_session
from app.v031_payment_workflow_routes import ensure_v031

def seed():
    init_db(); now=now_iso(); period=current_period()
    stages=[('甲公司-未通知',0,0,'','',''),('乙公司-已通知',1,0,now,'',''),('丙公司-待缴费',1,0,now,now,''),('丁公司-已完成',1,1,now,now,now)]
    ids={}
    with db() as conn:
        ensure_v031(conn)
        for idx,(name,notified,completed,notified_at,initiated_at,paid_at) in enumerate(stages,1):
            cid=int(conn.execute('''INSERT INTO customers(name,group_code,payment_enabled,payment_period,notified,completed,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)''',(name,f'V1511-{idx}',1,period,notified,completed,now,now)).lastrowid)
            ids[name]=cid
            conn.execute('''INSERT INTO services(customer_id,service_type,number,account,monthly_fee,payment_cycle,payment_interval_months,active_from_period,source_row,sort_order) VALUES(?,?,?,?,?,?,?,?,?,?)''',(cid,'成员',f'1380000010{idx}',f'ACCT{idx}',100+idx,'月',1,period,idx,idx*10))
            if notified_at or initiated_at or paid_at:
                conn.execute('''INSERT INTO customer_payment_runs(customer_id,period,notified_at,initiated_at,paid_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?)''',(cid,period,notified_at,initiated_at,paid_at,now,now))
    token,_,_=create_session(); return ids,token

def wait_http(url):
    for _ in range(100):
        try:
            if urllib.request.urlopen(url,timeout=1).status==200:return
        except Exception: pass
        time.sleep(.2)
    raise RuntimeError('server start failed')

def main():
    ids,token=seed()
    proc=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8151'],cwd=ROOT,env=os.environ.copy())
    try:
        wait_http('http://127.0.0.1:8151/health')
        from playwright.sync_api import expect,sync_playwright
        with sync_playwright() as p:
            browser=p.chromium.launch()
            context=browser.new_context(viewport={'width':1600,'height':950})
            context.add_cookies([{'name':'session_token','value':token,'url':'http://127.0.0.1:8151'}])
            page=context.new_page(); page.goto('http://127.0.0.1:8151/work/customers?home=payment',wait_until='networkidle')
            cols=page.locator('.home-payment-stage-v1511'); expect(cols).to_have_count(3)
            headings=[' '.join(x.split()) for x in cols.locator('h3').all_inner_texts()]
            assert headings==['未通知 1','已通知 1','待缴费 1'],headings
            expect(cols.nth(0).get_by_text('甲公司-未通知',exact=True)).to_be_visible()
            expect(cols.nth(1).get_by_text('乙公司-已通知',exact=True)).to_be_visible()
            expect(cols.nth(2).get_by_text('丙公司-待缴费',exact=True)).to_be_visible()
            expect(page.get_by_text('丁公司-已完成',exact=True)).to_have_count(0)
            expect(page.locator('[data-home-tab="payment"] b')).to_have_text('3')
            expect(page.get_by_text('3 个客户待处理',exact=True)).to_be_visible()
            assert cols.nth(2).locator('a').get_attribute('href')==f"/customers/{ids['丙公司-待缴费']}"
            browser.close()
        print('v1.5.11 three-stage payment dashboard browser acceptance passed')
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill()

if __name__ == '__main__':
    main()
