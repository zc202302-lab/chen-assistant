"""Actual cross-space pins preserve source visuals, summaries and saved editing."""
import os
import subprocess
import sys
import time
import urllib.request
from cryptography.fernet import Fernet

os.environ['APP_ENCRYPTION_KEY'] = Fernet.generate_key().decode()
from v162_number_inbox_contract import ROOT, create_session, init_db

STYLE = """el => {
  const s = getComputedStyle(el);
  return Object.fromEntries(['backgroundColor','borderRadius','borderColor','padding',
    'fontSize','fontWeight','color','display'].map(k => [k,s[k]]));
}"""


def main():
    init_db()
    token, _, _ = create_session()
    base = 'http://127.0.0.1:8185'
    proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app',
                             '--host', '127.0.0.1', '--port', '8185'], cwd=ROOT, env=os.environ.copy())
    try:
        for _ in range(100):
            try:
                if urllib.request.urlopen(base + '/health', timeout=1).status == 200:
                    break
            except OSError:
                pass
            time.sleep(.2)
        else:
            raise RuntimeError('server startup failed')
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': base}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            work = ['/work/customers', '/work/number-inbox', '/work/customers?home=payment', '/work/customers?home=promos']
            selected = [('/work', '.work-entry-link', work),
                        ('/info', '.info-overview-card-v160', ['/info', '/accounts']),
                        ('/life', '.v12-life-card', ['/life/recipes', '/life/tools'])]
            originals = {}
            for source, selector, hrefs in selected:
                page.goto(base + source, wait_until='networkidle')
                page.get_by_role('button', name='编辑模块', exact=True).click()
                for href in hrefs:
                    link = page.locator(f'{selector}[href="{href}"]')
                    action = link.locator('..').locator('.work-home-pin') if source == '/work' else link.locator('xpath=following-sibling::button[1]')
                    with page.expect_response(lambda response: response.url.endswith('/home/shortcuts') and response.request.method == 'POST') as result:
                        action.click()
                    assert result.value.ok
                    expect(action).to_be_enabled()
            # Capture normal, non-editing source styles at desktop and mobile sizes.
            for width in (1440, 390, 320):
                page.set_viewport_size({'width': width, 'height': 1000})
                for source, selector, hrefs in selected:
                    page.goto(base + source, wait_until='networkidle')
                    for href in hrefs:
                        link = page.locator(f'{selector}[href="{href}"]')
                        card = link.locator('..') if source == '/work' else link
                        originals[(width, href)] = (card.evaluate(STYLE), link.inner_html(), card.bounding_box())
                page.goto(base + '/', wait_until='networkidle')
                expect(page.locator('.home-shortcut-source')).to_have_count(8)
                expect(page.get_by_role('heading', name='待处理事项')).to_have_count(0)
                for source, selector, hrefs in selected:
                    for href in hrefs:
                        wrapper = page.locator(f'[data-home-module-href="{href}"]')
                        link = wrapper.locator(f'{selector}[href="{href}"]')
                        card = wrapper.locator('.work-entry-tile') if source == '/work' else link
                        style, content, box = originals[(width, href)]
                        assert card.evaluate(STYLE) == style, (width, href, style, card.evaluate(STYLE))
                        assert link.inner_html() == content, (width, href)
                        if source == '/work':
                            actual = card.bounding_box()
                            assert abs(actual['width'] - box['width']) <= 1 and abs(actual['height'] - box['height']) <= 1
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                previews = ROOT / 'artifacts' / 'number-inbox-batch'
                previews.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(previews / f'home-source-modules-{width}.png'), full_page=True)
                expect(page.locator('[data-sidebar-navigation]')).to_be_hidden()
                expect(page.locator('.bottom-nav')).to_have_count(0)
                expect(page.get_by_text('查看未加号码', exact=True)).to_have_count(0)
                page.locator('[data-sidebar-toggle]').click()
                expect(page.locator('[data-sidebar-navigation] a[href="/life"]')).to_be_visible()
                page.screenshot(path=str(previews / f'home-sidebar-{width}.png'), full_page=True)
                page.locator('[data-sidebar-close]').click()
                expect(page.locator('[data-sidebar-navigation]')).to_be_hidden()

            # Existing pins render automatically; cancel and saved order survive reload.
            page.get_by_role('button', name='编辑模块', exact=True).click()
            page.locator('.home-shortcut-controls').first.get_by_role('button', name='移除').click()
            page.get_by_role('button', name='取消', exact=True).click()
            expect(page.locator('.home-shortcut-source')).to_have_count(8)
            page.get_by_role('button', name='编辑模块', exact=True).click()
            page.locator('.home-shortcut-controls').first.get_by_role('button', name='→', exact=True).click()
            page.get_by_role('button', name='保存布局', exact=True).click()
            expect(page.get_by_role('button', name='编辑模块', exact=True)).to_be_enabled()
            page.reload(wait_until='networkidle')
            expect(page.locator('[data-home-module-href]').first).to_have_attribute('data-home-module-href', '/work/number-inbox')
            for tab in ('payment', 'promos'):
                href = f'/work/customers?home={tab}'
                page.locator(f'[data-home-module-href="{href}"] a').click()
                expect(page).to_have_url(base + href)
                expect(page.locator(f'[data-home-tab="{tab}"]')).to_have_class(__import__('re').compile('active'))
                page.goto(base + '/', wait_until='networkidle')
            # Temporary source failure preserves usable pins and their durable data.
            page.route('**/work', lambda route: route.abort())
            page.reload(wait_until='networkidle')
            expect(page.locator('[data-home-module-href]')).to_have_count(8)
            expect(page.locator('.home-shortcut-fallback')).to_have_count(4)
            page.unroute('**/work')
            page.reload(wait_until='networkidle')
            expect(page.locator('.home-shortcut-source')).to_have_count(8)
            assert not errors, errors
            browser.close()
        print('Source card visuals/live summaries, mobile layout, cross-space pin/edit, task-panel removal and payment/promo navigation passed')
    finally:
        proc.terminate()
        proc.wait(timeout=10)


if __name__ == '__main__':
    main()
