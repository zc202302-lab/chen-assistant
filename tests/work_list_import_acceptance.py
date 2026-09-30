from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = tempfile.TemporaryDirectory(prefix='chen-import-ui-')
os.environ.update(APP_DB_PATH=str(Path(TMP.name) / 'app.db'), APP_USERNAME='import-ui', APP_PASSWORD_SALT='dGVzdHNhbHQ=',
                  APP_PASSWORD_HASH='x', APP_SESSION_SECRET='import-ui', APP_ENCRYPTION_KEY=Fernet.generate_key().decode(), APP_SECURE_COOKIE='0')
from app.db import db, init_db, now_iso  # noqa: E402
from app.security import create_session  # noqa: E402


def main():
    from work_list_import_fixtures import workbook
    init_db()
    with db() as conn:
        now = now_iso()
        conn.execute('INSERT INTO customers(name,source_sheet,created_at,updated_at) VALUES(?,?,?,?)', ('导入客户', 'import-ui', now, now))
    token, _, _ = create_session()
    base = 'http://127.0.0.1:8168'
    proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8168'], cwd=ROOT, env=os.environ.copy())
    try:
        for _ in range(100):
            try:
                if urllib.request.urlopen(base + '/health', timeout=1).status == 200:
                    break
            except Exception:
                pass
            time.sleep(.2)
        else:
            raise RuntimeError('server start failed')
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1440, 'height': 900})
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': base}])
            page = context.new_page()
            page.goto(base + '/work/lists', wait_until='networkidle')
            page.get_by_role('link', name='从 Excel 导入').click()
            page.get_by_label('Excel 文件').set_input_files({'name': '欠费.xlsx', 'mimeType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'buffer': workbook()})
            page.get_by_role('button', name='上传并选择范围').click()
            page.get_by_label('工作表', exact=True).select_option(label='欠费明细')
            page.get_by_label('开始列', exact=True).fill('D')
            page.get_by_label('结束列（可选）', exact=True).fill('H')
            page.get_by_label('新清单名称（选择新建时使用）', exact=True).fill('导入验收欠费')
            page.get_by_role('button', name='读取所选范围').click()
            expect(page.get_by_role('heading', name='匹配字段')).to_be_visible()
            page.get_by_label('E列新字段类型', exact=True).select_option('money')
            page.get_by_label('F列新字段类型', exact=True).select_option('date')
            page.get_by_label('G列导入到', exact=True).select_option('customer_name')
            page.get_by_label('H列导入到', exact=True).select_option('note')
            page.get_by_role('button', name='检查数据并预览导入').click()
            expect(page.get_by_text('将新增 2 条，跳过 1 条完全重复记录。', exact=True)).to_be_visible()
            with db() as conn:
                assert conn.execute('SELECT COUNT(*) FROM work_list_records').fetchone()[0] == 0
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
            page.get_by_role('button', name='确认导入 2 条', exact=True).click()
            expect(page.get_by_role('heading', name='导入完成')).to_be_visible()
            page.get_by_role('link', name='查看清单', exact=True).click()
            expect(page.get_by_role('heading', name='导入验收欠费')).to_be_visible()
            expect(page.get_by_text('000123', exact=True)).to_be_visible()
            expect(page.locator('.wl-table tbody tr')).to_have_count(2)
            with db() as conn:
                list_id = conn.execute('SELECT id FROM work_lists').fetchone()[0]
            page.get_by_role('link', name='Excel 导入', exact=True).click()
            expect(page.get_by_label('导入目标', exact=True)).to_have_value(str(list_id))
            page.get_by_label('Excel 文件').set_input_files({'name': '再次.xlsx', 'mimeType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'buffer': workbook()})
            page.get_by_role('button', name='上传并选择范围').click()
            page.get_by_label('工作表', exact=True).select_option(label='欠费明细')
            page.get_by_label('开始列', exact=True).fill('D')
            page.get_by_label('结束列（可选）', exact=True).fill('H')
            page.get_by_role('button', name='读取所选范围').click()
            page.get_by_label('G列导入到', exact=True).select_option('customer_name')
            page.get_by_label('H列导入到', exact=True).select_option('note')
            page.get_by_role('button', name='检查数据并预览导入').click()
            expect(page.get_by_text('将新增 0 条，跳过 3 条完全重复记录。', exact=True)).to_be_visible()
            page.get_by_role('button', name='确认导入 0 条', exact=True).click()
            with db() as conn:
                assert conn.execute('SELECT COUNT(*) FROM work_list_records').fetchone()[0] == 2
            browser.close()
        print('Excel import browser acceptance passed: upload, sheet/range, mapping, no premature writes, mobile confirmation, customer linkage, repeat import')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
