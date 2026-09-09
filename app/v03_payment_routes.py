from __future__ import annotations

from fastapi import APIRouter, Request, Form
from fastapi.responses import JSONResponse

from .db import db
from .payment_v02 import current_period
from .v025_routes import customer_or_404
from . import v03_routes as v03

router = APIRouter()


@router.post('/customers/{customer_id}/payment-run')
def set_payment_run_v03_safe(
    request: Request,
    customer_id: int,
    csrf: str = Form(...),
    action: str = Form(...),
):
    """Guard v0.3 paid undo for runs that predate reversible snapshots.

    v0.2.x could mark a customer paid and immediately mutate service cycle fields,
    but it did not preserve the pre-payment service state. Guessing those values on
    an undo would be dangerous, so legacy paid runs are deliberately non-reversible.
    All payments completed by v0.3 create snapshots first and remain fully undoable.
    """
    if action == 'paid':
        period = current_period()
        with db() as conn:
            customer_or_404(conn, customer_id)
            v03._ensure_v03(conn)
            run = conn.execute(
                '''SELECT id,paid_at FROM customer_payment_runs
                   WHERE customer_id=? AND period=?''',
                (customer_id, period),
            ).fetchone()
            if run and (run['paid_at'] or '').strip():
                snapshot_count = conn.execute(
                    'SELECT COUNT(*) n FROM payment_run_service_snapshots_v03 WHERE run_id=?',
                    (run['id'],),
                ).fetchone()['n']
                if not snapshot_count:
                    return JSONResponse(
                        {
                            'ok': False,
                            'error': '这条“完成缴费”记录来自旧版本，没有保存缴费前的周期快照。为保护缴费周期，系统不允许自动撤回。',
                        },
                        status_code=409,
                    )

    return v03.set_payment_run_v03(
        request=request,
        customer_id=customer_id,
        csrf=csrf,
        action=action,
    )
