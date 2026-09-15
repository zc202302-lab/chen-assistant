from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse

from .db import db, now_iso
from .payment_v02 import current_period, service_active_in_period, service_interval_months, service_is_due
from .v023_routes import service_or_404
from .v026_routes import check_csrf
from . import v0212_routes as core
from . import v031_fixed_review_patch as review_patch
from . import v031_payment_workflow_routes as workflow


router = APIRouter()
_original_data_change_rollback = review_patch._rollback_completed_payment


def _snapshot_count(conn, run_id: int) -> int:
    row = conn.execute(
        'SELECT COUNT(*) n FROM payment_run_service_snapshots_v03 WHERE run_id=?',
        (int(run_id),),
    ).fetchone()
    return int(row['n'] or 0) if row else 0


def _recover_legacy_due_schedule(conn, customer_id: int, period: str) -> None:
    """Make an old completed-period row payable again when no pre-payment snapshot exists.

    Very old completed runs predate the schedule snapshot table. Their exact former
    last_payment_date cannot be reconstructed. We therefore preserve that historical
    date, but for multi-month services set next_payment_period back to the current
    period so the existing current-period payment entry is visible again. This is the
    smallest reversible recovery that restores manual controls without inventing a
    fake historical payment date.
    """
    rows = conn.execute(
        '''SELECT DISTINCT s.*
           FROM services s
           JOIN payment_entries pe ON pe.service_id=s.id AND pe.period=?
           WHERE s.customer_id=?''',
        (period, int(customer_id)),
    ).fetchall()
    for service in rows:
        months = service_interval_months(service)
        if months and months > 1:
            conn.execute(
                'UPDATE services SET next_payment_period=? WHERE id=?',
                (period, int(service['id'])),
            )
        core._save_runtime(conn, int(service['id']), deferred_until_period='')


def _rollback_completed_payment_compat(conn, customer_id: int, period: str, run):
    """Data-change rollback with a safe compatibility path for pre-snapshot runs."""
    if _snapshot_count(conn, int(run['id'])):
        return _original_data_change_rollback(conn, customer_id, period, run)

    _recover_legacy_due_schedule(conn, customer_id, period)
    now = now_iso()
    conn.execute(
        '''UPDATE customer_payment_runs
           SET reviewed_at='',notified_at='',initiated_at='',paid_at='',
               emailed_at='',email_to='',email_subject='',updated_at=?
           WHERE id=?''',
        (now, int(run['id'])),
    )
    conn.execute(
        'UPDATE customers SET payment_period=?,notified=0,completed=0,updated_at=? WHERE id=?',
        (period, now, int(customer_id)),
    )


# Row-review and amount-edit endpoints resolve this module global at request time.
# Replacing it here also fixes old completed records without weakening the normal
# exact snapshot/restore path for every newer run. The four-stage workflow route
# itself remains owned by app.v031_payment_workflow_routes for compatibility.
review_patch._rollback_completed_payment = _rollback_completed_payment_compat


@router.post('/services/{service_id}/toggle-fixed')
def toggle_fixed_v143_compat(
    request: Request,
    service_id: int,
    csrf: str = Form(...),
):
    """Toggle fixed/variable from the payment row in every workflow stage.

    The current amount is preserved. Fixed mode is immediately confirmed; variable
    mode becomes pending and the workflow automatically falls back to amount review.
    Any completed payment is rolled back first using the exact saved snapshot when
    available, or the legacy compatibility recovery above when it predates snapshots.
    """
    check_csrf(request, csrf)
    period = current_period()

    with db() as conn:
        service = service_or_404(conn, service_id)
        customer_id = int(service['customer_id'])
        existing_current = conn.execute(
            'SELECT id FROM payment_entries WHERE service_id=? AND period=?',
            (service_id, period),
        ).fetchone()
        if not service_active_in_period(service, period) or (not service_is_due(service) and not existing_current):
            return JSONResponse({'ok': False, 'error': '这项业务本月不在缴费范围内'}, status_code=400)

        entry, rule = review_patch._ensure_payment_entry_review_aware(conn, service, period)
        run, _ = workflow._run_v031(conn, customer_id, period)
        if run['paid']:
            review_patch._rollback_completed_payment(conn, customer_id, period, run)

        amount = float(entry['amount'] or 0)
        new_mode = 'variable' if rule['mode'] == 'fixed' else 'fixed'
        fixed_amount = amount if new_mode == 'fixed' else 0
        confirmed = 1 if new_mode == 'fixed' else 0
        source = 'fixed' if new_mode == 'fixed' else 'inherited'
        now = now_iso()

        conn.execute(
            '''INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(service_id,effective_period)
               DO UPDATE SET mode=excluded.mode,fixed_amount=excluded.fixed_amount''',
            (service_id, period, new_mode, fixed_amount, now),
        )
        conn.execute(
            'UPDATE services SET fixed_fee=?,monthly_fee=? WHERE id=?',
            (1 if new_mode == 'fixed' else 0, amount, service_id),
        )
        conn.execute(
            'UPDATE payment_entries SET source=?,confirmed=?,updated_at=? WHERE id=?',
            (source, confirmed, now, int(entry['id'])),
        )
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now, customer_id))

        payload = review_patch._payment_payload(conn, customer_id, period, service_id)
        current_run, current_stats = workflow._run_v031(conn, customer_id, period)
        payload.update(current_stats)
        payload['mode'] = new_mode
        payload['workflow_run'] = current_run
        payload['workflow_invalidated'] = new_mode == 'variable'
        return JSONResponse(payload)
