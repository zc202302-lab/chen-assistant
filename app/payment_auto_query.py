from __future__ import annotations

import re

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from . import v031_payment_workflow_routes as workflow
from .db import db, now_iso
from .payment_v02 import current_period, parse_money, service_active_in_period, service_is_due
from .v023_routes import service_or_404
from .v026_routes import check_csrf
from .v031_fixed_review_patch import (
    _ensure_payment_entry_review_aware,
    _payment_payload,
    _rollback_completed_payment,
)


router = APIRouter()
AUTO_QUERY_SOURCE = "auto_query"
TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,80}$")


@router.post("/services/{service_id}/payment-auto-query-result")
def apply_payment_auto_query_result(
    request: Request,
    service_id: int,
    csrf: str = Form(...),
    amount: str = Form(...),
    task_id: str = Form(...),
    query_value: str = Form(...),
):
    """Atomically apply a verified browser-query result and confirm that row."""
    check_csrf(request, csrf)
    if not TASK_ID_RE.fullmatch(task_id.strip()):
        raise HTTPException(400, "自动查询任务编号无效")
    value = parse_money(amount)
    if value < 0:
        raise HTTPException(400, "自动查询金额不能为负数")

    period = current_period()
    with db() as conn:
        service = service_or_404(conn, service_id)
        expected_values = {
            str(service["number"] or "").strip(),
            str(service["account"] or "").strip(),
        } - {""}
        if query_value.strip() not in expected_values:
            raise HTTPException(409, "查询号码与当前业务不一致，已拒绝回填")

        existing_current = conn.execute(
            "SELECT id FROM payment_entries WHERE service_id=? AND period=?",
            (service_id, period),
        ).fetchone()
        if not service_active_in_period(service, period) or (
            not service_is_due(service) and not existing_current
        ):
            raise HTTPException(400, "这项业务本月不在缴费范围内")

        entry, rule = _ensure_payment_entry_review_aware(conn, service, period)
        previous = float(entry["amount"] or 0)
        amount_changed = abs(float(value) - previous) > 0.000001
        run, _ = workflow._run_v031(conn, int(service["customer_id"]), period)
        if amount_changed and run["paid"]:
            _rollback_completed_payment(conn, int(service["customer_id"]), period, run)

        reference = entry["reference_amount"]
        if reference is None:
            reference = previous
        now = now_iso()
        conn.execute(
            """UPDATE payment_entries
               SET amount=?,reference_amount=?,source=?,confirmed=1,updated_at=?
               WHERE id=?""",
            (value, reference, AUTO_QUERY_SOURCE, now, entry["id"]),
        )
        conn.execute("UPDATE services SET monthly_fee=? WHERE id=?", (value, service_id))

        if rule["mode"] == "fixed":
            conn.execute(
                """INSERT INTO service_payment_rules
                   (service_id,effective_period,mode,fixed_amount,created_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(service_id,effective_period)
                   DO UPDATE SET mode='fixed',fixed_amount=excluded.fixed_amount""",
                (service_id, period, "fixed", value, now),
            )
            conn.execute("UPDATE services SET fixed_fee=1 WHERE id=?", (service_id,))

        if amount_changed and not run["paid"]:
            workflow._invalidate_after_amount_change(
                conn, int(service["customer_id"]), period, run
            )

        payload = _payment_payload(conn, int(service["customer_id"]), period, service_id)
        current_run, current_stats = workflow._run_v031(
            conn, int(service["customer_id"]), period
        )
        payload.update(current_stats)
        payload.update(
            {
                "task_id": task_id,
                "source": AUTO_QUERY_SOURCE,
                "workflow_invalidated": amount_changed,
                "workflow_run": current_run,
            }
        )
        return JSONResponse(payload)
