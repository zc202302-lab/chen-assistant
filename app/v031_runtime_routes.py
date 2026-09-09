from __future__ import annotations

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import JSONResponse

from .db import db, now_iso
from .payment_v02 import current_period
from .v025_routes import customer_or_404, service_or_404
from .v026_routes import check_csrf
from .v028_routes import _template
from . import v0212_routes as core
from . import v0212_business_display_routes as business_display
from . import v03_routes as v03

router = APIRouter()


def _run_state_direct(conn, customer_id: int):
    """Read/create the current workflow state without depending on mail setup or frontend state."""
    period = current_period()
    customer_or_404(conn, customer_id)
    v03._ensure_v03(conn)
    _, stats = core.payment_snapshot_v0212(conn, customer_id, period)
    row = conn.execute(
        'SELECT * FROM customer_payment_runs WHERE customer_id=? AND period=?',
        (customer_id, period),
    ).fetchone()
    if not row:
        now = now_iso()
        conn.execute(
            '''INSERT INTO customer_payment_runs
               (customer_id,period,reviewed_at,notified_at,paid_at,emailed_at,email_to,email_subject,created_at,updated_at)
               VALUES(?,?,\'\',\'\',\'\',\'\',\'\',\'\',?,?)''',
            (customer_id, period, now, now),
        )
        row = conn.execute(
            'SELECT * FROM customer_payment_runs WHERE customer_id=? AND period=?',
            (customer_id, period),
        ).fetchone()

    ready = int(stats.get('pending', 0)) == 0
    reviewed = bool((row['reviewed_at'] or '').strip())
    notified = bool((row['notified_at'] or '').strip())
    paid = bool((row['paid_at'] or '').strip())
    if paid:
        stage, label = 'paid', '已完成缴费'
    elif notified:
        stage, label = 'notified', '已通知客户，待完成缴费'
    elif reviewed:
        stage, label = 'reviewed', '金额已核对，待通知客户'
    elif ready:
        stage, label = 'ready', '金额可确认'
    else:
        stage, label = 'checking', '正在核对金额'

    return {
        'id': int(row['id']),
        'stage': stage,
        'label': label,
        'ready': ready,
        'reviewed': reviewed,
        'notified': notified,
        'paid': paid,
        'pending': int(stats.get('pending', 0)),
    }, stats


@router.get('/customers/{customer_id}/workflow-state-v03')
def workflow_state_v03(customer_id: int):
    with db() as conn:
        run, stats = _run_state_direct(conn, customer_id)
    return JSONResponse({'ok': True, 'run': run, 'stats': stats})


@router.post('/services/{service_id}/payment-status-v03')
def save_payment_status_v03(
    request: Request,
    service_id: int,
    csrf: str = Form(...),
    mode: str = Form(...),
):
    """Edit the runtime payment state from the business editor.

    For v0.3 the business editor may cancel an existing deferral and return the
    service to its normal payment cycle. Creating a new deferral remains in the
    payment workspace where the user supplies the number of months explicitly.
    """
    check_csrf(request, csrf)
    if mode != 'normal':
        raise HTTPException(400, '当前业务页仅支持恢复正常缴费周期')

    period = current_period()
    with db() as conn:
        service = service_or_404(conn, service_id)
        customer_id = int(service['customer_id'])
        before = core._runtime_for(conn, service_id)
        core._save_runtime(conn, service_id, deferred_until_period='')
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), customer_id))

        refreshed_service = service_or_404(conn, service_id)
        runtime = core._runtime_for(conn, service_id)
        state = core._schedule_state(refreshed_service, runtime, period)
        due = core._service_due(refreshed_service, runtime, period)
        template = _template(conn)
        ordered = business_display._ordered_keys(conn, template)
        rows = business_display._customer_rows_payload(conn, customer_id, template, ordered)

    return JSONResponse({
        'ok': True,
        'service_id': service_id,
        'mode': 'normal',
        'changed': bool((before.get('deferred_until_period') or '').strip()),
        'deferred_until_period': '',
        'schedule_state': state,
        'due': bool(due),
        'rows': rows,
    })
