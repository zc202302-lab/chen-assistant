"""Real page table previews: full text, partial selection and existing editors."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

from business_display_settings_contract import ROOT, seed, create_session, db
from fastapi.testclient import TestClient
from app.main import app


def main():
    (cid, sid), _ = seed()
    full = '完整备注：可以选择其中一部分复制 <script>禁止执行</script>\n' + '超长内容' * 80
    with db() as conn:
        conn.execute('UPDATE services SET notes=? WHERE id=?', (full, sid))
    token, csrf, _ = create_session()
    with TestClient(app) as client:
        client.cookies.set('session_token', token)
        for url, columns in [(f'/customers/{cid}/payment-columns-v0211', ['holder_name', 'notes', 'payment_amount']),
                             (f'/customers/{cid}/business-columns-v0212', ['holder_name', 'notes', 'number'])]:
            response = client.post(url, data={'csrf': csrf, 'columns_json': json.dumps(columns)})
            assert response.status_code == 200, response.text
    base = 'http://127.0.0.1:8183'
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8183'], cwd=ROOT, env=os.environ.copy(), stdout=subprocess.DEVNULL)
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
            context = browser.new_context(viewport={'width': 1440, 'height': 900})
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': base}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            for width in (1440, 390):
                page.set_viewport_size({'width': width, 'height': 900})
                for tab, selector in [('payment', '[data-payment-business-cell][data-payment-attr-key="notes"]'), ('services', '.business-attribute[data-attr-key="notes"]')]:
                    page.goto(base + f'/customers/{cid}?tab={tab}', wait_until='networkidle')
                    if tab == 'payment':
                        expect(page.locator('[data-payment-column-head][data-payment-attr-key="payment_amount"]')).to_contain_text('本月缴费')
                    cell = page.locator(selector).first
                    cell.click()
                    preview = page.locator('.workspace-cell-preview')
                    expect(preview).to_be_visible()
                    assert preview.text_content() == full
                    assert preview.locator('script').count() == 0
                    box = preview.bounding_box()
                    assert box['x'] >= 0 and box['x'] + box['width'] <= width
                    # Drag across actual rendered text, not an artificial Range.
                    page.mouse.move(box['x'] + 17, box['y'] + 23)
                    page.mouse.down()
                    page.mouse.move(box['x'] + 110, box['y'] + 23, steps=12)
                    page.mouse.up()
                    assert page.evaluate('getSelection().toString().length') > 0
                    expect(preview).to_be_visible()
                    out = ROOT / 'artifacts/table-cell-details'
                    out.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(out / f'{tab}-{width}.png'))
                    page.mouse.click(width - 3, 3)
                    expect(preview).not_to_be_visible()
                    cell.click()
                    page.keyboard.press('Escape')
                    expect(preview).not_to_be_visible()
                    cell.dblclick()
                    expect(page.locator('#businessAttributeDialog')).to_be_visible()
                    expect(preview).not_to_be_visible()
                    page.locator('[data-business-editor-close]').first.click()
            assert not errors, errors
            browser.close()
        print('table cell details acceptance passed: full text, selection, close, editor, desktop/mobile')
    finally:
        process.terminate()
        process.wait(timeout=10)


if __name__ == '__main__':
    main()
