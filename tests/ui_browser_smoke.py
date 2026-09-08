from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# This test intentionally exercises the real FastAPI app + real browser.
# It exists because syntax/template checks cannot detect a UI controller that
# fails to load or fails to bind click/drag handlers.
ROOT = Path(__file__).resolve().parents[1]
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


def seed() -> tuple[int, str]:
    init_db()
    now = now_iso()
    period = current_period()
    with db() as conn:
        cur = conn.execute(
            """INSERT INTO customers
               (name,group_code,tax_id,payment_enabled,created_at,updated_at)
               VALUES(?,?,?,?,?,?)""",
            ("UI测试客户", "C0001", "TEST-TAX", 1, now, now),
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
                    f"1380000000{idx}",
                    f"53380000000{idx}",
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
    token, _, _ = create_session()
    return customer_id, token


def wait_http(url: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as r:
                if r.status == 200:
                    return
        except Exception as exc:  # pragma: no cover - diagnostic only
            last = exc
        time.sleep(0.2)
    raise RuntimeError(f"server did not start: {last}")


def main() -> None:
    customer_id, token = seed()
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

        from playwright.sync_api import sync_playwright  # noqa: E402

        page_errors: list[str] = []
        request_failures: list[str] = []
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            context.add_cookies([
                {
                    "name": "session_token",
                    "value": token,
                    "url": "http://127.0.0.1:8123",
                }
            ])
            page = context.new_page()
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.on(
                "requestfailed",
                lambda req: request_failures.append(f"{req.method} {req.url}: {req.failure}"),
            )

            page.goto(f"http://127.0.0.1:8123/customers/{customer_id}", wait_until="networkidle")

            assert page.locator(".v028-workspace").count() == 1, "v0.2.8 workspace was not rendered"
            assert page.locator('[data-customer-panel="payment"]').is_visible(), "payment panel not initially visible"

            # 1) Real customer-tab interaction, not a static DOM assertion.
            page.locator('[data-customer-tab="services"]').click()
            page.wait_for_timeout(80)
            assert page.locator('[data-customer-panel="services"]').is_visible(), "services tab click did not show services"
            assert not page.locator('[data-customer-panel="payment"]').is_visible(), "services tab click did not hide payment"

            page.locator('[data-customer-tab="payment"]').click()
            page.wait_for_timeout(80)
            assert page.locator('[data-customer-panel="payment"]').is_visible(), "payment tab click did not restore payment"

            # 2) Real pointer drag on the number-column separator.
            before = page.eval_on_selector(
                "#paymentSortable",
                "el => parseInt(getComputedStyle(el).getPropertyValue('--col-number'), 10)",
            )
            handle = page.locator('[data-resize-col="number"]').first
            box = handle.bounding_box()
            assert box, "number-column resize handle has no clickable box"
            x = box["x"] + box["width"] / 2
            y = box["y"] + box["height"] / 2
            page.mouse.move(x, y)
            page.mouse.down()
            page.mouse.move(x + 90, y, steps=6)
            page.mouse.up()
            page.wait_for_timeout(500)
            after = page.eval_on_selector(
                "#paymentSortable",
                "el => parseInt(getComputedStyle(el).getPropertyValue('--col-number'), 10)",
            )
            assert after >= before + 60, f"column resize did not move: before={before}, after={after}"

            # 3) Persistence is part of the feature: reload must retain this customer's width.
            page.reload(wait_until="networkidle")
            persisted = page.eval_on_selector(
                "#paymentSortable",
                "el => parseInt(getComputedStyle(el).getPropertyValue('--col-number'), 10)",
            )
            assert abs(persisted - after) <= 3, f"column width did not persist: after={after}, persisted={persisted}"

            browser.close()

        assert not page_errors, "browser page errors: " + " | ".join(page_errors)
        assert not request_failures, "browser request failures: " + " | ".join(request_failures)
        print("UI smoke test passed: tabs switch and per-customer column width drag/persist work in Chromium")
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
