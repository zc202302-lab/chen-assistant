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
    init_db(); ensure_v10_schema()
    token, _, _ = create_session()
    with db() as conn:
        recipe = conn.execute("SELECT * FROM recipes WHERE name='糖醋排骨'").fetchone()
        almond = conn.execute("SELECT * FROM recipes WHERE name='杏鲍菇'").fetchone()
        assert recipe and almond
        sugar_id = int(recipe['id']); mushroom_id = int(almond['id'])

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

            page.goto(f'http://127.0.0.1:8140/life/recipes/{sugar_id}', wait_until='networkidle')
            expect(page.get_by_role('heading', name='糖醋排骨')).to_be_visible()
            expect(page.get_by_text('当前标准 V1')).to_be_visible()
            salt = page.locator('.v10-ingredient').filter(has_text='盐').first
            expect(salt.locator('[data-scaled]')).to_have_text('2.5')
            page.locator('#v10TargetAmount').fill('1000')
            expect(salt.locator('[data-scaled]')).to_have_text('5')

            # Fixed ingredients must not scale with main weight.
            page.goto(f'http://127.0.0.1:8140/life/recipes/{mushroom_id}', wait_until='networkidle')
            garlic = page.locator('.v10-ingredient').filter(has_text='大蒜').first
            expect(garlic.locator('[data-scaled]')).to_have_text('3')
            page.locator('#v10TargetAmount').fill('720')
            expect(garlic.locator('[data-scaled]')).to_have_text('3')

            # Editing a standard creates V2; it never overwrites V1.
            page.goto(f'http://127.0.0.1:8140/life/recipes/{sugar_id}/edit', wait_until='networkidle')
            page.locator('input[name="change_summary"]').fill('白醋由15g验证到18g')
            vinegar_row = page.locator('.v10-edit-row').filter(has=page.locator('input[name="ingredient_name"][value="6度白醋"]')).first
            vinegar_row.locator('input[name="ingredient_amount"]').fill('18')
            page.get_by_role('button', name=re.compile('保存为 V2')).click()
            page.wait_for_url(f'**/life/recipes/{sugar_id}')
            expect(page.get_by_text('当前标准 V2')).to_be_visible()
            page.goto(f'http://127.0.0.1:8140/life/recipes/{sugar_id}/versions', wait_until='networkidle')
            expect(page.get_by_role('heading', name=re.compile('V2'))).to_be_visible()
            expect(page.get_by_role('heading', name=re.compile('V1'))).to_be_visible()

            # Start a real cook session at 600g and record a one-off adjustment.
            page.goto(f'http://127.0.0.1:8140/life/recipes/{sugar_id}', wait_until='networkidle')
            page.locator('#v10TargetAmount').fill('600')
            page.get_by_role('button', name='开始做饭').click()
            page.wait_for_url('**/life/cook/*')
            expect(page.get_by_text('1 / 5')).to_be_visible()
            option = page.locator('select[name="ingredient_id"] option').filter(has_text='6度白醋').first
            vinegar_value = option.get_attribute('value')
            assert vinegar_value
            page.locator('select[name="ingredient_id"]').select_option(vinegar_value)
            page.locator('input[name="actual_value"]').fill('24')
            page.locator('input[name="note"]').fill('这次想加强酸味')
            page.get_by_role('button', name='记录调整').click()
            page.wait_for_load_state('networkidle')
            expect(page.get_by_text('18', exact=False)).to_be_visible()
            expect(page.get_by_text('24', exact=False)).to_be_visible()

            for _ in range(4):
                page.get_by_role('button', name=re.compile('完成，下一步')).click()
                page.wait_for_load_state('networkidle')
            page.get_by_role('button', name='完成制作').click()
            page.wait_for_url('**/complete')
            page.locator('input[name="rating"]').fill('9')
            page.locator('textarea[name="notes"]').fill('酸味更清楚，整体成功')
            page.locator('textarea[name="next_change"]').fill('再验证一次白醋提高后的效果')
            page.get_by_role('button', name='保存制作记录').click()
            page.wait_for_url('**/life/records/*')
            expect(page.get_by_text('9/10')).to_be_visible()
            expect(page.get_by_text('18g')).to_be_visible()
            expect(page.get_by_text('24g')).to_be_visible()

            # Only explicitly selected adjustments are promoted to a new standard.
            page.locator('input[name="adjustment_id"]').check()
            page.get_by_role('button', name='创建新的标准版本').click()
            page.wait_for_url(f'**/life/recipes/{sugar_id}*')
            expect(page.get_by_text('当前标准 V3')).to_be_visible()
            browser.close()

    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill()

    with db() as conn:
        recipe = conn.execute('SELECT * FROM recipes WHERE id=?', (sugar_id,)).fetchone()
        versions = conn.execute('SELECT * FROM recipe_versions WHERE recipe_id=? ORDER BY version_no', (sugar_id,)).fetchall()
        assert [v['version_no'] for v in versions] == [1, 2, 3]
        amounts = []
        for v in versions:
            row = conn.execute("SELECT amount FROM recipe_ingredients WHERE version_id=? AND name='6度白醋'", (v['id'],)).fetchone()
            amounts.append(round(float(row['amount']), 4))
        # V1 preserved at 15; V2 manual standard at 18; 24g used at 600g is
        # normalized back to 20g at the 500g standard when promoted to V3.
        assert amounts == [15.0, 18.0, 20.0], amounts
        assert recipe['current_version_id'] == versions[-1]['id']
        assert conn.execute("SELECT COUNT(*) n FROM cook_sessions WHERE recipe_id=? AND status='completed'", (sugar_id,)).fetchone()['n'] == 1
    print('v1.0 browser acceptance passed: scale -> cook -> record -> promote -> immutable history')


if __name__ == '__main__':
    main()
