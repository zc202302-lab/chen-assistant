"""Exercise actual display settings, AJAX refresh, reload and customer isolation."""
import os
import subprocess
import sys
import time
import urllib.request

from business_display_settings_contract import ROOT, seed, create_session, LEGACY, SELECTED


def main():
    (cid, sid), (other_cid, other_sid) = seed()
    token, _, _ = create_session()
    base = 'http://127.0.0.1:8177'
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app',
        '--host', '127.0.0.1', '--port', '8177'], cwd=ROOT, env=os.environ.copy())
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + '/health', timeout=1)
                break
            except OSError:
                time.sleep(.2)
        else:
            raise RuntimeError('server startup failed')
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1440, 'height': 900})
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': base}])
            page = context.new_page()
            page.goto(base + f'/customers/{cid}?tab=services', wait_until='networkidle')
            row = page.locator(f'[data-business-row][data-service-id="{sid}"]')
            cells = row.locator('.business-attribute')
            expect(cells).to_have_count(3)
            page.locator('[data-business-columns-settings-v0212]').click()
            settings = page.locator('.business-columns-dialog-v0212')
            expect(settings).to_be_visible()
            for field in settings.locator('[data-business-column-order-v0212]').all():
                field.fill('')
            for position, key in enumerate(SELECTED, 1):
                settings.locator(f'[data-business-column-key="{key}"] input').fill(str(position))
            with page.expect_response(lambda r: r.request.headers.get('x-chen-live-refresh') == '1') as refresh:
                settings.get_by_role('button', name='保存显示设置').click()
            assert refresh.value.ok
            expect(settings).not_to_be_visible()
            expect(cells).to_have_count(6)
            assert cells.evaluate_all('els => els.map(el => el.dataset.attrKey)') == SELECTED
            headers = page.locator('.business-table-header-cell-v030')
            expect(headers).to_have_text(['姓名/属性', '号码', '账号', '测试金额', '备注', '上次缴费日期'])
            # A reload must not need the client-side bootstrap to repair the HTML.
            page.reload(wait_until='networkidle')
            expect(cells).to_have_count(6)
            assert cells.evaluate_all('els => els.map(el => el.dataset.attrKey)') == SELECTED
            expect(headers).to_have_count(6)
            output = ROOT / 'artifacts' / 'list-compact'
            output.mkdir(parents=True, exist_ok=True)
            for width in (1440, 390):
                page.set_viewport_size({'width': width, 'height': 900})
                for field in cells.all():
                    expect(field).to_be_visible()
                page.screenshot(path=str(output / f'business-display-settings-{width}.png'), full_page=True)
            page.goto(base + f'/customers/{other_cid}?tab=services', wait_until='networkidle')
            other = page.locator(f'[data-business-row][data-service-id="{other_sid}"] .business-attribute')
            expect(other).to_have_count(3)
            assert other.evaluate_all('els => els.map(el => el.dataset.attrKey)') == LEGACY
            page.goto(base + f'/customers/{cid}?tab=services', wait_until='networkidle')
            expect(cells).to_have_count(6)
            browser.close()
        print('business display settings browser acceptance passed: six columns, live refresh, reload, mobile and customer isolation')
    finally:
        process.terminate()
        process.wait(timeout=10)


if __name__ == '__main__':
    main()
