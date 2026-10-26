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
from cryptography.fernet import Fernet
# This broader regression also visits reminders; use a valid isolated test key.
os.environ['APP_ENCRYPTION_KEY'] = Fernet.generate_key().decode()
from app import config
config.APP_ENCRYPTION_KEY = os.environ['APP_ENCRYPTION_KEY']


def settled(page):
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    page.wait_for_timeout(80)


def selected(editor):
    return editor.evaluate("el => [el.selectionStart, el.selectionEnd]")


def prepare(page, editor, value):
    editor.fill(value)
    editor.evaluate("""el => {
        el.style.setProperty('font', '16px monospace', 'important');
        el.style.letterSpacing = '0px';
        el.style.setProperty('line-height', '20px', 'important');
        el.style.setProperty('height', el.tagName === 'TEXTAREA' ? '64px' : '40px', 'important');
        el.style.setProperty('min-height', '0', 'important');
        el.style.setProperty('text-align', 'left', 'important');
        el.style.setProperty('width', '260px', 'important');
        el.style.setProperty('min-width', '260px', 'important');
        el.style.setProperty('max-width', 'none', 'important');
        el.style.setProperty('padding', '8px', 'important');
        el.style.boxSizing = 'border-box';
        el.blur();
        el.scrollLeft = 0;
        el.scrollTop = 0;
        el.scrollIntoView({behavior:'instant', block:'center', inline:'nearest'});
    }""")
    editor.click(trial=True)
    settled(page)
    coords = editor.evaluate("""el => {
        const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
        const canvas = document.createElement('canvas'), ctx = canvas.getContext('2d');
        ctx.font = style.font;
        return {left:parseFloat(style.borderLeftWidth) + parseFloat(style.paddingLeft), top:parseFloat(style.borderTopWidth) + parseFloat(style.paddingTop) + 10,
                x:rect.x + parseFloat(style.borderLeftWidth) + parseFloat(style.paddingLeft),
                y:rect.y + parseFloat(style.borderTopWidth) + parseFloat(style.paddingTop) + 10,
                char:ctx.measureText('0').width};
    }""")
    assert editor.evaluate("(el, c) => document.elementFromPoint(c.x + c.char * 2, c.y) === el", coords), (coords, editor.evaluate("el => ({rect:el.getBoundingClientRect().toJSON(),font:getComputedStyle(el).font})"))
    return coords


def drag(page, editor, coords, start=2, end=5):
    editor.hover(position={'x':coords['left'] + coords['char'] * start, 'y':coords['top']})
    page.mouse.down()
    box = editor.bounding_box()
    page.mouse.move(box['x'] + coords['left'] + coords['char'] * end, box['y'] + coords['top'], steps=12)
    page.mouse.up()
    settled(page)


def exercise(page, editor, value='1234567890'):
    # A drag into an unfocused editor must survive mouseup and deferred work.
    coords = prepare(page, editor, value)
    editor.evaluate("""el => {
      window.selectionTrace=[];
      for(const name of ['pointerdown','pointerup','click','focus']) {
        el.addEventListener(name, e => window.selectionTrace.push({name:e.type,x:e.clientX,y:e.clientY,
          start:el.selectionStart,end:el.selectionEnd,value:el.value,scroll:el.scrollLeft,
          rect:el.getBoundingClientRect().toJSON(),font:getComputedStyle(el).font}),true);
      }
    }""")
    drag(page, editor, coords)
    assert selected(editor) == [2, 5], (selected(editor), coords, page.evaluate('window.selectionTrace'))
    # A fresh, ordinary single click still supports quick replacement.
    editor.evaluate('el => el.blur()')
    editor.click(position={'x':coords['left'] + coords['char'] * 4, 'y':coords['top']})
    settled(page)
    assert selected(editor) == [0, len(value)], selected(editor)
    # Small hand motion must still be a single click, not mistaken for a drag.
    editor.evaluate('el => el.blur()')
    box = editor.bounding_box()
    page.mouse.move(box['x'] + coords['left'] + coords['char'] * 4, box['y'] + coords['top'])
    page.mouse.down()
    page.mouse.move(box['x'] + coords['left'] + coords['char'] * 4 + 2, box['y'] + coords['top'] + 1)
    page.mouse.up()
    settled(page)
    assert selected(editor) == [0, len(value)], selected(editor)
    # Second AND third clicks set the caret rather than cycling back to select-all.
    for offset in (4, 6, 3):
        editor.click(position={'x':coords['left'] + coords['char'] * offset, 'y':coords['top']})
        settled(page)
        assert selected(editor) == [offset, offset], selected(editor)
    drag(page, editor, coords)
    assert selected(editor) == [2, 5], selected(editor)
    editor.press('ArrowRight')
    editor.press('Shift+ArrowLeft')
    settled(page)
    assert selected(editor) == [4, 5], selected(editor)
    editor.press('ControlOrMeta+a')
    assert selected(editor) == [0, len(value)]
    # Document capture must not swallow module click handlers.
    editor.evaluate("el => {el.dataset.clicks='0'; el.addEventListener('click', () => el.dataset.clicks=String(Number(el.dataset.clicks)+1));}")
    editor.click(position={'x':coords['left'] + coords['char'] * 3, 'y':coords['top']})
    settled(page)
    assert editor.get_attribute('data-clicks') == '1'
    assert selected(editor) == [3, 3], (selected(editor), coords, page.evaluate('window.selectionTrace'))


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
