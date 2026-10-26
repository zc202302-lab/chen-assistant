"""Real browser forms, isolated work entry and desktop-to-web changes."""
from pathlib import Path
import os
import subprocess
import sys
import time
import urllib.request
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from v152_high_frequency_flow_acceptance import seed
from cryptography.fernet import Fernet
from app import config
os.environ['APP_ENCRYPTION_KEY'] = Fernet.generate_key().decode()
config.APP_ENCRYPTION_KEY = os.environ['APP_ENCRYPTION_KEY']
from app.db import db


def main():
    cid, ids, token = seed()
    base = 'http://127.0.0.1:8186'
    proc = subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8186'],cwd=ROOT,env=os.environ.copy())
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(base+'/health',timeout=1)
                break
            except Exception:
                time.sleep(.2)
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width':1440,'height':950})
            context.add_cookies([{'name':'session_token','value':token,'url':base}])
            page = context.new_page()
            errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(base+'/work',wait_until='networkidle')
            page.locator('a[href="/work/todos"]').click()
            page.get_by_role('link',name='新增待办',exact=True).click()
            page.get_by_label('待办标题').fill('独立工作测试')
            page.get_by_label('提醒时间',exact=True).fill('2020-01-01T09:00')
            page.get_by_label('备注',exact=True).fill('与集团客户待办分开')
            page.get_by_role('button',name='创建待办',exact=True).click()
            card=page.locator('[data-todo-id]').first
            expect(card).to_contain_text('已到期')
            card.get_by_text('延期',exact=True).click()
            card.get_by_label('延期至',exact=True).fill('2099-01-01T09:00')
            card.get_by_role('button',name='确认延期',exact=True).click()
            expect(card).to_contain_text('待处理')
            card.get_by_role('button',name='结办',exact=True).click()
            expect(page.locator('[data-todo-id]')).to_have_count(0)
            page.goto(base+'/work/todos?view=all',wait_until='networkidle')
            expect(page.locator('[data-todo-id]')).to_contain_text('已结办')
            page.get_by_role('button',name='重新打开',exact=True).click()
            expect(card).to_contain_text('独立工作测试')
            page.get_by_role('link',name='客户端连接',exact=True).click()
            connection=page.get_by_label('待办连接码').input_value()
            headers={'Authorization':'Bearer '+connection}
            snapshot=context.request.get(base+'/api/work-todos',headers=headers).json()
            item=snapshot['items'][0]
            result=context.request.post(base+f"/api/work-todos/{item['id']}",headers=headers,data={'action':'edit','revision':item['revision'],'title':'客户端修改','note':'同步备注','remind_at':''})
            assert result.ok, result.text()
            for width in (1440,390):
                page.set_viewport_size({'width':width,'height':950})
                page.goto(base+'/work/todos',wait_until='networkidle')
                expect(page.locator('[data-todo-id]')).to_contain_text('客户端修改')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                target=ROOT/'artifacts'/'work-todos'
                target.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(target/f'todos-{width}.png'),full_page=True)
            with db() as conn:
                assert conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 0
            assert not errors,errors
            browser.close()
        print('work todos real-browser lifecycle and desktop sync passed')
    finally:
        proc.terminate();proc.wait(timeout=10)

if __name__=='__main__':
    main()
