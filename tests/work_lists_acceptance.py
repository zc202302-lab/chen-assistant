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
TMP = tempfile.TemporaryDirectory(prefix='chen-work-lists-ui-')
os.environ.update(APP_DB_PATH=str(Path(TMP.name) / 'app.db'), APP_USERNAME='lists-ui',
                  APP_PASSWORD_SALT='dGVzdHNhbHQ=', APP_PASSWORD_HASH='x',
                  APP_SESSION_SECRET='lists-ui-session', APP_ENCRYPTION_KEY=Fernet.generate_key().decode(), APP_SECURE_COOKIE='0')
from app.db import db, init_db, now_iso  # noqa: E402
from app.security import create_session  # noqa: E402


def main():
    init_db()
    with db() as conn:
        now = now_iso()
        conn.execute('INSERT INTO customers(name,source_sheet,created_at,updated_at) VALUES(?,?,?,?)', ('验收客户', 'lists-ui', now, now))
    token, _, _ = create_session()
    base = 'http://127.0.0.1:8167'
    proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8167'], cwd=ROOT, env=os.environ.copy())
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
            context = browser.new_context(viewport={'width': 1440, 'height': 900}, accept_downloads=True)
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': base}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/work', wait_until='networkidle')
            page.locator('.work-entry-grid a[href="/work/lists"]').click()
            expect(page.get_by_role('heading', name='清单', exact=True)).to_be_visible()
            for width, height in [(1440, 900), (390, 844)]:
                page.set_viewport_size({'width': width, 'height': height})
                page.goto(base + '/work/lists', wait_until='networkidle')
                expect(page.locator('.wl-section-nav [aria-current=page]')).to_have_text('我的清单')
                expect(page.locator('input[name=title]')).to_have_count(0)
                expect(page.get_by_label('搜索清单', exact=True)).to_be_visible()
                expect(page.get_by_role('link', name='从 Excel 导入')).to_have_count(0)
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                page.get_by_role('link', name='新建清单', exact=True).click()
                expect(page.locator('.wl-section-nav [aria-current=page]')).to_have_text('新建清单')
                expect(page.get_by_label('清单名称', exact=True)).to_be_visible()
                expect(page.get_by_role('link', name='从 Excel 导入')).to_be_visible()
                expect(page.locator('.ws-grid tbody tr')).to_have_count(4)
                expect(page.locator('.ws-header-input')).to_have_count(3)
                expect(page.get_by_label('搜索清单', exact=True)).to_have_count(0)
                expect(page.locator('.wl-grid')).to_have_count(0)
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.set_viewport_size({'width': 1440, 'height': 900})
            page.locator('input[name=title]').fill('9月欠费清单')
            page.get_by_text('按字段模板创建', exact=True).click()
            page.locator('select[name=preset]').select_option('arrears')
            page.get_by_role('button', name='创建清单').click()
            expect(page.get_by_role('heading', name='9月欠费清单')).to_be_visible()
            list_url = page.url
            page.get_by_text('记录详情', exact=True).click()
            page.get_by_role('link', name='新增记录').click()
            page.locator('select[name=customer_id]').select_option(label='验收客户')
            page.get_by_label('项目 / 号码').fill('00123456789')
            page.get_by_label('欠费金额').fill('250.50')
            page.get_by_label('截止日期').fill('2026-10-10')
            page.get_by_label('处理进度').select_option(label='已联系')
            page.get_by_label('备注', exact=True).fill('电话沟通，等待回款')
            page.get_by_role('button', name='保存记录').click()
            expect(page.locator('.wl-table tbody tr')).to_have_count(1)
            expect(page.locator('.wl-table tbody tr td').first).to_have_text('1')
            expect(page.get_by_role('link', name='验收客户', exact=True)).to_be_visible()
            page.get_by_role('link', name='编辑', exact=True).click()
            page.get_by_label('记录状态').select_option('done')
            page.get_by_role('button', name='保存记录').click()
            page.get_by_label('记录状态').select_option('pending')
            page.get_by_role('button', name='筛选', exact=True).click()
            expect(page.get_by_text('暂无符合条件的记录。')).to_be_visible()
            page.get_by_role('link', name='重置', exact=True).click()
            page.get_by_label('搜索记录').fill('回款')
            page.get_by_role('button', name='筛选', exact=True).click()
            expect(page.get_by_text('00123456789', exact=True)).to_be_visible()
            with page.expect_download() as info:
                page.get_by_role('link', name='导出当前结果 Excel').click()
            assert info.value.suggested_filename.endswith('.xlsx')
            assert Path(info.value.path()).stat().st_size > 1000
            page.get_by_role('link', name='清单设置', exact=True).click()
            page.get_by_label('字段1名称', exact=True).fill('业务号码')
            page.get_by_role('button', name='保存设置').click()
            expect(page.get_by_role('columnheader', name='业务号码', exact=True)).to_be_visible()
            expect(page.get_by_text('00123456789', exact=True)).to_be_visible()
            page.get_by_role('link', name='清单设置', exact=True).click()
            page.get_by_label('字段名称', exact=True).fill('关注标签')
            page.get_by_label('字段类型', exact=True).select_option('multi')
            page.get_by_label('选项（单选 / 多选时填写，一行一个）', exact=True).fill('重要\n本周跟进')
            page.get_by_role('button', name='添加字段').click()
            page.get_by_role('link', name='返回清单', exact=True).click()
            page.get_by_role('link', name='编辑', exact=True).click()
            page.get_by_label('重要', exact=True).check()
            page.get_by_label('本周跟进', exact=True).check()
            page.get_by_role('button', name='保存记录').click()
            expect(page.get_by_text('重要、本周跟进', exact=True)).to_be_visible()
            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(list_url, wait_until='networkidle')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2'), 'mobile page must not overflow'
            page.get_by_role('link', name='编辑', exact=True).click()
            expect(page.get_by_role('button', name='保存记录')).to_be_visible()
            page.get_by_role('link', name='取消', exact=True).click()
            page.get_by_role('link', name='清单设置', exact=True).click()
            page.get_by_role('button', name='归档清单', exact=True).click()
            page.get_by_role('link', name='已归档清单', exact=True).click()
            page.locator('.wl-card').filter(has_text='9月欠费清单').click()
            expect(page.get_by_role('link', name='新增记录')).to_have_count(0)
            page.get_by_role('link', name='清单设置', exact=True).click()
            page.get_by_role('button', name='恢复清单', exact=True).click()
            page.locator('.wl-card').filter(has_text='9月欠费清单').click()
            expect(page.get_by_text('00123456789', exact=True)).to_be_visible()
            # Chromium reports native cross-document transition cancellation as
            # pageerror when navigating between opt-in documents or resizing.
            # These exact lifecycle messages do not indicate a script failure;
            # every other page error remains a test failure.
            transition_cancellations = {
                'Transition was aborted because of invalid state. ViewTransition opt-in disabled',
                'Transition was aborted because of invalid state. Viewport size changed',
            }
            script_errors = [error for error in errors if error not in transition_cancellations]
            assert not script_errors, script_errors
            browser.close()
        print('work lists browser acceptance passed: create, customer, edit, filter, export, fields, mobile, archive/restore')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()

