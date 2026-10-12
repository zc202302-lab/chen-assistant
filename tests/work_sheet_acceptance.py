"""Actual spreadsheet editing, filtering, resizing, import and export on desktop/mobile."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request
import xlsxwriter
from cryptography.fernet import Fernet

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TMP=tempfile.TemporaryDirectory(prefix='chen-sheet-ui-')
os.environ.update(APP_DB_PATH=str(Path(TMP.name)/'app.db'),APP_USERNAME='sheet-ui',
    APP_PASSWORD_SALT='dGVzdHNhbHQ=',APP_PASSWORD_HASH='x',APP_SESSION_SECRET='sheet-ui',
    APP_ENCRYPTION_KEY=Fernet.generate_key().decode(),APP_SECURE_COOKIE='0')
from app.db import db,init_db
from app.security import create_session
from app.work_list_excel import ExcelTable


def fixture():
    stream=io.BytesIO()
    with xlsxwriter.Workbook(stream,{'in_memory':True,'strings_to_formulas':False}) as book:
        sheet=book.add_worksheet('明细')
        head=book.add_format({'bold':True,'bg_color':'#225588','font_color':'#FFFFFF','border':1})
        percent=book.add_format({'bg_color':'#FFF2CC','num_format':'0.00%','align':'center'})
        merged=book.add_format({'italic':True,'font_color':'#7558A5','border':1})
        sheet.set_column(0,0,25);sheet.set_row(1,30)
        sheet.write_row(0,0,['号码','比例','备注'],head)
        sheet.write_string(1,0,'000123');sheet.write_number(1,1,.25,percent)
        sheet.merge_range(2,0,2,1,'合并单元格',merged)
        sheet.write_string(4,0,'末行')
    return stream.getvalue()


def main():
    init_db();token,_,_=create_session()
    base='http://127.0.0.1:8174'
    proc=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8174'],cwd=ROOT,env=os.environ.copy())
    try:
        for _ in range(100):
            try:
                if urllib.request.urlopen(base+'/health',timeout=1).status==200:break
            except Exception:pass
            time.sleep(.2)
        else:raise RuntimeError('server start failed')
        from playwright.sync_api import expect,sync_playwright
        with sync_playwright() as p:
            browser=p.chromium.launch()
            context=browser.new_context(viewport={'width':1440,'height':900},accept_downloads=True)
            context.add_cookies([{'name':'session_token','value':token,'url':base}])
            page=context.new_page();errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(base+'/work/lists?view=new',wait_until='networkidle')
            expect(page.locator('.ws-grid tbody tr')).to_have_count(4)
            expect(page.locator('.ws-header-input')).to_have_count(3)
            page.get_by_label('清单名称',exact=True).fill('在线表格')
            page.locator('.ws-header-input').first.fill('号码')
            page.locator('.ws-cell[data-row="0"][data-col="0"]').fill('000123')
            page.locator('.ws-cell[data-row="1"][data-col="0"]').fill('另一个号码')
            page.get_by_role('button',name='增加行').click()
            page.get_by_role('button',name='增加列').click()
            expect(page.locator('.ws-grid tbody tr')).to_have_count(5)
            expect(page.locator('.ws-header-input')).to_have_count(4)
            page.get_by_role('button',name='创建清单',exact=True).click()
            expect(page.get_by_role('heading',name='在线表格',exact=True)).to_be_visible()
            url=page.url
            assert page.locator('.ws-cell').first.evaluate("el=>getComputedStyle(el).resize")=='none'
            page.locator('.ws-cell[data-row="0"][data-col="1"]').fill('保存后的值')
            handle=page.locator('.ws-col-resize').first
            original_width=page.locator('.ws-letters th').nth(1).bounding_box()['width']
            handle.scroll_into_view_if_needed()
            page.evaluate('window.scrollTo(0,0)')
            handle.click(trial=True)
            box=handle.bounding_box()
            hit=page.evaluate('p=>document.elementFromPoint(p.x,p.y)?.tagName',{'x':box['x']+box['width']/2,'y':box['y']+box['height']/2})
            page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2)
            page.mouse.down();page.mouse.move(box['x']+box['width']/2+50,box['y']+box['height']/2);page.mouse.up()
            actual_width=page.locator('.ws-letters th').nth(1).bounding_box()['width']
            assert abs(actual_width-original_width-50)<3, {'before':original_width,'after':actual_width,'handle':handle.get_attribute('aria-valuenow'),'table':page.locator('.ws-grid').get_attribute('style'),'box':box,'hit':hit}
            rowhandle=page.locator('.ws-grid tbody .ws-row-resize').first
            rowhandle.focus();rowhandle.press('ArrowDown');rowhandle.press('ArrowDown')
            with page.expect_navigation(wait_until='networkidle'):
                page.get_by_role('button',name='保存表格',exact=True).click()
            expect(page.locator('.ws-cell[data-row="0"][data-col="1"]')).to_have_value('保存后的值')
            data=json.loads(page.locator('#work-sheet-data').text_content())
            assert list(data['layout']['widths'].values())[0]>=195
            assert list(data['layout']['heights'].values())[0]==48
            page.get_by_role('button',name='筛选第1列',exact=True).click()
            page.get_by_label('第1列筛选内容',exact=True).fill('000123')
            page.get_by_label('第1列筛选内容',exact=True).press('Enter')
            expect(page.locator('.ws-grid tbody tr')).to_have_count(1)
            page.get_by_role('button',name='清除筛选',exact=True).click()
            expect(page.locator('.ws-grid tbody tr')).to_have_count(5)
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+2')
            expect(page.get_by_role('button',name='增加行')).to_be_visible()
            page.goto(base+'/work/lists?view=new',wait_until='networkidle')
            page.get_by_role('link',name='从 Excel 导入',exact=True).click()
            page.get_by_label('Excel 文件',exact=True).set_input_files({'name':'格式.xlsx','mimeType':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','buffer':fixture()})
            page.get_by_role('button',name='上传文件').click()
            expect(page.locator('input[name="header"],input[name="first"],input[name="last"],input[name="end"]')).to_have_count(0)
            page.get_by_role('button',name='读取工作表').click()
            page.get_by_role('button',name='检查数据并预览导入').click()
            page.get_by_role('button',name='确认导入 4 条',exact=True).click()
            page.get_by_role('link',name='查看清单',exact=True).click()
            expect(page.locator('.ws-grid tbody tr')).to_have_count(4)
            expect(page.locator('.ws-cell[data-row="0"][data-col="0"]')).to_have_value('000123')
            expect(page.locator('.ws-cell[data-row="0"][data-col="1"]')).to_have_value('25.00%')
            expect(page.locator('.ws-grid tbody td[colspan="2"]')).to_have_count(1)
            assert page.locator('.ws-header-cell').first.evaluate('(el)=>getComputedStyle(el).backgroundColor')=='rgb(34, 85, 136)'
            assert page.locator('.ws-grid tbody tr').first.bounding_box()['height']>=39
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+2')
            with page.expect_download() as info:
                page.get_by_role('link',name='导出 Excel',exact=True).click()
            content=Path(info.value.path()).read_bytes()
            reader=ExcelTable(content,'roundtrip.xlsx');table=reader.read('清单',preserve_format=True);reader.close()
            assert len(table['rows'])==4 and table['rows'][0]['cells'][0]=='000123'
            assert table['layout']['cells']['1|1']['background']=='#225588'
            assert table['layout']['cells']['2|2']['number_format']=='0.00%'
            assert table['layout']['merges']==[{'rows':[3],'cols':[1,2]}]
            page.once('dialog',lambda dialog:dialog.accept())
            page.get_by_role('button',name='删除第3行',exact=True).click()
            expect(page.locator('.ws-grid tbody tr')).to_have_count(3)
            page.once('dialog',lambda dialog:dialog.accept())
            page.get_by_role('button',name='删除第1列',exact=True).click()
            expect(page.locator('.ws-header-input')).to_have_count(2)
            with page.expect_navigation(wait_until='networkidle'):
                page.get_by_role('button',name='保存表格',exact=True).click()
            expect(page.locator('.ws-grid tbody tr')).to_have_count(3)
            expect(page.locator('.ws-header-input')).to_have_count(2)
            expect(page.locator('.ws-header-input').first).to_have_value('比例')
            expect(page.locator('.ws-cell[data-row="0"][data-col="0"]')).to_have_value('25.00%')
            data=json.loads(page.locator('#work-sheet-data').text_content())
            assert data['layout']['merges']==[]
            ignored={'Transition was aborted because of invalid state. ViewTransition opt-in disabled','Transition was aborted because of invalid state. Viewport size changed'}
            assert not [e for e in errors if e not in ignored],errors
            browser.close()
        print('Spreadsheet desktop/mobile and formatted Excel roundtrip acceptance passed')
    finally:
        proc.terminate()
        try:proc.wait(timeout=5)
        except subprocess.TimeoutExpired:proc.kill()


if __name__=='__main__':
    main()
