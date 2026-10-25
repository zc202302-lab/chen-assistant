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
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v10-browser-')
TEST_DB = Path(_TMPDIR.name) / 'app.db'
os.environ['APP_DB_PATH'] = str(TEST_DB)
os.environ.update({
    'APP_USERNAME': '晨',
    'APP_PASSWORD_SALT': 'dGVzdHNhbHQ=',
    'APP_PASSWORD_HASH': 'x',
    'APP_SESSION_SECRET': 'v10-browser-session',
    'APP_ENCRYPTION_KEY': 'x',
    'APP_SECURE_COOKIE': '0',
})

from app.db import db, init_db  # noqa: E402
from app.security import create_session  # noqa: E402
from app.v10_routes import ensure_v10_schema  # noqa: E402
from app.v101_recipe_template_data import TEMPLATE_IMPORT_MARKER, TEMPLATE_SHEET_NAMES  # noqa: E402
from app.v101_recipe_template_patch import ensure_v101_recipe_templates  # noqa: E402


def wait_http(url: str):
    for _ in range(100):
        try:
            if urllib.request.urlopen(url, timeout=1).status == 200:
                return
        except Exception:
            pass
        time.sleep(.2)
    raise RuntimeError('server start failed')


def main():
    init_db(); ensure_v10_schema(); ensure_v101_recipe_templates()
    token, _, _ = create_session()
    with db() as conn:
        template_rows = conn.execute(
            '''SELECT r.id,r.name,r.current_version_id FROM recipes r
               WHERE r.name IN (%s) ORDER BY r.name''' % ','.join('?' * len(TEMPLATE_SHEET_NAMES)),
            TEMPLATE_SHEET_NAMES,
        ).fetchall()
        assert len(template_rows) == 18, [r['name'] for r in template_rows]
        recipe_ids = {r['name']: int(r['id']) for r in template_rows}
        sugar_id = recipe_ids['糖醋排骨']
        fish_id = recipe_ids['红烧鲈鱼']
        sugar = conn.execute('SELECT * FROM recipes WHERE id=?', (sugar_id,)).fetchone()
        imported = conn.execute('SELECT * FROM recipe_versions WHERE id=?', (sugar['current_version_id'],)).fetchone()
        assert imported['change_summary'].startswith(TEMPLATE_IMPORT_MARKER)
        imported_version_no = int(imported['version_no'])
        assert imported_version_no == 2

    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8140'],
        cwd=ROOT, env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8140/health')
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1450, 'height': 950})
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8140'}])
            page = context.new_page()

            page.goto('http://127.0.0.1:8140/', wait_until='networkidle')
            expect(page.locator('.brand')).to_contain_text('v1.0')
            expect(page.get_by_text('工作空间', exact=True)).to_be_visible()
            expect(page.get_by_text('生活空间', exact=True)).to_be_visible()

            page.goto('http://127.0.0.1:8140/life/recipes', wait_until='networkidle')
            for name in TEMPLATE_SHEET_NAMES:
                expect(page.get_by_text(name, exact=True).first).to_be_visible()

            page.goto(f'http://127.0.0.1:8140/life/recipes/{sugar_id}', wait_until='networkidle')
            expect(page.get_by_role('heading', name='糖醋排骨', exact=True)).to_be_visible()
            expect(page.get_by_text(f'当前标准 V{imported_version_no}')).to_be_visible()
            expect(page.get_by_text('打印 A4', exact=True)).to_be_visible()
            expect(page.get_by_text('开始做饭', exact=True)).to_have_count(0)
            expect(page.get_by_text('沿用 Excel 原始文本', exact=True)).to_be_visible()
            step1 = page.locator('.v10-step-action').first
            raw = step1.text_content() or ''
            assert raw == (
                '1.排骨：500g\n'
                '2.焯水：冷水下锅，葱段，姜片，料酒，开锅后2分钟捞出，凉水洗去浮沫\n'
                '3.擦干：尽可能擦干水分，晾干'
            ), repr(raw)
            expect(page.get_by_text('3.火不要大，容易糊锅', exact=True)).to_be_visible()

            salt = page.locator('.v10-ingredient').filter(has_text='盐').first
            expect(salt.locator('[data-scaled]')).to_have_text('2.5')
            page.locator('#v10TargetAmount').fill('1000')
            expect(salt.locator('[data-scaled]')).to_have_text('5')

            page.goto(f'http://127.0.0.1:8140/life/recipes/{fish_id}', wait_until='networkidle')
            expect(page.get_by_role('heading', name='红烧鲈鱼', exact=True)).to_be_visible()
            expect(page.locator('.v10-step-action').first).to_contain_text('鲈鱼：一条540g')
            expect(page.get_by_text('1.擦干有助于腌肉', exact=False)).to_be_visible()
            expect(page.get_by_text('开始做饭', exact=True)).to_have_count(0)

            response = context.request.post(
                f'http://127.0.0.1:8140/life/recipes/{sugar_id}/cook/start',
                max_redirects=0,
            )
            assert response.status == 303, response.status
            assert response.headers.get('location') == f'/life/recipes/{sugar_id}'

            page.goto(f'http://127.0.0.1:8140/life/recipes/{sugar_id}/edit', wait_until='networkidle')
            expect(page.get_by_text('沿用 Excel 的“步骤 / 方法 / 原理”原始文本，不强制拆成火力、时间等字段。', exact=True)).to_be_visible()
            expect(page.locator('input[name="step_heat"][type="hidden"]').first).to_have_count(1)
            next_no = imported_version_no + 1
            page.locator('input[name="change_summary"]').fill('白醋由15g验证到18g')
            vinegar_row = page.locator('.v10-edit-row').filter(has=page.locator('input[name="ingredient_name"][value="6度白醋"]')).first
            vinegar_row.locator('input[name="ingredient_amount"]').fill('18')
            page.get_by_role('button', name='保存菜谱').click()
            page.wait_for_url(f'**/life/recipes/{sugar_id}')
            expect(page.get_by_text(f'当前标准 V{next_no}')).to_be_visible()
            expect(page.get_by_text('开始做饭', exact=True)).to_have_count(0)

            page.emulate_media(media='print')
            for name in TEMPLATE_SHEET_NAMES:
                recipe_id = recipe_ids[name]
                page.goto(f'http://127.0.0.1:8140/life/recipes/{recipe_id}/print', wait_until='networkidle')
                expect(page.get_by_role('heading', name=name, exact=True)).to_be_visible()
                sheet = page.locator('.recipe-print-sheet')
                dims = sheet.evaluate('el => ({scroll: el.scrollHeight, client: el.clientHeight})')
                assert dims['scroll'] <= dims['client'] + 2, (name, dims)
                pdf = page.pdf(print_background=True, prefer_css_page_size=True)
                page_count = len(re.findall(rb'/Type\s*/Page(?!s)\b', pdf))
                assert page_count == 1, (name, page_count, len(pdf))
            page.emulate_media(media='screen')

            browser.close()

    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill()

    with db() as conn:
        sugar = conn.execute('SELECT * FROM recipes WHERE id=?', (sugar_id,)).fetchone()
        versions = conn.execute('SELECT * FROM recipe_versions WHERE recipe_id=? ORDER BY version_no', (sugar_id,)).fetchall()
        assert len(versions) == 3 and versions[-1]['version_no'] == 3, [v['version_no'] for v in versions]
        imported = next(v for v in versions if v['change_summary'].startswith(TEMPLATE_IMPORT_MARKER))
        old_vinegar = conn.execute("SELECT amount FROM recipe_ingredients WHERE version_id=? AND name='6度白醋'", (imported['id'],)).fetchone()['amount']
        new_vinegar = conn.execute("SELECT amount FROM recipe_ingredients WHERE version_id=? AND name='6度白醋'", (versions[-1]['id'],)).fetchone()['amount']
        assert float(old_vinegar) == 15.0
        assert float(new_vinegar) == 18.0
        assert sugar['current_version_id'] == versions[-1]['id']
        assert conn.execute('SELECT COUNT(*) n FROM cook_sessions').fetchone()['n'] == 0
    print('v1.0 browser acceptance passed: Excel template import -> original text -> no cook mode -> one-page A4 print')


if __name__ == '__main__':
    main()
