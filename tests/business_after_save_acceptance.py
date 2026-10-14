"""Save real attributes, then immediately copy/reopen without live-refresh repair."""
import json
import os
import subprocess
import sys
import time
import urllib.request

from fastapi.testclient import TestClient
from business_display_settings_contract import ROOT, app, seed, create_session, SELECTED


def main():
    (cid, sid), _ = seed()
    token, csrf, _ = create_session()
    with TestClient(app) as client:
        client.cookies.set('session_token', token)
        response = client.post(f'/customers/{cid}/business-columns-v0212',
            data={'csrf': csrf, 'columns_json': json.dumps(SELECTED)})
        assert response.status_code == 200
    base = 'http://127.0.0.1:8179'
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app',
        '--host', '127.0.0.1', '--port', '8179'], cwd=ROOT, env=os.environ.copy())
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + '/health', timeout=1)
                break
            except OSError:
                time.sleep(.2)
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1440, 'height': 900},
                permissions=['clipboard-read', 'clipboard-write'])
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': base}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            # A successful save must restore its own UI. A background page
            # reload must not silently hide a broken save renderer.
            page.route('**/*', lambda route: route.abort()
                if route.request.headers.get('x-chen-live-refresh') == '1'
                else route.continue_())
            page.goto(base + f'/customers/{cid}?tab=services', wait_until='networkidle')
            row = page.locator(f'[data-business-row][data-service-id="{sid}"]')
            editor = page.locator('#businessAttributeDialog')
            for turn in range(3):
                row.locator('[data-attr-key="number"]').dblclick()
                expect(editor).to_be_visible()
                expect(editor.locator('[data-v031-payment-mode]')).to_be_enabled()
                number = f'00138000000{turn}'
                account = f'00053380000{turn}'
                editor.locator('[data-key="number"] .attr-value').fill(number)
                editor.locator('[data-key="account"] .attr-value').fill(account)
                editor.locator('[data-key="notes"] .attr-value').fill(f'真实保存{turn}')
                with page.expect_response(lambda r: r.url.endswith('/status-v03')
                        and r.request.method == 'POST') as saved:
                    editor.locator('[data-business-attribute-form] button[type="submit"]').click()
                assert saved.value.ok
                expect(editor).not_to_be_visible()
                keys = row.locator('.business-attribute').evaluate_all('els => els.map(el => el.dataset.attrKey)')
                assert keys == SELECTED, {'turn': turn, 'keys': keys, 'errors': errors}
                for key, value in [('number', number), ('account', account)]:
                    field = row.locator(f'[data-attr-key="{key}"]')
                    expect(field.locator('strong')).to_have_text(value)
                    field.click()
                    assert page.evaluate('navigator.clipboard.readText()') == value
                before = page.evaluate('navigator.clipboard.readText()')
                row.locator('[data-attr-key="notes"]').click()
                assert page.evaluate('navigator.clipboard.readText()') == before
                row.locator('[data-attr-key="notes"]').dblclick()
                expect(editor).to_be_visible()
                assert editor.locator('[data-key="notes"] .attr-value').input_value() == f'真实保存{turn}'
                editor.locator('[data-business-editor-close]').first.click()
            assert not errors, errors
            browser.close()
        print('real business save/reopen/copy acceptance passed: three saves without refresh')
    finally:
        process.terminate()
        process.wait(timeout=10)


if __name__ == '__main__':
    main()
