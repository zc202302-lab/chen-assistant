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
from app.security import create_session  # noqa: E402
from app.v032_customer_import_routes import (  # noqa: E402
    CONTACT_HEADERS,
    GROUP_HEADERS,
    PROMO_HEADERS,
    SERVICE_HEADERS,
)


def make_fixture(path: Path):
    workbook = xlsxwriter.Workbook(str(path))
    group = workbook.add_worksheet('集团')
    group.write_row(0, 0, GROUP_HEADERS)
    group.write_row(1, 0, ['G001', '浏览器导入集团甲', 'BATCH-001', '9137001001', '浏览器验收', '是'])
    group.write_row(2, 0, ['G002', '浏览器导入集团乙', 'BATCH-002', '9137001002', '', '是'])

    service = workbook.add_worksheet('业务')
    service.write_row(0, 0, SERVICE_HEADERS)
    service.write_row(1, 0, ['S001', 'G001', '成员', '测试成员', '15812340001', '533812340001', 40, '固定', '每月', '', '微信', '', '', '', '固定金额'])
    service.write_row(2, 0, ['S002', 'G001', '宽带', '后勤', '', '533812340002', 560, '变动', '每月', '', '转账', '', '', '', '变动金额'])
    service.write_row(3, 0, ['S003', 'G002', '专线', '', '', 'LINE-10001', 1200, '固定', '12个月', '2027-09', '', '', '', '2026-09-01', ''])

    contact = workbook.add_worksheet('联系人')
    contact.write_row(0, 0, CONTACT_HEADERS)
    contact.write_row(1, 0, ['G001', '关键联系人', '王经理', '财务', '13812340000'])

    promo = workbook.add_worksheet('优惠')
    promo.write_row(0, 0, PROMO_HEADERS)
    promo.write_row(1, 0, ['S001', '浏览器测试优惠', '2026-01-01', '2026-12-31', 60, ''])
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
    fixture = TEST_DIR / 'batch.xlsx'
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
            assert 'v0.3.2' in page.locator('.brand').inner_text()
            expect(page.get_by_role('link', name='Excel批量导入')).to_have_class('active')
            expect(page.get_by_role('link', name='下载 Excel 模板')).to_be_visible()

            with page.expect_download(timeout=5000) as download_info:
                page.get_by_role('link', name='下载 Excel 模板').click()
            download = download_info.value
            downloaded = TEST_DIR / 'downloaded-template.xlsx'
            download.save_as(str(downloaded))
            assert downloaded.read_bytes()[:2] == b'PK'

            page.locator('input[name="excel_file"]').set_input_files(str(fixture))
            page.get_by_role('button', name='上传并检查').click()
            expect(page.get_by_text('检查通过，等待你的最终确认')).to_be_visible(timeout=5000)
            metrics = page.locator('.v032-preview-metrics')
            expect(metrics).to_contain_text('2')
            expect(metrics).to_contain_text('3')
            expect(page.get_by_text('浏览器导入集团甲')).to_be_visible()
            expect(page.get_by_text('浏览器导入集团乙')).to_be_visible()

            page.get_by_role('button', name='确认导入全部数据').click()
            expect(page.get_by_text('批量导入完成')).to_be_visible(timeout=5000)
            expect(page.locator('.v032-success-panel')).to_contain_text('新增 2 个集团、3 条业务、1 个联系人、1 条优惠')

            with db() as conn:
                assert conn.execute('SELECT COUNT(*) n FROM customers').fetchone()['n'] == 2
                assert conn.execute('SELECT COUNT(*) n FROM services').fetchone()['n'] == 3
                fixed = conn.execute(
                    '''SELECT pe.confirmed,pe.source,r.mode,r.fixed_amount
                       FROM services s JOIN payment_entries pe ON pe.service_id=s.id
                       JOIN service_payment_rules r ON r.service_id=s.id
                       WHERE s.number='15812340001' LIMIT 1'''
                ).fetchone()
                assert fixed['confirmed'] == 1 and fixed['source'] == 'fixed' and fixed['mode'] == 'fixed'
                variable = conn.execute(
                    '''SELECT pe.confirmed,r.mode FROM services s
                       JOIN payment_entries pe ON pe.service_id=s.id
                       JOIN service_payment_rules r ON r.service_id=s.id
                       WHERE s.account='533812340002' LIMIT 1'''
                ).fetchone()
                assert variable['confirmed'] == 0 and variable['mode'] == 'variable'

            # Re-uploading the same batch must be stopped before a second write.
            page.locator('input[name="excel_file"]').set_input_files(str(fixture))
            page.get_by_role('button', name='上传并检查').click()
            expect(page.get_by_text('需要修正')).to_be_visible(timeout=5000)
            expect(page.locator('.v032-issue-block.danger')).to_contain_text('已存在')
            assert page.get_by_role('button', name='确认导入全部数据').count() == 0
            with db() as conn:
                assert conn.execute('SELECT COUNT(*) n FROM customers').fetchone()['n'] == 2

            browser.close()
        print('v0.3.2 customer batch import browser acceptance passed (isolated test database)')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
