from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v12-browser-')
os.environ['APP_DB_PATH'] = str(Path(_TMPDIR.name) / 'app.db')
os.environ.update({'APP_USERNAME':'晨','APP_PASSWORD_SALT':'dGVzdHNhbHQ=','APP_PASSWORD_HASH':'x','APP_SESSION_SECRET':'v12-browser-session','APP_ENCRYPTION_KEY':'x','APP_SECURE_COOKIE':'0'})

from app import config  # noqa: E402
from app.db import db, init_db  # noqa: E402
from app.security import create_session  # noqa: E402
from app.v101_recipe_template_data import TEMPLATE_SHEET_NAMES  # noqa: E402
from app.v101_recipe_template_patch import ensure_v101_recipe_templates  # noqa: E402


def wait_http(url):
    for _ in range(100):
        try:
            if urllib.request.urlopen(url, timeout=1).status == 200: return
        except Exception: pass
        time.sleep(.2)
    raise RuntimeError('server start failed')


def main():
    init_db(); ensure_v101_recipe_templates()
    token, _, _ = create_session()
    with db() as conn:
        rows = conn.execute('SELECT id,name FROM recipes WHERE name IN (%s)' % ','.join('?' * len(TEMPLATE_SHEET_NAMES)), TEMPLATE_SHEET_NAMES).fetchall()
        ids = {r['name']: int(r['id']) for r in rows}
        assert len(ids) == 18
    proc = subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8142'],cwd=ROOT,env=os.environ.copy())
    try:
        wait_http('http://127.0.0.1:8142/health')
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1400, 'height': 950})
            context.add_cookies([{'name':'session_token','value':token,'url':'http://127.0.0.1:8142'}])
            page = context.new_page()
            page.goto('http://127.0.0.1:8142/life/recipes', wait_until='networkidle')
            expect(page.locator('.brand')).to_contain_text(f'v{config.APP_VERSION}')
            assert [x.strip() for x in page.locator('.bottom-nav .nav-item span').all_inner_texts()] == ['生活','菜谱','工具']
            for name in TEMPLATE_SHEET_NAMES:
                expect(page.get_by_text(name, exact=True).first).to_be_visible()

            rid = ids['糖醋排骨']
            page.goto(f'http://127.0.0.1:8142/life/recipes/{rid}', wait_until='networkidle')
            expect(page.get_by_text('开始做饭', exact=True)).to_have_count(0)
            expect(page.get_by_text('打印 A4', exact=True)).to_be_visible()
            raw = page.locator('.v10-step-action').first.text_content() or ''
            assert raw.startswith('1.排骨：500g\n2.焯水：冷水下锅')

            page.goto('http://127.0.0.1:8142/life/tools', wait_until='networkidle')
            expect(page.get_by_role('heading', name='基础知识 · 计算工具')).to_be_visible()
            expect(page.locator('[data-v12-out="total"]')).to_have_text('4.2 g')
            expect(page.locator('[data-v12-out="base"]')).to_have_text('1.26 g')
            expect(page.locator('[data-v12-out="add"]')).to_have_text('2.94 g')
            page.locator('#v12SaltWeight').fill('500')
            expect(page.locator('[data-v12-out="total"]')).to_have_text('6 g')
            page.locator('#v12SauceWeight').fill('1000')
            expect(page.locator('[data-v12-sauce-results]')).to_contain_text('188 g')
            page.locator('#v12TechniqueType').select_option('宫保')
            expect(page.locator('[data-v12-technique-note]')).to_contain_text('负的老抽比例')

            page.emulate_media(media='print')
            page.goto(f'http://127.0.0.1:8142/life/recipes/{rid}/print', wait_until='networkidle')
            grid = page.locator('.excel-recipe-grid')
            expect(grid).to_be_visible()
            assert page.locator('.excel-recipe-grid tr').count() == 15
            assert page.locator('.excel-ingredient-row').count() == 9
            assert page.locator('.excel-section-header-row').count() == 2
            assert page.locator('.excel-step-row').count() == 4
            expect(page.locator('.recipe-print-head')).to_have_count(0)
            expect(page.locator('.excel-ingredient-row').first.locator('th')).to_have_text(['主材', '备注'])
            expect(page.locator('.excel-ingredient-row').first.locator('td').nth(0)).to_have_text('排骨')
            expect(page.locator('.excel-ingredient-row').first.locator('td').nth(1)).to_have_text('500')
            expect(page.locator('.excel-ingredient-row').nth(1).locator('th')).to_have_text('糖色')
            expect(page.locator('.excel-step-row').first.locator('th')).to_have_text('主材准备')
            expect(page.locator('.excel-step-row').first.locator('.excel-step-method')).to_contain_text('1.排骨：500g')
            box = grid.bounding_box()
            assert box
            assert abs(box['width'] - 649.7) <= 3, box
            assert abs(box['height'] - 914.8) <= 4, box
            pdf = page.pdf(print_background=True, prefer_css_page_size=True)
            pages = len(re.findall(rb'/Type\\s*/Page(?!s)\\b', pdf))
            assert pages == 1, pages
            browser.close()
        print('recipe tools browser acceptance passed: Excel-grid recipe print + original text + formula tools + one-page A4')
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill()

if __name__ == '__main__': main()
