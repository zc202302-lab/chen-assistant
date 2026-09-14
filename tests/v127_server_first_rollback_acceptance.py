from __future__ import annotations

import os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMP = tempfile.TemporaryDirectory(prefix='chen-v127-')
os.environ['APP_DB_PATH'] = str(Path(_TMP.name) / 'app.db')
os.environ.update({
    'APP_USERNAME':'ui-test','APP_PASSWORD_SALT':'dGVzdHNhbHQ=',
    'APP_PASSWORD_HASH':'x','APP_SESSION_SECRET':'ui-test-session-secret',
    'APP_ENCRYPTION_KEY':'x','APP_SECURE_COOKIE':'0',
})

from app.db import db, init_db, now_iso
from app.payment_v02 import current_period
from app.security import create_session


def seed():
    init_db(); now = now_iso(); period = current_period()
    with db() as conn:
        cid = int(conn.execute(
            'INSERT INTO customers(name,group_code,payment_enabled,created_at,updated_at) VALUES(?,?,?,?,?)',
            ('服务端权威状态客户','V127',1,now,now),
        ).lastrowid)
        sid = int(conn.execute(
            '''INSERT INTO services(customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
               payment_cycle,payment_interval_months,next_payment_period,active_from_period,sort_order,source_row,payment_method)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (cid,'成员','成员1','13999990000','V127-A',100,0,'1个月',1,'',period,10,1,'微信'),
        ).lastrowid)
        conn.execute('INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at) VALUES(?,?,?,?,?)',(sid,'1900-01','variable',0,now))
        conn.execute('INSERT INTO payment_entries(service_id,period,amount,reference_amount,source,confirmed,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(sid,period,100,100,'manual',1,now,now))
    token,_,_ = create_session()
    return cid, token


def wait(url):
    for _ in range(100):
        try:
            if urllib.request.urlopen(url, timeout=1).status == 200: return
        except Exception: pass
        time.sleep(.2)
    raise RuntimeError('server start failed')


def main():
    cid, token = seed()
    proc = subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8147'], cwd=ROOT, env=os.environ.copy())
    try:
        wait('http://127.0.0.1:8147/health')
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={'width':1400,'height':900})
            ctx.add_cookies([{'name':'session_token','value':token,'url':'http://127.0.0.1:8147'}])
            page = ctx.new_page()
            page.goto(f'http://127.0.0.1:8147/customers/{cid}', wait_until='networkidle')
            page.wait_for_timeout(1200)
            notify = page.locator('[data-v031-flow-action="notify"]')
            page.evaluate('''() => { window.ChenPaymentWorkflowActionsV031.prepareNotice = async () => ({mode:'clipboard',test:true}); }''')

            notify.click(); expect(notify).to_contain_text('待确认', timeout=5000)
            notify.click(); expect(notify).to_have_attribute('aria-pressed','true', timeout=5000)

            # Simulate the production bug: UI lies and looks unfinished while server is already notified.
            page.evaluate('''() => {
              const b=document.querySelector('[data-v031-flow-action="notify"]');
              b.setAttribute('aria-pressed','false'); b.classList.remove('done'); b.textContent='2 通知客户';
            }''')
            expect(notify).to_have_attribute('aria-pressed','false')

            # One click must still rollback because v1.2.7 asks the server before deciding direction.
            notify.click()
            with db() as conn:
                deadline = time.time() + 5
                while time.time() < deadline:
                    row = conn.execute('SELECT notified_at FROM customer_payment_runs WHERE customer_id=? AND period=?',(cid,current_period())).fetchone()
                    if row and not row['notified_at']: break
                    time.sleep(.1)
                assert row and not row['notified_at'], row
            expect(notify).to_have_attribute('aria-pressed','false', timeout=5000)
            browser.close()
        print('v1.2.7 server-first rollback acceptance passed')
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill()

if __name__ == '__main__': main()
