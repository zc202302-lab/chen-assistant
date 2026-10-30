from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = ROOT / 'data' / 'app.db'
for suffix in ('', '-wal', '-shm'):
    p = Path(str(DB) + suffix)
    if p.exists():
        p.unlink()

os.environ.update({
    'APP_USERNAME': 'ui-test',
    'APP_PASSWORD_SALT': 'dGVzdHNhbHQ=',
    'APP_PASSWORD_HASH': 'x',
    'APP_SESSION_SECRET': 'ui-test-session-secret',
    'APP_ENCRYPTION_KEY': 'x',
    'APP_SECURE_COOKIE': '0',
})

from app.db import db, init_db, now_iso  # noqa: E402
from app.payment_v02 import add_periods, current_period  # noqa: E402
from app.security import create_session  # noqa: E402


def seed():
    init_db()
    now = now_iso()
    period = current_period()
    future = add_periods(period, 2)
    with db() as conn:
        cid = int(conn.execute(
            'INSERT INTO customers (name,group_code,tax_id,payment_enabled,created_at,updated_at) VALUES(?,?,?,?,?,?)',
            ('v0211双向同步客户', 'SYNC211', 'SYNC211-TAX', 1, now, now),
        ).lastrowid)
        service_ids = []
        specs = [
            ('成员', '甲', '13800130211', '5338000020211', 1, '', '微信'),
            ('专线', '乙', '13800130212', '5338000020212', 3, future, '转账'),
            ('宽带', '丙', '13800130213', '5338000020213', 1, '', '支付宝'),
        ]
        for idx, (typ, holder, number, account, months, next_period, method) in enumerate(specs, 1):
            sid = int(conn.execute(
                '''INSERT INTO services
                   (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
                    payment_cycle,payment_interval_months,next_payment_period,active_from_period,
                    sort_order,source_row,payment_method,invoice_type,package_type,notes)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (cid, typ, holder, number, account, 80 + idx, 0,
                 f'{months}个月', months, next_period, period, idx * 10, idx,
                 method, '普票', f'套餐{idx}', f'备注{idx}'),
            ).lastrowid)
            service_ids.append(sid)
            conn.execute(
                'INSERT INTO service_payment_rules (service_id,effective_period,mode,fixed_amount,created_at) VALUES(?,?,?,?,?)',
                (sid, '1900-01', 'variable', 0, now),
            )
        pid = int(conn.execute(
            '''INSERT INTO promotions(service_id,name,start_date,expiry_date,remind_days,status,notes,created_at)
               VALUES(?,?,?,?,?,?,?,?)''',
            (service_ids[0], '原优惠名称', '', date.today().isoformat(), 60, 'active', '优惠备注', now),
        ).lastrowid)
    token, _, _ = create_session()
    return cid, service_ids, pid, token


def wait_http(url: str):
    for _ in range(80):
        try:
            if urllib.request.urlopen(url, timeout=1).status == 200:
                return
        except Exception:
            pass
        time.sleep(.2)
    raise RuntimeError('server start failed')


def service_order(page, selector):
    return page.locator(selector).evaluate_all('rows => rows.map(r => Number(r.dataset.serviceId))')


def drag_handle_to_before(page, handle, target):
    """Perform a real pointer drag and wait until the reorder POST is persisted.

    The dragged row is removed from normal layout as soon as pointerdown starts, so the
    target row can move. Re-read its bounding box after drag startup instead of using a
    stale pre-drag coordinate; this keeps the browser acceptance deterministic while
    still exercising the real pointer sorter and backend persistence.
    """
    hb = handle.bounding_box()
    assert hb, hb
    x = hb['x'] + hb['width'] / 2
    y = hb['y'] + hb['height'] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.wait_for_timeout(80)
    assert page.locator('.sort-drag-ghost-v0211').count() == 1, 'drag ghost missing'
    assert page.locator('.sort-insertion-placeholder-v0211').count() == 1, 'insertion slot missing'

    tb = target.bounding_box()
    assert tb, tb
    target_x = tb['x'] + min(70, max(12, tb['width'] / 4))
    target_y = tb['y'] + min(7, max(3, tb['height'] * .18))
    page.mouse.move(target_x, target_y, steps=12)
    page.wait_for_timeout(100)

    with page.expect_response(
        lambda response: '/services/reorder' in response.url and response.request.method == 'POST',
        timeout=5000,
    ) as response_info:
        page.mouse.up()
    response = response_info.value
    assert response.ok, (response.status, response.url)
    payload = response.json()
    assert payload.get('ok') is True, payload
    page.wait_for_timeout(120)

    assert page.locator('.sort-drag-ghost-v0211').count() == 0
    assert page.locator('.sort-insertion-placeholder-v0211').count() == 0


def main():
    cid, (s1, s2, s3), pid, token = seed()
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8128'],
        cwd=ROOT,
        env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8128/health')
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1500, 'height': 1000})
            context.add_cookies([{'name': 'session_token', 'value': token, 'url': 'http://127.0.0.1:8128'}])
            context.grant_permissions(['clipboard-read', 'clipboard-write'], origin='http://127.0.0.1:8128')
            page = context.new_page()
            page.goto(f'http://127.0.0.1:8128/customers/{cid}', wait_until='networkidle')

            # 缴费不再只有“两个默认属性”，而是任意数量的属性列；金额正式叫“本月缴费”。
            assert page.locator('#displayAttributeDialog').count() == 0
            assert page.locator('#paymentColumnsDialog').count() == 1
            labels = [x.strip() for x in page.locator('[data-payment-column-head] > span').all_inner_texts()]
            assert labels == ['类型', '姓名/属性', '号码', '账号', '本月缴费'], labels
            assert page.locator('[data-payment-row]').count() == 2, 'future quarterly service leaked into payment workbench'
            assert service_order(page, '[data-payment-row]') == [s1, s3]

            # Single click exposes full text; selecting a substring inside must
            # survive pointer events, and clicking outside dismisses the preview.
            cell = page.locator('[data-payment-business-cell]').first
            original = cell.locator('strong').inner_text()
            full = '完整信息：长文本 <script>不可执行</script>\n第二行可单独复制'
            cell.locator('strong').evaluate('(el, text) => el.textContent = text', full)
            cell.click()
            preview = page.locator('.workspace-cell-preview')
            assert preview.inner_text() == full
            assert preview.locator('script').count() == 0
            preview.evaluate("""el => {
                const range = document.createRange();
                range.setStart(el.firstChild, 0); range.setEnd(el.firstChild, 4);
                const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
            }""")
            assert page.evaluate('getSelection().toString()') == '完整信息'
            assert preview.evaluate("el => getComputedStyle(el).userSelect") == 'text'
            preview.click(position={'x': 10, 'y': 10})
            assert preview.is_visible()
            page.locator('h2:visible').first.click()
            assert not preview.is_visible()
            cell.click()
            page.keyboard.press('Escape')
            assert not preview.is_visible()

            cell.locator('strong').evaluate('(el, text) => el.textContent = text', original)

            # 属性设置可增加第6列，证明不是原来的两个属性选择器。
            page.locator('[data-payment-columns-settings]').click()
            dialog = page.locator('#paymentColumnsDialog')
            dialog.wait_for(state='visible')
            assert dialog.locator('[data-payment-column-row]').count() == 5
            dialog.locator('[data-payment-column-add]').click()
            assert dialog.locator('[data-payment-column-row]').count() == 6
            last_select = dialog.locator('[data-payment-column-row]').last.locator('select')
            last_select.select_option('payment_method')
            assert dialog.locator('[data-payment-column-row] select').evaluate_all("sels => sels.map(s => s.value).includes('payment_amount')")
            with page.expect_navigation(wait_until='networkidle'):
                dialog.locator('button[type="submit"]').click()
            labels = [x.strip() for x in page.locator('[data-payment-column-head] > span').all_inner_texts()]
            assert labels[-1] == '付款方式', labels
            assert '本月缴费' in labels and len(labels) == 6, labels

            # 缴费页修改同一条业务属性：双击属性值，直接编辑共同的业务主数据。
            payment_row1 = page.locator(f'[data-payment-row][data-service-id="{s1}"]')
            holder_cell = payment_row1.locator('[data-payment-attr-key="holder_name"]')
            holder_cell.dblclick()
            business_dialog = page.locator('#businessAttributeDialog')
            business_dialog.wait_for(state='visible')
            holder_input = business_dialog.locator('.global-attribute-row-v028[data-key="holder_name"] .attr-value')
            holder_input.fill('缴费页修改甲')
            business_dialog.locator('[data-business-attribute-form] button[type="submit"]').click()
            business_dialog.wait_for(state='hidden')
            page.wait_for_timeout(250)
            assert payment_row1.locator('[data-payment-attr-key="holder_name"] strong').inner_text() == '缴费页修改甲'
            page.locator('[data-customer-tab="services"]').click()
            business_row1 = page.locator(f'[data-business-row][data-service-id="{s1}"]')
            assert '缴费页修改甲' in business_row1.inner_text(), 'payment edit did not sync into business module'

            # 反向：业务页修改后，缴费工作区也立刻读取相同主数据。
            business_row1.locator('[data-open-service-editor]').click()
            business_dialog.wait_for(state='visible')
            holder_input = business_dialog.locator('.global-attribute-row-v028[data-key="holder_name"] .attr-value')
            holder_input.fill('业务页修改甲')
            business_dialog.locator('[data-business-attribute-form] button[type="submit"]').click()
            business_dialog.wait_for(state='hidden')
            page.wait_for_timeout(250)
            page.locator('[data-customer-tab="payment"]').click()
            assert payment_row1.locator('[data-payment-attr-key="holder_name"] strong').inner_text() == '业务页修改甲'

            # 本月缴费也是可操作属性；修改后 payment_entries 与 services.monthly_fee 同步。
            amount = payment_row1.locator('.quick-amount')
            amount.fill('123.45')
            amount.press('Enter')
            page.wait_for_timeout(300)
            assert amount.input_value() in {'123.45', '123.450'}, amount.input_value()

            # 从缴费子集拖动：非本月应缴的 s2 不在缴费页，但必须保留其在完整业务顺序中的中间槽位。
            payment_row3 = page.locator(f'[data-payment-row][data-service-id="{s3}"]')
            drag_handle_to_before(page, payment_row3.locator('.drag-handle'), payment_row1)
            assert service_order(page, '[data-payment-row]') == [s3, s1]
            page.locator('[data-customer-tab="services"]').click()
            assert service_order(page, '[data-business-row]') == [s3, s2, s1], 'payment subset reorder corrupted full business order'

            # 业务列表本身也能拖动；落点沿用同一套“拿起 + 插入位 + 周围行让位”效果。
            business_row1 = page.locator(f'[data-business-row][data-service-id="{s1}"]')
            business_row3 = page.locator(f'[data-business-row][data-service-id="{s3}"]')
            drag_handle_to_before(page, business_row1.locator('.business-drag-handle'), business_row3)
            assert service_order(page, '[data-business-row]') == [s1, s3, s2]
            page.locator('[data-customer-tab="payment"]').click()
            assert service_order(page, '[data-payment-row]') == [s1, s3], 'business reorder did not sync into payment module'

            # 优惠工作区修改名称后，业务完整编辑器看到的是同一条优惠记录。
            page.locator('[data-customer-tab="promotions"]').click()
            promo_btn = page.locator(f'[data-promo-item][data-promo-id="{pid}"] .promo-name-copy-v028')
            promo_btn.wait_for(state='visible')
            promo_btn.dblclick()
            inline = page.locator(f'[data-promo-item][data-promo-id="{pid}"] .promo-name-inline-edit-v030')
            inline.wait_for(state='visible')
            inline.fill('优惠模块改名')
            inline.press('Enter')
            page.wait_for_timeout(220)
            page.locator('[data-customer-tab="services"]').click()
            page.locator(f'[data-business-row][data-service-id="{s1}"] [data-open-service-editor]').click()
            business_dialog.wait_for(state='visible')
            promo_name = business_dialog.locator(f'.editor-promo-row-v029[data-promo-id="{pid}"] .editor-promo-name-v029')
            promo_name.wait_for(state='visible')
            assert promo_name.input_value() == '优惠模块改名'
            business_dialog.locator('[data-business-editor-close]').first.click()
            business_dialog.wait_for(state='hidden')

            browser.close()

        with db() as conn:
            ordered = [r['id'] for r in conn.execute(
                'SELECT id FROM services WHERE customer_id=? ORDER BY sort_order,id', (cid,)
            ).fetchall()]
            assert ordered == [s1, s3, s2], ordered
            service = conn.execute('SELECT holder_name,monthly_fee FROM services WHERE id=?', (s1,)).fetchone()
            assert service['holder_name'] == '业务页修改甲'
            assert abs(float(service['monthly_fee']) - 123.45) < 0.001
            pe = conn.execute('SELECT amount,confirmed FROM payment_entries WHERE service_id=? AND period=?', (s1, current_period())).fetchone()
            assert pe and abs(float(pe['amount']) - 123.45) < 0.001 and pe['confirmed'] == 1
            promo = conn.execute('SELECT name FROM promotions WHERE id=?', (pid,)).fetchone()
            assert promo['name'] == '优惠模块改名'
        print('v0.2.11 dynamic payment and bidirectional sorting acceptance passed')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
