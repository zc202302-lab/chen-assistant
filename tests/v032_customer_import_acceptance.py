from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import xlsxwriter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v032-browser-')
TEST_DIR = Path(_TMPDIR.name)
TEST_DB = TEST_DIR / 'app.db'
os.environ['APP_DB_PATH'] = str(TEST_DB)
os.environ.update({
    'APP_USERNAME': 'ui-test',
    'APP_PASSWORD_SALT': 'dGVzdHNhbHQ=',
    'APP_PASSWORD_HASH': 'x',
    'APP_SESSION_SECRET': 'ui-test-session-secret',
    'APP_ENCRYPTION_KEY': 'x',
    'APP_SECURE_COOKIE': '0',
})

from app.db import db, init_db  # noqa: E402
from app.importer import XlsmReader  # noqa: E402
from app.security import create_session  # noqa: E402
from app.v028_routes import _template  # noqa: E402
from app.v032_customer_exchange_routes import _write_customer_sheet  # noqa: E402


def payload(name: str, code: str, number: str, amount: float, mode: str):
    return {
        'info': {
            'name': name, 'group_code': code, 'tax_id': '', 'relation_summary': '浏览器验收', 'payment_enabled': '是',
            'payment_display_attr_1': '类型', 'payment_display_attr_2': '姓名/属性',
            'mail_subject': f'{name}缴费', 'mail_body': '请处理', 'attachment_filename': f'{name}.txt',
            'employee_own': '', 'employee_share': '', 'leased_own': '', 'leased_other': '', 'other_status': '',
        },
        'entities': [], 'invoices': [],
        'businesses': [[
            'S001', '成员', '测试成员', number, '5338' + number[-6:], 1, '微信', '', '', '', '', '',
            amount, mode, '', '启用', '', '', '', 10,
        ]],
        'contacts': [['关键联系人', '王经理', '财务', '13812340000']],
        'promotions': [['S001', '浏览器测试优惠', '2026-01-01', '2026-12-31', 60, 'active', '']],
        'tasks': [['浏览器测试待办', '2026-09-30', '', '否']],
        'visits': [['2026-09-01', '拜访', '正常', '继续跟进']],
        'rules': [], 'payments': [], 'runs': [],
    }


def make_fixture(path: Path):
    with db() as conn:
        template = _template(conn)
    workbook = xlsxwriter.Workbook(str(path))
    _write_customer_sheet(workbook, workbook.add_worksheet('客户甲'), template, payload('浏览器导入客户甲', 'BATCH-001', '15812340001', 40, '固定'))
    _write_customer_sheet(workbook, workbook.add_worksheet('客户乙'), template, payload('浏览器导入客户乙', 'BATCH-002', '15812340002', 560, '变动'))
    workbook.close()


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
    init_db()
    token, _, _ = create_session()
    fixture = TEST_DIR / 'batch-one-sheet.xlsx'
    make_fixture(fixture)
    assert TEST_DB.resolve() != (ROOT / 'data' / 'app.db').resolve()

    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8139'],
        cwd=ROOT,
        env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8139/health')
        from playwright.sync_api import expect, sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8139'}])
            page = context.new_page()
            page.goto('http://127.0.0.1:8139/customers/new?mode=batch', wait_until='networkidle')
            assert 'v0.3.3' in page.locator('.brand').inner_text()
            expect(page.get_by_role('link', name='Excel批量导入/导出')).to_have_class('active')
            expect(page.get_by_role('link', name='下载最新 Excel 模板')).to_be_visible()
            expect(page.get_by_role('link', name='导出全部客户 Excel')).to_be_visible()

            with page.expect_download(timeout=5000) as download_info:
                page.get_by_role('link', name='下载最新 Excel 模板').click()
            template_download = TEST_DIR / 'downloaded-template.xlsx'
            download_info.value.save_as(str(template_download))
            template_reader = XlsmReader(template_download)
            assert len(template_reader.sheets) == 1 and template_reader.sheets[0][0] == '客户1'
            template_cells = template_reader.cells(template_reader.sheets[0][1])
            # Exchange format remains v0.3.2 for backward compatibility.
            assert template_cells.get('A1') == '晨的助手客户档案 v0.3.2'
            assert '【业务/产品】' in template_cells.values()

            page.locator('input[name="excel_file"]').set_input_files(str(fixture))
            page.get_by_role('button', name='上传并检查').click()
            expect(page.get_by_text('检查通过，等待最终确认')).to_be_visible(timeout=5000)
            expect(page.get_by_text('浏览器导入客户甲')).to_be_visible()
            expect(page.get_by_text('浏览器导入客户乙')).to_be_visible()

            page.get_by_role('button', name='确认导入全部客户').click()
            expect(page.get_by_text('批量导入完成')).to_be_visible(timeout=5000)
            expect(page.locator('.v032-success-panel')).to_contain_text('新增 2 个客户、2 条业务、2 个联系人、2 条优惠')

            with db() as conn:
                assert conn.execute('SELECT COUNT(*) n FROM customers').fetchone()['n'] == 2
                assert conn.execute('SELECT COUNT(*) n FROM services').fetchone()['n'] == 2
                fixed = conn.execute("SELECT pe.confirmed,pe.source FROM services s JOIN payment_entries pe ON pe.service_id=s.id WHERE s.number='15812340001' LIMIT 1").fetchone()
                variable = conn.execute("SELECT pe.confirmed,pe.source FROM services s JOIN payment_entries pe ON pe.service_id=s.id WHERE s.number='15812340002' LIMIT 1").fetchone()
                assert fixed['confirmed'] == 1 and fixed['source'] == 'fixed'
                assert variable['confirmed'] == 0

            with page.expect_download(timeout=8000) as export_info:
                page.get_by_role('link', name='导出全部客户 Excel').click()
            exported = TEST_DIR / 'all-customers.xlsx'
            export_info.value.save_as(str(exported))
            exported_reader = XlsmReader(exported)
            assert {name for name, _ in exported_reader.sheets} == {'浏览器导入客户甲', '浏览器导入客户乙'}
            all_values = []
            for _, sheet_path in exported_reader.sheets:
                all_values.extend(exported_reader.cells(sheet_path).values())
            assert '浏览器测试待办' in all_values
            assert '继续跟进' in all_values
            assert '浏览器测试优惠' in all_values

            # Re-uploading the same clients must be stopped before any second write.
            page.locator('input[name="excel_file"]').set_input_files(str(fixture))
            page.get_by_role('button', name='上传并检查').click()
            expect(page.get_by_text('需要修正')).to_be_visible(timeout=5000)
            expect(page.locator('.v032-issue-block.danger')).to_contain_text('已存在')
            assert page.get_by_role('button', name='确认导入全部客户').count() == 0
            with db() as conn:
                assert conn.execute('SELECT COUNT(*) n FROM customers').fetchone()['n'] == 2

            browser.close()
        print('v0.3.3 app + v0.3.2 one-customer-per-sheet import/export browser acceptance passed (isolated database)')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
