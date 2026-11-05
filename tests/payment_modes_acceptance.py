"""Real completion dialog, sequential editing and both exemption paths."""
from payment_next_date_contract import ROOT, app, db, init_db, now_iso, create_session
from app.payment_v02 import current_period
from app.payment_schedule import computed_next_date
from app.v031_payment_workflow_routes import _run_v031
import os
import subprocess
import sys
import time
import urllib.request


def main():
    init_db()
    now = now_iso()
    period = current_period()
    with db() as conn:
        cid = conn.execute('INSERT INTO customers(name,payment_enabled,created_at,updated_at) VALUES(?,1,?,?)',('缴费模式验收',now,now)).lastrowid
        ids = []
        for i in range(3):
            ids.append(conn.execute('''INSERT INTO services(customer_id,service_type,number,payment_interval_months,payment_cycle,last_payment_date,next_payment_date,payment_schedule_mode,monthly_fee,fixed_fee)
              VALUES(?,?,?,?,?,?,?,?,?,?)''',(cid,'成员',f'1380000000{i}',1,'1个月','2020-01-01',period+'-01','specified',10,1)).lastrowid)
        other_customer = conn.execute('INSERT INTO customers(name,payment_enabled,created_at,updated_at) VALUES(?,1,?,?)',
                                      ('模式切换刷新客户',now,now)).lastrowid
        periodic_id = conn.execute('''INSERT INTO services(customer_id,service_type,number,payment_interval_months,
            payment_cycle,last_payment_date,next_payment_date,payment_schedule_mode,monthly_fee,fixed_fee)
            VALUES(?,?,?,?,?,?,?,?,?,?)''',
            (other_customer,'成员','13800000009',1,'1个月','2020-01-01','2020-02-01','periodic',10,1)).lastrowid
        run, _ = _run_v031(conn,cid)
        conn.execute('UPDATE customer_payment_runs SET reviewed_at=?,notified_at=?,initiated_at=? WHERE id=?',(now,now,now,run['id']))
    token, _, _ = create_session()
    base = 'http://127.0.0.1:8179'
    proc = subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8179','--log-level','warning'],cwd=ROOT,env=os.environ.copy())
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base+'/health',timeout=1)
                break
            except Exception:
                time.sleep(.2)
        from playwright.sync_api import expect,sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width':1440,'height':1000})
            context.add_cookies([{'name':'session_token','value':token,'url':base}])
            page = context.new_page()
            errors=[]
            page.on('pageerror',lambda error: errors.append(str(error)))
            dashboard = context.new_page()
            dashboard.goto(base+'/work/customers',wait_until='networkidle')
            dashboard_link = dashboard.locator(f'[data-home-panel="payment"] a[href="/customers/{other_customer}"]')
            expect(dashboard_link).to_have_count(1)
            page.goto(base+f'/customers/{other_customer}?tab=payment',wait_until='networkidle')
            page.evaluate('window.__paymentModeRefresh = true')
            row = page.locator(f'[data-payment-row][data-service-id="{periodic_id}"]')
            row.locator('[data-open-service-editor]').click()
            editor = page.locator('#businessAttributeDialog')
            expect(editor.locator('[data-v031-payment-mode]')).to_have_value('periodic')
            editor.locator('[data-v031-payment-mode]').select_option('specified')
            editor.locator('[data-key="next_payment_date"] .attr-value').fill(computed_next_date(period+'-01',2))
            editor.locator('.attribute-dialog-actions button[type="submit"]').click()
            expect(row).to_have_count(0)
            expect(page.locator('#paymentDueCount')).to_have_text('0')
            expect(page.locator('#paymentGrandTotal')).to_have_text('¥0')
            expect(page.locator('[data-payment-empty]')).to_be_visible()
            assert page.evaluate('window.__paymentModeRefresh')
            expect(dashboard_link).to_have_count(0)
            dashboard.close()
            page.goto(base+f'/customers/{cid}?tab=payment',wait_until='networkidle')
            paid=page.locator('[data-v031-flow-action="paid"]')
            expect(paid).to_be_enabled()
            paid.click()
            prompt=page.get_by_role('dialog').filter(has=page.get_by_role('heading',name='请设置下次缴费时间'))
            expect(prompt).to_contain_text('3 条业务')
            output=ROOT/'artifacts'/'list-compact'
            output.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(output/'payment-modes-confirm.png'))
            prompt.get_by_role('button',name='取消',exact=True).click()
            expect(paid).to_have_attribute('aria-pressed','false')
            paid.click()
            prompt.get_by_role('button',name='进入',exact=True).click()
            editor=page.locator('#businessAttributeDialog')
            expect(editor).to_be_visible()
            expect(editor.locator('[name="service_id"]')).to_have_value(str(ids[0]))
            # Same date must not advance.
            save=editor.locator('.attribute-dialog-actions button[type="submit"]')
            page.evaluate("document.querySelector('.v0211-workspace').addEventListener('chen:service-editor-opened', () => window.__dateEditorOpens = (window.__dateEditorOpens || 0) + 1)")
            save.click()
            page.wait_for_function('() => window.__dateEditorOpens === 1')
            expect(editor).to_be_visible()
            expect(editor.locator('[name="service_id"]')).to_have_value(str(ids[0]))
            editor.locator('[data-key="next_payment_date"] .attr-value').fill(computed_next_date(period+'-01',2))
            save.click()
            expect(editor.locator('[name="service_id"]')).to_have_value(str(ids[1]))
            editor.locator('[data-business-editor-close]').first.click()
            page.reload(wait_until='networkidle')
            paid.click()
            expect(prompt).to_contain_text('2 条业务')
            prompt.get_by_role('button',name='进入',exact=True).click()
            expect(editor.locator('[name="service_id"]')).to_have_value(str(ids[1]))
            expect(editor.locator('[data-v031-payment-mode]')).to_have_value('specified')
            editor.locator('[data-v031-payment-mode]').select_option('periodic')
            save.click()
            expect(editor.locator('[name="service_id"]')).to_have_value(str(ids[2]))
            editor.locator('[data-v03-business-enabled]').select_option('inactive')
            save.click()
            expect(editor).not_to_be_visible()
            expect(paid).to_be_enabled()
            paid.click()
            expect(paid).to_have_attribute('aria-pressed','true')
            assert not errors, errors
            output=ROOT/'artifacts'/'list-compact'
            output.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(output/'payment-modes-completed.png'))
            # Verify controls and dialog fit on phone as well as desktop.
            page.locator('[data-customer-tab="services"]').click()
            for width,height in [(1440,1000),(390,844)]:
                page.set_viewport_size({'width':width,'height':height})
                page.locator(f'[data-business-row][data-service-id="{ids[0]}"] .business-attribute').first.dblclick()
                expect(editor).to_be_visible()
                expect(editor.locator('[data-v031-payment-mode]')).to_have_value('specified')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                mode=editor.locator('[data-v031-payment-mode]').bounding_box()
                bounds=editor.bounding_box()
                assert mode['width'] >= 94
                assert mode['x'] + mode['width'] <= bounds['x'] + bounds['width']
                page.screenshot(path=str(output/f'payment-modes-{width}.png'))
                editor.locator('[data-business-editor-close]').first.click()
            browser.close()
        print('payment modes browser passed: cancel, unchanged, sequential dates, convert, close, complete, desktop/phone')
    finally:
        proc.terminate()
        proc.wait(timeout=10)


if __name__=='__main__':
    main()
