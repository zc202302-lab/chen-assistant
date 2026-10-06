"""Real mouse/keyboard selection on shared forms, customer workspace and sheet."""
from pathlib import Path
import os
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from v152_high_frequency_flow_acceptance import seed


def settled(page):
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    page.wait_for_timeout(80)


def selected(editor):
    return editor.evaluate("el => [el.selectionStart, el.selectionEnd]")


def prepare(page, editor, value):
    editor.fill(value)
    editor.evaluate("""el => {
        el.style.font = '16px monospace';
        el.style.letterSpacing = '0px';
        el.style.textAlign = 'left';
        el.style.width = '260px';
        el.style.padding = '8px';
        el.style.boxSizing = 'border-box';
        el.blur();
        el.scrollLeft = 0;
    }""")
    editor.click(trial=True)
    return editor.evaluate("""el => {
        const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
        const canvas = document.createElement('canvas'), ctx = canvas.getContext('2d');
        ctx.font = style.font;
        return {x:rect.x + parseFloat(style.borderLeftWidth) + parseFloat(style.paddingLeft),
                y:rect.y + parseFloat(style.borderTopWidth) + parseFloat(style.paddingTop) + 8,
                char:ctx.measureText('0').width};
    }""")


def drag(page, coords, start=2, end=5):
    page.mouse.move(coords['x'] + coords['char'] * start, coords['y'])
    page.mouse.down()
    page.mouse.move(coords['x'] + coords['char'] * end, coords['y'], steps=12)
    page.mouse.up()
    settled(page)


def exercise(page, editor, value='1234567890'):
    # A drag into an unfocused editor must survive mouseup and deferred work.
    coords = prepare(page, editor, value)
    drag(page, coords)
    assert selected(editor) == [2, 5], selected(editor)
    # A fresh, ordinary single click still supports quick replacement.
    editor.evaluate('el => el.blur()')
    page.mouse.click(coords['x'] + coords['char'] * 4, coords['y'])
    settled(page)
    assert selected(editor) == [0, len(value)], selected(editor)
    # Second AND third clicks set the caret rather than cycling back to select-all.
    for offset in (4, 6, 3):
        page.mouse.click(coords['x'] + coords['char'] * offset, coords['y'])
        settled(page)
        assert selected(editor) == [offset, offset], selected(editor)
    drag(page, coords)
    assert selected(editor) == [2, 5], selected(editor)
    editor.press('ArrowRight')
    editor.press('Shift+ArrowLeft')
    settled(page)
    assert selected(editor) == [4, 5], selected(editor)
    editor.press('ControlOrMeta+a')
    assert selected(editor) == [0, len(value)]
    # Document capture must not swallow module click handlers.
    editor.evaluate("el => {el.dataset.clicks='0'; el.addEventListener('click', () => el.dataset.clicks=String(Number(el.dataset.clicks)+1));}")
    page.mouse.click(coords['x'] + coords['char'] * 3, coords['y'])
    settled(page)
    assert editor.get_attribute('data-clicks') == '1'
    assert selected(editor) == [3, 3]


def main():
    cid, ids, token = seed()
    base = 'http://127.0.0.1:8175'
    proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app',
        '--host', '127.0.0.1', '--port', '8175'], cwd=ROOT, env=os.environ.copy())
    try:
        for _ in range(120):
            try:
                if urllib.request.urlopen(base + '/health', timeout=1).status == 200: break
            except Exception: pass
            time.sleep(.2)
        else: raise RuntimeError('server start failed')
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width':1450,'height':950})
            context.grant_permissions(['clipboard-read','clipboard-write'], origin=base)
            context.add_cookies([{'name':'session_token','value':token,'url':base}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + f'/customers/{cid}', wait_until='networkidle')
            amount = page.locator('.quick-amount').first
            exercise(page, amount)
            amount.fill('100')
            page.locator('[data-customer-tab="services"]').click()
            panel = page.locator('[data-customer-panel="services"]')
            details = panel.locator('details').filter(has=page.locator('input.manual-date')).last
            details.locator('summary').click()
            exercise(page, details.locator('input.manual-date'), '2026/10/01')
            exercise(page, details.locator('textarea'))
            # Existing continuous payment entry still selects the destination.
            page.locator('[data-customer-tab="payment"]').click()
            amount = page.locator(f'[data-service-id="{ids[0]}"] .quick-amount')
            amount.fill('125')
            amount.press('Enter')
            destination = page.locator(f'[data-service-id="{ids[1]}"] .quick-amount')
            expect(destination).to_be_focused(timeout=5000)
            settled(page)
            value = destination.input_value()
            assert selected(destination) == [0, len(value)]
            exercise(page, destination, value='1234567890')
            for width in (1450, 390):
                page.set_viewport_size({'width':width,'height':950})
                page.goto(base + '/work/lists?view=new', wait_until='networkidle')
                exercise(page, page.get_by_label('清单名称', exact=True))
                exercise(page, page.locator('.ws-cell').first)
                page.get_by_role('button', name='增加行').click()
                exercise(page, page.locator('.ws-cell').last)
            # Shared behavior is delegated and covers dynamically inserted forms
            # on non-customer pages too, without per-page initialization.
            for path in ('/work', '/life', '/reminders'):
                page.goto(base + path, wait_until='networkidle')
                page.evaluate("""() => {
                    const input=document.createElement('input');
                    input.id='dynamic-selection';
                    document.querySelector('main').prepend(input);
                }""")
                exercise(page, page.locator('#dynamic-selection'))
            assert not errors, errors
            browser.close()
        print('Input selection acceptance passed: first click, drag, repeated caret, keyboard, dynamic forms, date, textarea, sheet, Enter navigation')
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill()


if __name__ == '__main__':
    main()
