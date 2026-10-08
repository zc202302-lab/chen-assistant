"""Browser workflow, including upload, duplicate-click suppression and local errors."""
import http.client
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from cryptography.fernet import Fernet

os.environ['APP_ENCRYPTION_KEY'] = Fernet.generate_key().decode()

from number_inbox_batch_contract import ROOT, excel, HEADERS
from v162_number_inbox_contract import _TMPDIR, create_session, db, init_db
from app.v162_number_inbox import ensure_number_inbox_schema, ensure_desktop_token
from win_assistants.number_batch_bridge import NumberBatchBridge


def main():
    init_db()
    with db() as conn:
        ensure_number_inbox_schema(conn)
        desktop_token = ensure_desktop_token(conn)
        conn.execute("INSERT INTO number_inbox(number,normalized_number,status,submitted_at) VALUES('00123456789','00123456789','pending','2026-10-01')")
    session, _, _ = create_session()
    target = Path(_TMPDIR.name) / 'members.xlsx'
    target.write_bytes(excel([['stale', 'old', '99999', 'name', '0', 'dept']], HEADERS))
    bridge = NumberBatchBridge(lambda: desktop_token, lambda: target, ledger=Path(_TMPDIR.name) / 'requests.json', port=0)
    assert bridge.start()[0]
    base = 'http://127.0.0.1:8179'
    proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8179'], cwd=ROOT, env=os.environ.copy())
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
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={'width': 1440, 'height': 900})
            context.grant_permissions(['local-network-access'], origin=base)
            context.add_cookies([{'name': 'session_token', 'value': session, 'url': base}])
            # Local test origin is not trusted by the production bridge. Forward only
            # these explicit routes with the production Origin; bridge auth remains real.
            calls = []
            def local_proxy(route):
                request = route.request
                connection = http.client.HTTPConnection('127.0.0.1', bridge.server.server_port, timeout=5)
                path = '/health' if request.url.endswith('/health') else '/number-batch'
                if path == '/number-batch' and request.method == 'POST':
                    calls.append(request.post_data)
                connection.request(request.method, path, request.post_data, {'Origin': 'https://assistant.ziboxiaozhushou.cn', 'Content-Type': 'application/json'})
                response = connection.getresponse()
                route.fulfill(status=response.status, content_type='application/json', body=response.read(),
                              headers={'Access-Control-Allow-Origin': base, 'Access-Control-Allow-Headers': 'Content-Type',
                                       'Access-Control-Allow-Methods': 'GET, POST, OPTIONS', 'Access-Control-Allow-Private-Network': 'true'})
                connection.close()
            context.route('http://127.0.0.1:18764/**', local_proxy)
            page = context.new_page()
            page.goto(base + '/work/number-inbox?view=settings', wait_until='networkidle')
            page.locator('input[name=group_template]').set_input_files({'name': 'groups.xlsx', 'mimeType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'buffer': excel([['G001'], ['G002']])})
            page.locator('input[name=role]').fill('custom-role')
            page.locator('input[name=manual]').fill('0')
            page.get_by_role('button', name='保存批量设置').click()
            expect(page.locator('.number-batch-settings')).to_contain_text('2 个集团编码')
            previews = ROOT / 'artifacts' / 'number-inbox-batch'
            previews.mkdir(parents=True, exist_ok=True)
            for width, height in [(1440, 900), (390, 844)]:
                page.set_viewport_size({'width': width, 'height': height})
                page.goto(base + '/work/number-inbox?view=settings', wait_until='networkidle')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
                page.locator('.number-batch-settings').locator('..').screenshot(path=str(previews / f'settings-{width}.png'))
            page.goto(base + '/work/number-inbox', wait_until='networkidle')
            button = page.get_by_role('button', name='批量添加', exact=True)
            button.evaluate('(el) => { el.click(); el.click(); }')
            expect(page.locator('[data-number-batch-status]')).to_contain_text('已写入 1 个号码')
            assert len(calls) == 1, 'double click must not submit twice'
            page.locator('.number-inbox-shell').screenshot(path=str(previews / 'pending-written.png'))
            expect(page.locator('[data-copy-value]')).to_have_count(1)
            with db() as conn:
                assert conn.execute("SELECT COUNT(*) n FROM number_inbox WHERE status='pending'").fetchone()['n'] == 1
            context.unroute('http://127.0.0.1:18764/**', local_proxy)
            context.route('http://127.0.0.1:18764/**', lambda route: route.abort())
            button.click()
            expect(page.locator('[data-number-batch-status]')).to_contain_text('无法连接Windows助手')
            expect(button).to_be_enabled()
            context.unroute('http://127.0.0.1:18764/**')
            context.route('http://127.0.0.1:18764/**', local_proxy)
            saved = target.read_bytes()
            target.rename(target.with_suffix('.moved'))
            button.click()
            expect(page.locator('[data-number-batch-status]')).to_contain_text('请选择已存在')
            assert target.with_suffix('.moved').read_bytes() == saved
            with db() as conn:
                conn.execute("UPDATE number_inbox SET status='done'")
            page.reload(wait_until='networkidle')
            expect(button).to_be_disabled()
            browser.close()
        print('number batch browser upload, mobile layout, signed writer, repeat click and local errors passed')
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        bridge.stop()


if __name__ == '__main__':
    main()
