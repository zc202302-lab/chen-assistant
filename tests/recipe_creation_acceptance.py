"""Create a real manual recipe from the life entry, then edit/read/search/print it."""
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request

from v162_number_inbox_contract import ROOT, init_db
from app.security import create_session
from app.v101_recipe_template_patch import ensure_v101_recipe_templates
from cryptography.fernet import Fernet


def main():
    init_db()
    ensure_v101_recipe_templates()
    token, _, _ = create_session()
    env = os.environ.copy()
    env['APP_ENCRYPTION_KEY'] = Fernet.generate_key().decode()
    base = 'http://127.0.0.1:8188'
    server = subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8188'], cwd=ROOT, env=env)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + '/health', timeout=1)
                break
            except OSError:
                time.sleep(.1)
        else:
            raise AssertionError('test server unavailable')
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width':1440,'height':1000})
            context.add_cookies([{'name':'session_token','value':token,'url':base}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(base + '/life', wait_until='networkidle')
            page.get_by_role('link', name='＋ 新建菜谱', exact=True).click()
            expect(page.get_by_role('heading', name='新建菜谱', exact=True)).to_be_visible()
            page.get_by_label('菜名', exact=True).fill('自建清汤鱼锅')
            page.get_by_label('分类', exact=True).fill('手写鱼类')
            page.get_by_label('标签', exact=True).fill('个人试做')
            page.get_by_label('标准主材重量', exact=True).fill('1000')
            page.get_by_label('说明', exact=True).fill('自己的准备事项')
            page.get_by_role('button', name='创建并编辑配方', exact=True).click()
            expect(page).to_have_url(re.compile(r'/life/recipes/\d+/edit$'))
            rid = int(page.url.split('/')[-2])
            expect(page.get_by_role('heading', name='编辑标准配方', exact=True)).to_be_visible()
            page.get_by_label('改进说明', exact=True).fill('首次填写配方')
            for group, materials in [('主材',[('鲜鱼','1000','proportional')]),('腌肉',[('盐','6','fixed'),('白胡椒粉','0.3','proportional')])]:
                page.locator('[data-add-group]').click()
                card = page.locator('[data-recipe-group]').last
                card.get_by_label('环节名称', exact=True).fill(group)
                for name, amount, mode in materials:
                    card.locator('[data-add-ingredient]').click()
                    row = card.locator('.recipe-material').last
                    row.get_by_label('物料名称', exact=True).fill(name)
                    row.get_by_label('用量', exact=True).fill(amount)
                    row.locator('summary').click()
                    row.locator('[name=ingredient_mode]').select_option(mode)
                    row.get_by_label('备注', exact=True).fill('保留备注 ' + name)
            # Move an existing material between groups without retyping its data.
            card.locator('.recipe-material').last.get_by_label('所属环节', exact=True).select_option(label='主材')
            expect(card.locator('.recipe-material')).to_have_count(1)
            moved = page.locator('[data-recipe-group]').first.locator('.recipe-material').last
            expect(moved.get_by_label('备注', exact=True)).to_have_value('保留备注 白胡椒粉')
            moved.get_by_label('所属环节', exact=True).select_option(label='腌肉')
            expect(card.locator('.recipe-material')).to_have_count(2)
            # Rename and move an entire group without separating its materials.
            card.get_by_label('环节名称', exact=True).fill('腌制')
            card.get_by_role('button', name='上移环节', exact=True).click()
            expect(page.locator('[data-recipe-group]').first.locator('.recipe-material')).to_have_count(2)
            page.locator('[data-add-group]').click()
            empty = page.locator('[data-recipe-group]').last
            empty.locator('[data-add-ingredient]').click()
            empty.get_by_label('删除物料', exact=True).click()
            empty.get_by_label('删除环节', exact=True).click()
            page.locator('[data-add-step]').click()
            page.get_by_label('步骤标题', exact=True).fill('准备原料')
            page.get_by_label('方法原文', exact=True).fill('核对食材\n记录自己的操作过程')
            page.get_by_label('原理 / 备注原文', exact=True).fill('记录完成状态')
            page.get_by_role('button', name='保存为 V2', exact=True).click()
            expect(page).to_have_url(base + f'/life/recipes/{rid}')
            expect(page.get_by_role('heading', name='自建清汤鱼锅', exact=True)).to_be_visible()
            expect(page.locator('.v10-step-action').first).to_contain_text('记录自己的操作过程')
            page.locator('#v10TargetAmount').fill('2000')
            expect(page.locator('.v10-ingredient').filter(has_text='鲜鱼').locator('[data-scaled]')).to_have_text('2000')
            expect(page.locator('.v10-ingredient').filter(has_text='盐').locator('[data-scaled]')).to_have_text('6')
            page.goto(base + f'/life/recipes/{rid}/edit', wait_until='networkidle')
            cards = page.locator('[data-recipe-group]')
            expect(cards).to_have_count(2)
            expect(cards.first.get_by_label('环节名称', exact=True)).to_have_value('腌制')
            expect(cards.first.locator('.recipe-material')).to_have_count(2)
            expect(cards.first.locator('[name=ingredient_note]').first).to_have_value('保留备注 盐')
            expect(cards.first.locator('[name=ingredient_mode]').first).to_have_value('fixed')
            page.goto(base + '/life/recipes', wait_until='networkidle')
            page.get_by_label('搜索菜谱', exact=True).fill('个人试做')
            page.get_by_role('button', name='筛选', exact=True).click()
            expect(page.locator('.v10-recipe-line')).to_have_count(1)
            expect(page.locator('.v10-recipe-line')).to_contain_text('手动创建')
            page.reload(wait_until='networkidle')
            expect(page.locator('.v10-recipe-line')).to_contain_text('自建清汤鱼锅')
            directory = ROOT / 'artifacts/recipe-creation'
            directory.mkdir(parents=True, exist_ok=True)
            for width in [1440,390]:
                page.set_viewport_size({'width':width,'height':1000})
                for label, path in [('list','/life/recipes'),('new','/life/recipes/new'),('edit',f'/life/recipes/{rid}/edit')]:
                    page.goto(base + path, wait_until='networkidle')
                    page.evaluate('() => Promise.all(document.getAnimations().map(animation => animation.finished.catch(() => {})))')
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), (width, path)
                    if label == 'edit':
                        # Main material inputs stay on one row even on the phone.
                        dimensions = page.locator('.recipe-material-main').first.locator('input').evaluate_all('(inputs) => inputs.map(input => {const r = input.getBoundingClientRect(); return {top:r.top,width:r.width};})')
                        assert max(d['top'] for d in dimensions) - min(d['top'] for d in dimensions) < 2, dimensions
                        assert all(d['width'] > 35 for d in dimensions), dimensions
                        assert page.locator('.v10-sticky-save').bounding_box()['height'] < 90
                        row = page.locator('.recipe-material').first
                        assert row.bounding_box()['height'] <= 54, row.bounding_box()
                        assert page.locator('.v10-sticky-save').bounding_box()['height'] <= 58
                        assert row.get_by_label('物料名称', exact=True).evaluate('el => parseFloat(getComputedStyle(el).fontSize)') >= 16
                        # The compact settings entry has its own hit target, next to delete.
                        summary = row.locator('summary')
                        assert summary.evaluate('el => {const r=el.getBoundingClientRect(); return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}')
                        summary.click()
                        expect(row.locator('details')).to_have_attribute('open', '')
                        expect(row.get_by_role('combobox', name='用量方式', exact=True)).to_be_visible()
                        summary.click()
                    page.screenshot(path=str(directory / f'{label}-{width}.png'), full_page=True)
            page.goto(base + f'/life/recipes/{rid}/versions', wait_until='networkidle')
            expect(page.get_by_text('首次填写配方', exact=True)).to_be_visible()
            print_page = context.new_page()
            print_page.on('pageerror', lambda e: errors.append(str(e)))
            print_page.goto(base + f'/life/recipes/{rid}/print', wait_until='networkidle')
            expect(print_page.get_by_role('article', name='自建清汤鱼锅 A4菜谱', exact=True)).to_be_visible()
            expect(print_page.get_by_text('记录自己的操作过程', exact=False).first).to_be_visible()
            assert not errors, errors
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    print('manual recipe browser passed: life/new/edit/ingredients/steps/scale/search/reload/versions/print and desktop/mobile geometry')


if __name__ == '__main__':
    main()
