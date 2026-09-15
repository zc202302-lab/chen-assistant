from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = tempfile.TemporaryDirectory(prefix='chen-v13-documents-')
BASE = Path(TMP.name)
TEST_DB = BASE / 'qingdao' / 'app.db'
REMOTE_ROOT = BASE / 'racknerd-files'
SOURCE_FILE = BASE / '营业执照测试.txt'
SOURCE_CONTENT = '晨的助手 v1.3 远程资料存储测试\ncustomer-document-content\n'.encode('utf-8')
SOURCE_FILE.write_bytes(SOURCE_CONTENT)

os.environ.update({
    'APP_DB_PATH': str(TEST_DB),
    'APP_USERNAME': 'ui-test',
    'APP_PASSWORD_SALT': 'dGVzdHNhbHQ=',
    'APP_PASSWORD_HASH': 'x',
    'APP_SESSION_SECRET': 'ui-test-session-secret',
    'APP_ENCRYPTION_KEY': 'x',
    'APP_SECURE_COOKIE': '0',
    'REMOTE_STORAGE_BASE_URL': 'http://127.0.0.1:8152',
    'REMOTE_STORAGE_TOKEN': 'v13-test-token',
    'REMOTE_STORAGE_MAX_FILE_MB': '50',
})

from app.db import db, init_db, now_iso  # noqa: E402
from app.security import create_session  # noqa: E402


def seed():
    init_db()
    now = now_iso()
    with db() as conn:
        cid = int(conn.execute(
            'INSERT INTO customers(name,group_code,payment_enabled,created_at,updated_at) VALUES(?,?,?,?,?)',
            ('远程资料测试客户', 'DOC-V13', 0, now, now),
        ).lastrowid)
    token, _, _ = create_session()
    return cid, token


def wait_http(url: str):
    for _ in range(120):
        try:
            if urllib.request.urlopen(url, timeout=1).status == 200:
                return
        except Exception:
            pass
        time.sleep(.2)
    raise RuntimeError(f'server start failed: {url}')


def main():
    cid, token = seed()
    storage_env = os.environ.copy()
    storage_env.update({
        'CHEN_STORAGE_ROOT': str(REMOTE_ROOT),
        'CHEN_STORAGE_TOKEN': 'v13-test-token',
        'CHEN_STORAGE_MAX_FILE_MB': '50',
    })
    storage_proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'storage_node.app:app', '--host', '127.0.0.1', '--port', '8152'],
        cwd=ROOT, env=storage_env,
    )
    app_proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8153'],
        cwd=ROOT, env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8152/health')
        wait_http('http://127.0.0.1:8153/health')
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1500, 'height': 1000}, accept_downloads=True)
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8153'}])
            page = context.new_page()
            page.goto(f'http://127.0.0.1:8153/customers/{cid}', wait_until='networkidle')

            documents_tab = page.locator('[data-customer-tab="documents"]')
            expect(documents_tab).to_be_visible(timeout=5000)
            documents_tab.click()
            expect(page.locator('[data-customer-panel="documents"]')).to_be_visible()
            expect(page.locator('[data-v13-storage-state]')).to_contain_text('美国节点', timeout=5000)

            # v1.4.3: customer "资料" is not file-only. Free-form records can store
            # account names, URLs and other text, and their type is user-defined.
            resource_form = page.locator('[data-v143-resource-form]')
            expect(resource_form).to_be_visible(timeout=5000)
            resource_form.locator('input[name="resource_type"]').fill('客户后台网址')
            resource_form.locator('input[name="name"]').fill('集团业务系统')
            resource_form.locator('textarea[name="value"]').fill('https://example.com/customer/login')
            resource_form.locator('input[name="note"]').fill('客户专属入口')
            resource_form.locator('[data-v143-resource-save]').click()
            expect(page.locator('[data-v143-resource-id]')).to_have_count(1, timeout=5000)
            expect(page.locator('[data-v143-resource-id]')).to_contain_text('客户后台网址')
            expect(page.locator('[data-v143-resource-id]')).to_contain_text('集团业务系统')
            expect(page.locator('[data-v143-resource-id]')).to_contain_text('https://example.com/customer/login')
            expect(page.locator('[data-v143-resource-id] a', has_text='打开')).to_have_count(1)

            page.locator('[data-v143-resource-edit]').click()
            resource_form.locator('input[name="resource_type"]').fill('账号入口')
            resource_form.locator('input[name="name"]').fill('集团系统账号入口')
            resource_form.locator('[data-v143-resource-save]').click()
            expect(page.locator('[data-v143-resource-id]')).to_contain_text('账号入口', timeout=5000)
            expect(page.locator('[data-v143-resource-id]')).to_contain_text('集团系统账号入口')

            with db() as conn:
                resource = conn.execute(
                    'SELECT resource_type,name,value,note FROM customer_resource_items_v143 WHERE customer_id=?',
                    (cid,),
                ).fetchone()
                assert resource is not None
                assert resource['resource_type'] == '账号入口'
                assert resource['name'] == '集团系统账号入口'
                assert resource['value'] == 'https://example.com/customer/login'
                assert resource['note'] == '客户专属入口'

            # File type is also free-form rather than a fixed category selector.
            file_type = page.locator('[data-v13-upload] input[name="category"]')
            expect(file_type).to_be_visible()
            file_type.fill('客户自定义证照')
            page.locator('[data-v13-upload] input[type="file"]').set_input_files(str(SOURCE_FILE))
            page.locator('[data-v13-upload-button]').click()
            expect(page.locator('.v13-doc-row')).to_have_count(1, timeout=8000)
            expect(page.locator('.v13-doc-row')).to_contain_text('营业执照测试.txt')
            expect(page.locator('.v13-doc-row')).to_contain_text('客户自定义证照')

            remote_files = [p for p in REMOTE_ROOT.iterdir() if p.is_file() and not p.name.startswith('.')]
            assert len(remote_files) == 1, remote_files
            assert remote_files[0].read_bytes() == SOURCE_CONTENT
            assert len(remote_files[0].name) == 32

            with db() as conn:
                row = conn.execute(
                    'SELECT original_name,category,size,sha256,storage_key FROM customer_documents WHERE customer_id=?',
                    (cid,),
                ).fetchone()
                assert row is not None
                assert row['original_name'] == '营业执照测试.txt'
                assert row['category'] == '客户自定义证照'
                assert int(row['size']) == len(SOURCE_CONTENT)
                assert row['storage_key'] == remote_files[0].name

            with page.expect_download(timeout=8000) as download_info:
                page.locator('.v13-doc-download').click()
            download = download_info.value
            assert download.suggested_filename == '营业执照测试.txt'
            downloaded = download.path()
            assert downloaded and Path(downloaded).read_bytes() == SOURCE_CONTENT

            page.once('dialog', lambda dialog: dialog.accept())
            page.locator('[data-v13-delete]').click()
            expect(page.locator('.v13-doc-row')).to_have_count(0, timeout=8000)
            assert not [p for p in REMOTE_ROOT.iterdir() if p.is_file() and not p.name.startswith('.')]
            with db() as conn:
                assert conn.execute('SELECT COUNT(*) n FROM customer_documents WHERE customer_id=?', (cid,)).fetchone()['n'] == 0

            page.once('dialog', lambda dialog: dialog.accept())
            page.locator('[data-v143-resource-delete]').click()
            expect(page.locator('[data-v143-resource-id]')).to_have_count(0, timeout=5000)
            with db() as conn:
                assert conn.execute('SELECT COUNT(*) n FROM customer_resource_items_v143 WHERE customer_id=?', (cid,)).fetchone()['n'] == 0

            browser.close()
        print('v1.3/v1.4.3 customer resources acceptance passed: freeform info + custom file type + remote file lifecycle')
    finally:
        for proc in (app_proc, storage_proc):
            proc.terminate()
        for proc in (app_proc, storage_proc):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == '__main__':
    main()
