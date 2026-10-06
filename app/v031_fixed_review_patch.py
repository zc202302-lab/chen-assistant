from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from .db import db, now_iso
from .payment_v02 import (
    current_period,
    effective_payment_rule,
    ensure_payment_entry as _base_ensure_payment_entry,
    parse_money,
    service_active_in_period,
    service_is_due,
)
from .v023_routes import service_or_404
from .v026_routes import check_csrf
from . import v0212_routes as core
from . import v031_payment_workflow_routes as workflow


router = APIRouter()
from .payments import (
    MANUAL_CHANGED_SOURCE, MANUAL_UNCHECKED_SOURCE, MANUAL_PENDING_SOURCES,
    _ensure_payment_entry_review_aware, _review_snapshot, _auto_review_run,
    _payment_payload, _fixed_amount_review, _rollback_completed_payment_exact,
)


@router.post('/services/{service_id}/payment-current')
def payment_save_preserve_reviews_v032(
    request: Request,
    service_id: int,
    csrf: str = Form(...),
    amount: str = Form(...),
):
    """Save one amount; only that changed row loses confirmation.

    Any real amount change silently rolls the workflow back to amount review.
    Untouched payment rows retain their confirmation state. If stage 4 was
    completed, its saved schedule snapshot is restored automatically first.
    """
    check_csrf(request, csrf)
    period = current_period()
    value = parse_money(amount)

    with db() as conn:
        service = service_or_404(conn, service_id)
        existing_current = conn.execute(
            'SELECT id FROM payment_entries WHERE service_id=? AND period=?',
            (service_id, period),
        ).fetchone()
        if not service_active_in_period(service, period) or (not service_is_due(service) and not existing_current):
            return JSONResponse({'ok': False, 'error': '这项业务本月不在缴费范围内'}, status_code=400)

        entry, rule = _ensure_payment_entry_review_aware(conn, service, period)
        previous = float(entry['amount'] or 0)
        amount_changed = abs(float(value) - previous) > 0.000001
        run = None
        if amount_changed:
            run, _ = workflow._run_v031(conn, service['customer_id'], period)
            if run['paid']:
                _rollback_completed_payment(conn, int(service['customer_id']), period, run)

        reference = entry['reference_amount']
        if reference is None:
            reference = previous
        now = now_iso()

        if amount_changed:
            confirmed = 0
            source = MANUAL_CHANGED_SOURCE
        else:
            confirmed = 1 if bool(entry['confirmed']) else 0
            source = entry['source'] or ('fixed' if rule['mode'] == 'fixed' else 'manual')

        conn.execute(
            '''UPDATE payment_entries
               SET amount=?,reference_amount=?,source=?,confirmed=?,updated_at=? WHERE id=?''',
            (value, reference, source, confirmed, now, entry['id']),
        )
        conn.execute('UPDATE services SET monthly_fee=? WHERE id=?', (value, service_id))

        if rule['mode'] == 'fixed':
            conn.execute(
                '''INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(service_id,effective_period)
                   DO UPDATE SET mode='fixed',fixed_amount=excluded.fixed_amount''',
                (service_id, period, 'fixed', value, now),
            )
            conn.execute('UPDATE services SET fixed_fee=1 WHERE id=?', (service_id,))

        if amount_changed and run and not run['paid']:
            workflow._invalidate_after_amount_change(conn, service['customer_id'], period, run)

        payload = _payment_payload(conn, service['customer_id'], period, service_id)
        current_run, current_stats = workflow._run_v031(conn, service['customer_id'], period)
        payload.update(current_stats)
        payload['workflow_invalidated'] = amount_changed
        payload['workflow_run'] = current_run
        return JSONResponse(payload)


@router.post('/services/{service_id}/payment-review-toggle')
def payment_review_toggle_preserve_reviews_v032(
    request: Request,
    service_id: int,
    csrf: str = Form(...),
):
    """Toggle exactly one row and derive the whole workflow from row state.

    Both fixed and variable rows can be manually confirmed or unconfirmed. If a
    confirmed row is manually unchecked after stage 1 (or later), the workflow
    rolls back to amount review while every untouched row keeps its own state.
    """
    check_csrf(request, csrf)
    period = current_period()
    with db() as conn:
        service = service_or_404(conn, service_id)
        existing_current = conn.execute(
            'SELECT id FROM payment_entries WHERE service_id=? AND period=?',
            (service_id, period),
        ).fetchone()
        if not service_active_in_period(service, period) or (not service_is_due(service) and not existing_current):
            return JSONResponse({'ok': False, 'error': '该业务本月无需缴费'}, status_code=400)

        pe, rule = _ensure_payment_entry_review_aware(conn, service, period)
        was_confirmed = bool(pe['confirmed'])
        run, _ = workflow._run_v031(conn, int(service['customer_id']), period)
        if was_confirmed and run['paid']:
            _rollback_completed_payment(conn, int(service['customer_id']), period, run)

        new_confirmed = 0 if was_confirmed else 1
        source = pe['source'] or ('fixed' if rule['mode'] == 'fixed' else 'manual')
        if new_confirmed:
            if rule['mode'] == 'fixed':
                source = 'fixed'
        elif rule['mode'] == 'fixed':
            source = MANUAL_UNCHECKED_SOURCE

        conn.execute(
            'UPDATE payment_entries SET confirmed=?,source=?,updated_at=? WHERE id=?',
            (new_confirmed, source, now_iso(), pe['id']),
        )

        payload = _payment_payload(conn, service['customer_id'], period, service_id)
        current_run, current_stats = workflow._run_v031(conn, service['customer_id'], period)
        payload.update(current_stats)
        payload['workflow_invalidated'] = bool(was_confirmed and not new_confirmed)
        payload['workflow_run'] = current_run
        return JSONResponse(payload)


def _rollback_completed_payment(conn, customer_id, period, run):
    from .v143_payment_controls_patch import _rollback_completed_payment_compat
    return _rollback_completed_payment_compat(conn, customer_id, period, run)
