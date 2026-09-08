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
DATA = ROOT / "data"
DB = DATA / "app.db"

for suffix in ("", "-wal", "-shm"):
    p = Path(str(DB) + suffix)
    if p.exists():
        p.unlink()

os.environ.setdefault("APP_USERNAME", "ui-test")
os.environ.setdefault("APP_PASSWORD_SALT", "dGVzdHNhbHQ=")
os.environ.setdefault("APP_PASSWORD_HASH", "not-used-by-this-test")
os.environ.setdefault("APP_SESSION_SECRET", "ui-test-session-secret")
os.environ.setdefault("APP_ENCRYPTION_KEY", "not-used-by-this-test")
os.environ.setdefault("APP_SECURE_COOKIE", "0")

from app.db import db, init_db, now_iso  # noqa: E402
from app.payment_v02 import current_period  # noqa: E402
from app.security import create_session  # noqa: E402


def month_add(d: date, months: int) -> date:
    idx = d.year * 12 + d.month - 1 + months
    year, month0 = divmod(idx, 12)
    return date(year, month0 + 1, 15)


def add_customer(conn, name: str, suffix: int) -> tuple[int, list[int]]:
    now = now_iso()
    period = current_period()
    cur = conn.execute(
        """INSERT INTO customers
           (name,group_code,tax_id,payment_enabled,created_at,updated_at)
           VALUES(?,?,?,?,?,?)""",
        (name, f"C000{suffix}", f"TEST-TAX-{suffix}", 1, now, now),
    )
    customer_id = int(cur.lastrowid)
    service_ids: list[int] = []
    for idx, amount in enumerate((100, 200), start=1):
        cur = conn.execute(
            """INSERT INTO services
               (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
                payment_cycle,payment_interval_months,active_from_period,sort_order,source_row)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                customer_id,
                "成员",
                f"测试{idx}",
                f"1380000{suffix:02d}{idx:03d}",
                f"5338000{suffix:02d}{idx:03d}",
                amount,
                0,
                "1个月",
                1,
                period,
                idx * 10,
                idx,
            ),
        )
        service_id = int(cur.lastrowid)
        service_ids.append(service_id)
        conn.execute(
            """INSERT INTO service_payment_rules
               (service_id,effective_period,mode,fixed_amount,created_at)
               VALUES(?,?,?,?,?)""",
            (service_id, "1900-01", "variable", 0, now),
        )
    return customer_id, service_ids


def seed() -> tuple[int, int, str]:
    init_db()
    now = now_iso()
    with db() as conn:
        c1, s1 = add_customer(conn, "UI测试客户A", 1)
        c2, _ = add_customer(conn, "UI测试客户B", 2)
        # 同一号码同时覆盖“已经到期 / 即将到期”，另加一条后续优惠用于确认不进入行动区。
        for name, expiry in (
            ("已到期优惠", date.today().isoformat()),
            ("即将到期优惠", month_add(date.today(), 2).isoformat()),
            ("后续优惠不显示", month_add(date.today(), 4).isoformat()),
        ):
            conn.execute(
                """INSERT INTO promotions
                   (service_id,name,start_date,expiry_date,remind_days,status,notes,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (s1[0], name, "", expiry, 60, "active", "", now),
            )
    token, _, _ = create_session()
    return c1, c2, token


def wait_http(url: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as r:
                if r.status == 200:
                    return
        except Exception as exc:
            last = exc
        time.sleep(0.2)
    raise RuntimeError(f"server did not start: {last}")


def read_width(page, key: str) -> int:
    value = page.eval_on_selector(
        "#paymentSortable",
        """(el, key) => {
          const raw = getComputedStyle(el).getPropertyValue(`--col-${key}`).trim();
          const n = Number.parseInt(raw, 10);
          return Number.isFinite(n) ? n : -1;
        }""",
        key,
    )
    assert value > 0, f"invalid {key} column width: {value}"
    return int(value)


def assert_near(a: float, b: float, tolerance: float, message: str) -> None:
    assert abs(a - b) <= tolerance, f"{message}: {a} vs {b}"


def main() -> None:
    customer_id, other_customer_id, token = seed()
    env = os.environ.copy()
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8123"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_http("http://127.0.0.1:8123/health")
        from playwright.sync_api import sync_playwright

        page_errors: list[str] = []
        request_failures: list[str] = []
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            context.grant_permissions(["clipboard-read", "clipboard-write"], origin="http://127.0.0.1:8123")
            context.add_cookies([{
                "name": "session_token",
                "value": token,
                "url": "http://127.0.0.1:8123",
            }])
            page = context.new_page()
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.on("requestfailed", lambda req: request_failures.append(f"{req.method} {req.url}: {req.failure}"))

            page.goto(f"http://127.0.0.1:8123/customers/{customer_id}", wait_until="networkidle")
            assert page.locator(".v028-workspace").count() == 1

            # 运行时只允许基础CSS + 当前CSS；不准再叠历史版本。
            hrefs = page.locator('link[rel="stylesheet"]').evaluate_all("els => els.map(x => x.getAttribute('href'))")
            assert len(hrefs) == 2, hrefs
            assert any("/static/app.css" in x for x in hrefs)
            assert any("/static/v028.css" in x for x in hrefs)
            assert not any(any(f"/static/v0{n}" in x for n in (2, 21, 22, 23, 24, 25, 26, 27)) for x in hrefs), hrefs

            # 客户功能键必须是真实的页内切换。
            for tab in ("services", "promotions", "contacts", "tasks", "visits", "payment"):
                page.locator(f'[data-customer-tab="{tab}"]').click()
                page.wait_for_timeout(60)
                assert page.locator(f'[data-customer-panel="{tab}"]').is_visible(), f"tab failed: {tab}"
                visible = page.locator('[data-customer-panel]:visible').count()
                assert visible == 1, f"more than one customer panel visible after {tab}: {visible}"

            # 缴费四列必须各自存在拖动柄并可独立调宽。
            assert page.locator('[data-resize-col]').count() == 4
            before = read_width(page, "number")
            attr_before = read_width(page, "attr")
            handle = page.locator('[data-resize-col="number"]').first
            box = handle.bounding_box()
            assert box and box["width"] >= 16, "number resize handle is not practically draggable"
            x = box["x"] + box["width"] / 2
            y = box["y"] + box["height"] / 2
            page.mouse.move(x, y)
            page.mouse.down()
            page.mouse.move(x + 90, y, steps=8)
            page.mouse.up()
            page.wait_for_timeout(500)
            after = read_width(page, "number")
            assert after >= before + 55, (before, after)
            assert_near(read_width(page, "attr"), attr_before, 3, "resizing number changed attr width")

            page.reload(wait_until="networkidle")
            persisted = read_width(page, "number")
            assert_near(persisted, after, 3, "column width did not persist")
            page.goto(f"http://127.0.0.1:8123/customers/{other_customer_id}", wait_until="networkidle")
            other_width = read_width(page, "number")
            assert_near(other_width, before, 3, "column width leaked to another customer")

            # 业务编辑：dialog 不改变滚动位置；周期是纯文本手输；模板新增全局生效。
            page.goto(f"http://127.0.0.1:8123/customers/{customer_id}?tab=services", wait_until="networkidle")
            page.evaluate("window.scrollTo(0, Math.min(650, document.body.scrollHeight - innerHeight))")
            page.wait_for_timeout(80)
            y_before = page.evaluate("window.scrollY")
            page.locator('[data-open-service-editor]').first.click()
            page.locator('#businessAttributeDialog').wait_for(state="visible")
            y_open = page.evaluate("window.scrollY")
            assert_near(y_open, y_before, 2, "opening business editor moved page")

            cycle_row = page.locator('.global-attribute-row-v028[data-key="payment_interval_months"]')
            assert cycle_row.count() == 1
            cycle_input = cycle_row.locator('.attr-value')
            assert cycle_input.get_attribute('type') == 'text', "payment interval is not manual text input"
            old_cycle = cycle_input.input_value()
            cycle_input.focus()
            page.mouse.wheel(0, -600)
            page.wait_for_timeout(50)
            assert cycle_input.input_value() == old_cycle, "mouse wheel changed payment interval"

            page.locator('[data-add-global-attribute]').click()
            new_row = page.locator('.global-attribute-row-v028').last
            new_row.locator('.attr-label').fill('全局测试属性')
            new_row.locator('.attr-value').fill('A值')
            page.locator('[data-business-attribute-form] button[type="submit"]').click()
            page.locator('#businessAttributeDialog').wait_for(state="hidden")
            y_saved = page.evaluate("window.scrollY")
            assert_near(y_saved, y_before, 3, "saving business editor moved page")
            assert page.locator('.business-attribute', has_text='全局测试属性').count() >= 1
            assert page.locator('.business-attribute', has_text='A值').count() >= 1

            # 另一个客户打开编辑器也必须同步出现新增属性。
            page.goto(f"http://127.0.0.1:8123/customers/{other_customer_id}?tab=services", wait_until="networkidle")
            page.locator('[data-open-service-editor]').first.click()
            page.locator('#businessAttributeDialog').wait_for(state="visible")
            global_row = page.locator('.global-attribute-row-v028').filter(has=page.locator('.attr-label[value="全局测试属性"]'))
            if global_row.count() == 0:
                # Chromium对动态input的[value]选择器不反映property，用evaluate筛。
                count = page.locator('.global-attribute-row-v028').evaluate_all("rows => rows.filter(r => r.querySelector('.attr-label')?.value === '全局测试属性').length")
                assert count == 1, "global attribute did not propagate to another customer"
            page.locator('[data-business-editor-close]').first.click()
            page.locator('#businessAttributeDialog').wait_for(state="hidden")

            # 优惠：两列、无后续到期、号码复制+优惠名复制、日期框紧凑。
            page.goto(f"http://127.0.0.1:8123/customers/{customer_id}?tab=promotions", wait_until="networkidle")
            columns = page.locator('.promo-column-v028')
            assert columns.count() == 2
            left = columns.nth(0).bounding_box(); right = columns.nth(1).bounding_box()
            assert left and right and right['x'] > left['x'] + left['width'] * 0.65, "promotion columns are not side by side"
            assert_near(left['y'], right['y'], 3, "promotion columns are not aligned")
            assert page.get_by_text('已经到期', exact=True).count() == 1
            assert page.get_by_text('即将到期', exact=True).count() == 1
            assert page.get_by_text('后续优惠不显示', exact=True).count() == 0

            name_box = page.locator('.promo-name-copy-v028').first.bounding_box()
            expiry_box = page.locator('.promo-expiry-input-v028').first.bounding_box()
            assert name_box and expiry_box
            assert expiry_box['width'] <= 150, f"promotion expiry input too wide: {expiry_box['width']}"
            assert_near(name_box['height'], expiry_box['height'], 4, "promotion name and expiry controls differ too much in height")

            number_btn = page.locator('.promo-number-copy-v028').first
            expected_number = number_btn.get_attribute('data-copy-silent')
            number_btn.click(); page.wait_for_timeout(80)
            copied = page.evaluate("navigator.clipboard.readText()")
            assert copied == expected_number, (copied, expected_number)
            assert page.locator('.app-toast').count() == 0, "silent number copy displayed a toast"
            name_btn = page.locator('.promo-name-copy-v028').first
            expected_name = name_btn.get_attribute('data-copy-silent')
            name_btn.click(); page.wait_for_timeout(80)
            copied = page.evaluate("navigator.clipboard.readText()")
            assert copied == expected_name, (copied, expected_name)
            assert page.locator('.app-toast').count() == 0, "silent promo-name copy displayed a toast"

            # 首页优惠必须按客户汇总，而不是按每条优惠展开。
            page.goto("http://127.0.0.1:8123/?home=promos", wait_until="networkidle")
            assert page.locator('[data-home-panel="promos"]').is_visible()
            rows = page.locator('.home-promo-customer')
            assert rows.count() == 1, f"home promotions not grouped by customer: {rows.count()}"
            assert 'UI测试客户A' in rows.first.inner_text()

            browser.close()

        assert not page_errors, "browser page errors: " + " | ".join(page_errors)
        assert not request_failures, "browser request failures: " + " | ".join(request_failures)
        print("UI acceptance passed: single CSS, tabs, 4-column resize, business global attributes, manual cycle, promotion workflow")
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
        if server.returncode not in (0, -15):
            output = server.stdout.read() if server.stdout else ""
            print(output, file=sys.stderr)


if __name__ == "__main__":
    main()
