"""Save real attributes, then immediately copy/reopen without live-refresh repair."""
import json
import os
import subprocess
import sys
import time
import urllib.request

from fastapi.testclient import TestClient
from business_display_settings_contract import ROOT, app, seed, create_session, SELECTED
from app.db import db


def main():
    (cid, sid), _ = seed()
    # Enough rows to exercise the scrolled region where the fixed toast lives.
    with db() as conn:
        for index in range(30):
            new_sid = conn.execute('''INSERT INTO services(customer_id,service_type,holder_name,number,account,
                payment_interval_months,payment_cycle,last_payment_date,notes,monthly_fee,fixed_fee)
                SELECT customer_id,service_type,holder_name,number,account,payment_interval_months,
                payment_cycle,last_payment_date,notes,monthly_fee,fixed_fee FROM services WHERE id=?''',
                (sid,)).lastrowid
            if index == 15:
                edited_sid = new_sid
    sid = edited_sid
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
            # Toasts are noninteractive, including after their opacity animation
            # has hidden them. Click the real coordinate under the retained toast,
            # not a locator center that happens to miss its small covered area.
            page.evaluate("window.ChenToast('业务已保存')")
            page.wait_for_timeout(1200)
            hit = page.evaluate('''sid => {
                const row = document.querySelector(`[data-business-row][data-service-id="${sid}"]`);
                const toast = document.querySelector('.app-toast');
                const initial = toast.getBoundingClientRect();
                const rect = row.querySelector('.business-attribute').getBoundingClientRect();
                window.scrollBy({top:rect.top + rect.height / 2 - (initial.top + initial.height / 2), behavior:'instant'});
                const box = toast.getBoundingClientRect();
                const y = box.top + box.height / 2;
                const attribute = [...row.querySelectorAll('.business-attribute')].find(el => {
                    const r = el.getBoundingClientRect();
                    return r.left < box.right - 2 && r.right > box.left + 2 && r.top < y && r.bottom > y;
                });
                const r = attribute?.getBoundingClientRect();
                const x = r ? (Math.max(r.left, box.left) + Math.min(r.right, box.right)) / 2 : box.left + box.width / 2;
                return {x, y, key:attribute?.dataset.attrKey,
                    top:document.elementFromPoint(x, y)?.className};
            }''', sid)
            assert hit['key'], hit
            assert 'app-toast' not in hit['top'], hit
            assert hit['key'] in ['number', 'account'], hit
            copied = row.locator(f'[data-attr-key="{hit["key"]}"] strong').inner_text()
            page.mouse.click(hit['x'], hit['y'])
            assert page.evaluate('navigator.clipboard.readText()') == copied
            expect(page.locator('.app-toast')).to_have_text('已复制')
            # The copy feedback is now visible; the second gesture must also
            # reach the same identifier while that feedback is still shown.
            assert page.evaluate('''point => document.elementFromPoint(point.x, point.y)
                ?.closest('.business-attribute')?.dataset.attrKey''', hit) == hit['key']
            page.mouse.click(hit['x'], hit['y'], click_count=2)
            expect(editor).to_be_visible()
            editor.locator('[data-business-editor-close]').first.click()
            assert not errors, errors
            browser.close()
        print('real business save/reopen/copy acceptance passed: three saves, scrolled rows and toast hit testing')
    finally:
        process.terminate()
        process.wait(timeout=10)


if __name__ == '__main__':
    main()
