"""Use the actual layered workflow UI, including multi-image upload and mobile reading."""
import os
import subprocess
import sys
import time
import urllib.request
from business_process_contract import app, create_session, init_db, image_bytes
from v162_number_inbox_contract import ROOT


def main():
    init_db()
    token, _, _ = create_session()
    base = 'http://127.0.0.1:8185'
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8185'], cwd=ROOT, env=os.environ.copy())
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base+'/health', timeout=1)
                break
            except OSError:
                time.sleep(.2)
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width':1440,'height':950})
            context.add_cookies([{'name':'session_token','value':token,'url':base}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(base+'/work', wait_until='networkidle')
            page.locator('[data-entry-key=processes] a').click()
            page.get_by_role('link', name='＋ 新建流程', exact=True).click()
            page.get_by_label('流程名称', exact=True).fill('集团业务办理指南')
            page.get_by_label('文字说明', exact=True).fill('先准备办理材料，再按照步骤提交申请。')
            page.get_by_role('button', name='保存流程', exact=True).click()
            expect(page.get_by_role('heading',name='集团业务办理指南',exact=True)).to_be_visible()
            page.get_by_role('link',name='＋ 添加步骤',exact=True).click()
            page.get_by_label('步骤名称',exact=True).fill('核对办理材料')
            page.get_by_label('文字说明',exact=True).fill('第一行说明\n第二行说明，确认资料完整。')
            page.locator('[data-process-images]').set_input_files([
                {'name':'材料示例.png','mimeType':'image/png','buffer':image_bytes()},
                {'name':'系统界面.png','mimeType':'image/png','buffer':image_bytes()}])
            expect(page.locator('[data-image-preview] img')).to_have_count(2)
            page.get_by_role('button', name='保存步骤', exact=True).click()
            expect(page.locator('.bp-step')).to_have_count(1)
            expect(page.locator('.bp-step img')).to_have_count(2)
            assert page.locator('.bp-step img').first.evaluate('img => img.complete && img.naturalWidth > 0')
            page.locator('.bp-actions summary').click()
            page.get_by_role('link', name='编辑步骤', exact=True).click()
            page.get_by_label('步骤名称', exact=True).fill('核对资料与授权')
            page.locator('input[name=remove_images]').first.check()
            page.get_by_role('button', name='保存步骤', exact=True).click()
            expect(page.locator('.bp-step img')).to_have_count(1)
            page.get_by_role('link',name='＋ 添加步骤',exact=True).click()
            page.get_by_label('步骤名称',exact=True).fill('提交系统申请')
            page.get_by_label('文字说明',exact=True).fill('填写受理内容并提交。')
            page.get_by_role('button',name='保存步骤',exact=True).click()
            page.locator('.bp-step').last.locator('summary').click()
            page.locator('.bp-step').last.get_by_role('button',name='上移',exact=True).click()
            expect(page.locator('.bp-step h2').first).to_have_text('提交系统申请')
            page.reload(wait_until='networkidle')
            expect(page.locator('.bp-step h2').first).to_have_text('提交系统申请')
            output = ROOT/'artifacts'/'list-compact'
            output.mkdir(parents=True, exist_ok=True)
            for width in (1440, 390):
                page.set_viewport_size({'width':width,'height':950})
                expect(page.locator('.bp-step h2').first).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                page.screenshot(path=str(output/f'business-process-{width}.png'), full_page=True)
            page.on('dialog', lambda dialog: dialog.accept())
            page.locator('.bp-step').first.locator('summary').click()
            page.locator('.bp-step').first.get_by_role('button',name='删除步骤',exact=True).click()
            expect(page.locator('.bp-step')).to_have_count(1)
            page.get_by_role('button',name='删除整个流程',exact=True).click()
            expect(page.get_by_role('heading', name='建立你的第一份业务流程')).to_be_visible()
            assert not errors, errors
            browser.close()
        print('business process browser acceptance passed: create, image previews/upload/removal, edit, reorder, reload, mobile and deletion')
    finally:
        process.terminate()
        process.wait(timeout=10)


if __name__ == '__main__':
    main()
