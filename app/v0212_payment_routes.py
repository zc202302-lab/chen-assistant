from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import JSONResponse

from .db import db, now_iso
from .payment_v02 import current_period, add_periods, service_interval_months
from .v025_routes import customer_or_404, _payment_run
from .v026_routes import check_csrf
from .v0212_routes import payment_snapshot_v0212, _save_runtime

router = APIRouter()


def next_period_after_actual_payment(period: str, months: int) -> str:
    """The recurring cycle restarts from the month payment was actually completed."""
    months = int(months or 0)
    if months <= 1:
        return ''
    return add_periods(period, months)


@router.post('/customers/{customer_id}/payment-run')
def set_payment_run_v0212_actual_cycle(
    request: Request,
    customer_id: int,
    csrf: str = Form(...),
    action: str = Form(...),
):
    check_csrf(request, csrf)
    period = current_period()
    with db() as conn:
        customer_or_404(conn, customer_id)
        items, stats = payment_snapshot_v0212(conn, customer_id, period)
        run = _payment_run(conn, customer_id, period, stats)
        now = now_iso()

        if action == 'notify':
            if stats['pending']:
                return JSONResponse(
                    {'ok': False, 'error': f"还有 {stats['pending']} 项金额未核对，暂不能标记已通知"},
                    status_code=400,
                )
            conn.execute(
                'UPDATE customer_payment_runs SET notified_at=?,updated_at=? WHERE id=?',
                (now, now, run['id']),
            )
            conn.execute(
                'UPDATE customers SET payment_period=?,notified=1,completed=0,updated_at=? WHERE id=?',
                (period, now, customer_id),
            )

        elif action == 'paid':
            if stats['pending']:
                return JSONResponse(
                    {'ok': False, 'error': f"还有 {stats['pending']} 项金额未核对，暂不能完成缴费"},
                    status_code=400,
                )
            if not run['notified']:
                return JSONResponse(
                    {'ok': False, 'error': '请先标记“已通知客户”，再完成缴费'},
                    status_code=400,
                )

            if not run['paid']:
                today_iso = date.today().isoformat()
                for item in items:
                    service = item['row']
                    months = service_interval_months(service)
                    next_period = next_period_after_actual_payment(period, months)
                    conn.execute(
                        'UPDATE services SET last_payment_date=?,next_payment_period=? WHERE id=?',
                        (today_iso, next_period, service['id']),
                    )
                    _save_runtime(conn, service['id'], deferred_until_period='')

            conn.execute(
                'UPDATE customer_payment_runs SET paid_at=?,updated_at=? WHERE id=?',
                (now, now, run['id']),
            )
            conn.execute(
                'UPDATE customers SET payment_period=?,notified=1,completed=1,updated_at=? WHERE id=?',
                (period, now, customer_id),
            )

        else:
            raise HTTPException(400, '状态操作无效')

        _, stats2 = payment_snapshot_v0212(conn, customer_id, period)
        updated = _payment_run(conn, customer_id, period, stats2)

    return JSONResponse({'ok': True, 'run': updated, 'stats': stats2})
