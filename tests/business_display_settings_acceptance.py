"""Exercise actual display settings, AJAX refresh, reload and customer isolation."""
import os
import subprocess
import sys
import time
import urllib.request

from business_display_settings_contract import ROOT, seed, create_session, LEGACY, SELECTED, db


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
            # No reload/rebinding: exercise new cells immediately after AJAX
            # settings save, then after replacing a row exactly as live refresh.
            page.evaluate("""() => {
                window.__copied = [];
                Object.defineProperty(navigator, 'clipboard', {configurable:true,
                    value:{writeText:async text => window.__copied.push(text)}});
            }""")
            editor = page.locator('#businessAttributeDialog')
            for replace in (False, True):
                if replace:
                    row.evaluate("el => {el.innerHTML = el.innerHTML; el.querySelector('[data-open-service-editor]')?.remove();}")
                cell = row.locator('.business-attribute[data-attr-key="number"]')
                expected = cell.locator('strong').inner_text().strip()
                cell.click()
                expect(page.locator('.app-toast').last).to_have_text('已复制')
                assert page.evaluate('window.__copied.at(-1)') == expected
                account = row.locator('.business-attribute[data-attr-key="account"]')
                account.click()
                assert page.evaluate('window.__copied.at(-1)') == account.locator('strong').inner_text().strip()
                cell.dblclick()
                expect(editor).to_be_visible()
                assert editor.locator('[name="service_id"]').input_value() == str(sid)
                editor.locator('[data-business-editor-close]').first.click()
                expect(editor).not_to_be_visible()
                # Other attributes neither copy nor claim success, including
                # stale markers left on a freshly replaced row.
                for other in cells.all():
                    if other.get_attribute('data-attr-key') in ('number', 'account'):
                        continue
                    count = page.evaluate('window.__copied.length')
                    other.evaluate("el => {el.dataset.copySilent = 'must-not-copy';}")
                    other.click()
                    page.wait_for_timeout(30)
                    assert page.evaluate('window.__copied.length') == count
                    other.dblclick()
                    expect(editor).to_be_visible()
                    editor.locator('[data-business-editor-close]').first.click()
            # A denied clipboard must not display a false success toast.
            page.evaluate("""() => {
                navigator.clipboard.writeText = async () => {throw new Error('denied')};
                window.__execCommand = document.execCommand;
                document.execCommand = () => false;
            }""")
            row.locator('.business-attribute[data-attr-key="number"]').click()
            expect(page.locator('.app-toast').last).to_have_text('复制失败，请重试')
            page.evaluate('() => { document.execCommand = window.__execCommand; }')
            # A reload must not need the client-side bootstrap to repair the HTML.
            page.reload(wait_until='networkidle')
            expect(cells).to_have_count(6)
            assert cells.evaluate_all('els => els.map(el => el.dataset.attrKey)') == SELECTED
            expect(headers).to_have_count(6)
            # A refresh skipped during editing must be replayed even if the
            # next server response has exactly the same HTML signature.
            before = cells.first.locator('strong').inner_text()
            page.evaluate("""() => {
                const input = document.createElement('input'); input.id = 'busy-refresh-probe';
                document.querySelector('[data-customer-panel="services"]').appendChild(input);
                input.focus();
            }""")
            with db() as conn:
                conn.execute('UPDATE services SET holder_name=? WHERE id=?', ('无需刷新更新成员', sid))
            with page.expect_response(lambda r: r.request.headers.get('x-chen-live-refresh') == '1'):
                page.evaluate('window.ChenLiveRefresh.refresh()')
            page.wait_for_timeout(100)
            expect(cells.first.locator('strong')).to_have_text(before)
            page.evaluate("() => {const input=document.querySelector('#busy-refresh-probe'); input.blur(); input.remove();}")
            with page.expect_response(lambda r: r.request.headers.get('x-chen-live-refresh') == '1'):
                page.evaluate('window.ChenLiveRefresh.refresh()')
            expect(cells.first.locator('strong')).to_have_text('无需刷新更新成员')
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
            page.goto(base + f'/customers/{cid}?tab=payment', wait_until='networkidle')
            payment = page.locator(f'[data-payment-row][data-service-id="{sid}"]')
            expect(payment).to_be_visible()
            payment.evaluate("el => {el.innerHTML = el.innerHTML; el.querySelector('[data-open-service-editor]')?.remove();}")
            fields = payment.locator('[data-payment-business-cell]')
            assert fields.count() > 0
            page.evaluate("""() => {
                window.__copied = [];
                Object.defineProperty(navigator, 'clipboard', {configurable:true,
                    value:{writeText:async text => window.__copied.push(text)}});
            }""")
            for field in fields.all():
                count = page.evaluate('window.__copied.length')
                key = field.get_attribute('data-payment-attr-key')
                if key not in ('number', 'account'):
                    field.evaluate("el => {el.dataset.copySilent = 'must-not-copy';}")
                field.click()
                page.wait_for_timeout(30)
                assert page.evaluate('window.__copied.length') == count + int(key in ('number', 'account'))
                field.dblclick()
                expect(editor).to_be_visible()
                assert editor.locator('[name="service_id"]').input_value() == str(sid)
                editor.locator('[data-business-editor-close]').first.click()
            # Promotion triggers inserted by an AJAX table refresh must also
            # use the stable editor owner without needing another page load.
            page.evaluate("""sid => {
                const button = document.createElement('button');
                button.dataset.promoServiceEditor = '1'; button.dataset.serviceId = sid;
                button.id = 'dynamic-promotion-test'; button.textContent = '测试优惠业务';
                document.querySelector('.v028-workspace').appendChild(button);
            }""", str(sid))
            page.locator('#dynamic-promotion-test').dblclick()
            expect(editor).to_be_visible()
            assert editor.locator('[name="service_id"]').input_value() == str(sid)
            editor.locator('[data-business-editor-close]').first.click()
            browser.close()
        print('business display settings browser acceptance passed: six columns, live refresh, reload, mobile and customer isolation')
    finally:
        process.terminate()
        process.wait(timeout=10)


if __name__ == '__main__':
    main()
