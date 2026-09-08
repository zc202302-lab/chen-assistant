from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# Real FastAPI + real Chromium smoke test. Syntax/template checks alone are not
# sufficient for interactive UI features such as tab switching and column drag.
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


def add_customer(conn, name: str, suffix: int) -> int:
    now = now_iso()
    period = current_period()
    cur = conn.execute(
        """INSERT INTO customers
           (name,group_code,tax_id,payment_enabled,created_at,updated_at)
           VALUES(?,?,?,?,?,?)""",
        (name, f"C000{suffix}", f"TEST-TAX-{suffix}", 1, now, now),
    )
    customer_id = int(cur.lastrowid)
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
        conn.execute(
            """INSERT INTO service_payment_rules
               (service_id,effective_period,mode,fixed_amount,created_at)
               VALUES(?,?,?,?,?)""",
            (service_id, "1900-01", "variable", 0, now),
        )
    return customer_id


def seed() -> tuple[int, int, str]:
    init_db()
    with db() as conn:
        c1 = add_customer(conn, "UI测试客户A", 1)
        c2 = add_customer(conn, "UI测试客户B", 2)
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
          const name = `--col-${key}`;
          const inlineValue = el.style.getPropertyValue(name).trim();
          const computedValue = getComputedStyle(el).getPropertyValue(name).trim();
          const raw = inlineValue || computedValue;
          const n = Number.parseInt(raw, 10);
          return Number.isFinite(n) ? n : -1;
        }""",
        key,
    )
    assert value > 0, f"invalid {key} column width: {value}"
    return int(value)


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
            context.add_cookies([{
                "name": "session_token",
                "value": token,
                "url": "http://127.0.0.1:8123",
            }])
            page = context.new_page()
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.on("requestfailed", lambda req: request_failures.append(f"{req.method} {req.url}: {req.failure}"))

            page.goto(f"http://127.0.0.1:8123/customers/{customer_id}", wait_until="networkidle")
            assert page.locator(".v028-workspace").count() == 1, "v0.2.8 workspace was not rendered"
            assert page.locator('[data-customer-panel="payment"]').is_visible(), "payment panel not initially visible"

            # Real customer-tab interaction.
            page.locator('[data-customer-tab="services"]').click()
            page.wait_for_timeout(100)
            assert page.locator('[data-customer-panel="services"]').is_visible(), "services tab click did not show services"
            assert not page.locator('[data-customer-panel="payment"]').is_visible(), "services tab click did not hide payment"

            page.locator('[data-customer-tab="payment"]').click()
            page.wait_for_timeout(100)
            assert page.locator('[data-customer-panel="payment"]').is_visible(), "payment tab click did not restore payment"

            # Real pointer drag on number column separator.
            before = read_width(page, "number")
            handle = page.locator('[data-resize-col="number"]').first
            box = handle.bounding_box()
            assert box, "number-column resize handle has no clickable box"
            x = box["x"] + box["width"] / 2
            y = box["y"] + box["height"] / 2
            page.mouse.move(x, y)
            page.mouse.down()
            page.mouse.move(x + 90, y, steps=8)
            page.mouse.up()
            page.wait_for_timeout(600)
            after = read_width(page, "number")
            assert after >= before + 55, f"column resize did not move enough: before={before}, after={after}"

            # Persistence for this customer.
            page.reload(wait_until="networkidle")
            persisted = read_width(page, "number")
            assert abs(persisted - after) <= 3, f"column width did not persist: after={after}, persisted={persisted}"

            # Isolation: another customer must keep its own default width.
            page.goto(f"http://127.0.0.1:8123/customers/{other_customer_id}", wait_until="networkidle")
            other_width = read_width(page, "number")
            assert abs(other_width - before) <= 3, f"column width leaked to another customer: first_before={before}, other={other_width}"

            browser.close()

        assert not page_errors, "browser page errors: " + " | ".join(page_errors)
        assert not request_failures, "browser request failures: " + " | ".join(request_failures)
        print("UI smoke test passed: tabs switch; column drag persists per customer")
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
