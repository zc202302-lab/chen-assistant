from __future__ import annotations

import os
import sys
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

from fastapi.testclient import TestClient  # noqa: E402
from app.db import db, init_db, now_iso  # noqa: E402
from app.main import app  # noqa: E402
from app.payment_v02 import current_period  # noqa: E402
from app.security import create_session  # noqa: E402


def month_add(d: date, months: int) -> date:
    idx = d.year * 12 + (d.month - 1) + months
    year, month0 = divmod(idx, 12)
    return date(year, month0 + 1, 15)


def seed() -> tuple[int, str]:
    init_db()
    now = now_iso()
    period = current_period()
    with db() as conn:
        cur = conn.execute(
            """INSERT INTO customers
               (name,group_code,tax_id,payment_enabled,created_at,updated_at)
               VALUES(?,?,?,?,?,?)""",
            ("优惠渲染回归客户", "PROMO001", "PROMO-TAX", 1, now, now),
        )
        customer_id = int(cur.lastrowid)
        cur = conn.execute(
            """INSERT INTO services
               (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
                payment_cycle,payment_interval_months,active_from_period,sort_order,source_row)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                customer_id,
                "成员",
                "后勤",
                "13800138000",
                "5338000000001",
                88,
                0,
                "1个月",
                1,
                period,
                10,
                1,
            ),
        )
        service_id = int(cur.lastrowid)
        conn.execute(
            """INSERT INTO service_payment_rules
               (service_id,effective_period,mode,fixed_amount,created_at)
               VALUES(?,?,?,?,?)""",
            (service_id, "1900-01", "variable", 0, now),
        )
        expiry_expired = date.today().isoformat()
        expiry_soon = month_add(date.today(), 2).isoformat()
        for name, expiry in (
            ("优惠A", expiry_expired),
            ("优惠B", expiry_expired),
            ("优惠C", expiry_soon),
        ):
            conn.execute(
                """INSERT INTO promotions
                   (service_id,name,start_date,expiry_date,remind_days,status,notes,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (service_id, name, "", expiry, 60, "active", "", now),
            )
    token, _, _ = create_session()
    return customer_id, token


def main() -> None:
    customer_id, token = seed()
    client = TestClient(app)
    client.cookies.set("session_token", token)

    response = client.get(f"/customers/{customer_id}?tab=promotions")
    assert response.status_code == 200, response.text
    html = response.text
    assert "优惠续约工作区" in html
    assert "已经到期" in html
    assert "即将到期" in html
    assert html.count("13800138000") >= 2
    assert "优惠A" in html and "优惠B" in html and "优惠C" in html
    assert html.count('data-promo-item') >= 3
    print("promotion render regression passed")


if __name__ == "__main__":
    main()
