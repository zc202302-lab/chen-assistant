from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from .db import db, now_iso
from .payment_v02 import (
    current_period,
    ensure_payment_entry,
    parse_money,
    service_active_in_period,
    service_is_due,
)
from .v023_routes import service_or_404
from .v026_routes import check_csrf
from . import v0212_routes as core
from . import v031_payment_workflow_routes as workflow


router = APIRouter()
_base_run_v031 = workflow._run_v031
_base_snapshot_v0212 = core.payment_snapshot_v0212
MANUAL_CHANGED_SOURCE = 'manual_changed'


def _review_snapshot(conn, customer_id: int, period: str | None = None):
    """Return the payment snapshot using row-level review semantics.

    Fixed amounts are normally automatic confirmations. A fixed amount that the
    user has just edited is the one exception: that changed row remains pending
    until the user confirms it once. All untouched rows keep their own state.
    """
    period = period or current_period()
    items, stats = _base_snapshot_v0212(conn, customer_id, period)

    repair_ids = [
        int(item['payment']['id'])
        for item in items
        if item['rule']['mode'] == 'fixed'
        and not bool(item['payment']['confirmed'])
        and (item['payment']['source'] or '') != MANUAL_CHANGED_SOURCE
    ]
    if repair_ids:
        placeholders = ','.join('?' for _ in repair_ids)
        conn.execute(
            f"""UPDATE payment_entries
                SET confirmed=1,
                    source=CASE WHEN source='fixed_review_reset' THEN 'fixed' ELSE source END,
                    updated_at=?
                WHERE id IN ({placeholders})""",
            (now_iso(), *repair_ids),
        )
        items, stats = _base_snapshot_v0212(conn, customer_id, period)

    pending = sum(1 for item in items if not bool(item['payment']['confirmed']))
    required = sum(
        1 for item in items
        if item['rule']['mode'] == 'variable'
        or (item['payment']['source'] or '') == MANUAL_CHANGED_SOURCE
    )
    stats = dict(stats)
    stats['required'] = required
    stats['pending'] = pending
    stats['txt_ready'] = pending == 0
    return items, stats


def _auto_review_run(conn, customer_id: int, period: str | None = None):
    """Derive stage 1 from the authoritative row-level confirmation state."""
    period = period or current_period()
    run, _ = _base_run_v031(conn, customer_id, period)
    _, stats = _review_snapshot(conn, customer_id, period)

    due_count = int(stats.get('due_count', 0))
    pending = int(stats.get('pending', 0))
    all_confirmed = due_count > 0 and pending == 0
    run = dict(run)
    run['ready'] = all_confirmed
    run['pending'] = pending

    if all_confirmed and not run['reviewed']:
        now = now_iso()
        conn.execute(
            """UPDATE customer_payment_runs
               SET reviewed_at=CASE WHEN COALESCE(reviewed_at,'')='' THEN ? ELSE reviewed_at END,
                   updated_at=?
               WHERE id=?""",
            (now, now, int(run['id'])),
        )
        row = conn.execute(
            'SELECT reviewed_at FROM customer_payment_runs WHERE id=?',
            (int(run['id']),),
        ).fetchone()
        run['reviewed'] = True
        run['reviewed_at'] = (row['reviewed_at'] if row else now) or now
        if not run['notified'] and not run['initiated'] and not run['paid']:
            run['stage'] = 'reviewed'
            run['label'] = '金额已全部核对，待通知客户'

    elif pending > 0 and not run['paid'] and (run['reviewed'] or run['notified'] or run['initiated']):
        # Once any amount becomes pending, every communication step based on the
        # old total is stale. Payment-entry confirmations are deliberately not
        # reset here; only the row whose amount changed is made pending by save.
        now = now_iso()
        conn.execute(
            """UPDATE customer_payment_runs
               SET reviewed_at='',notified_at='',initiated_at='',updated_at=?
               WHERE id=?""",
            (now, int(run['id'])),
        )
        conn.execute(
            'UPDATE customers SET notified=0,completed=0,updated_at=? WHERE id=?',
            (now, customer_id),
        )
        run['reviewed'] = False
        run['notified'] = False
        run['initiated'] = False
        run['reviewed_at'] = ''
        run['notified_at'] = ''
        run['initiated_at'] = ''
        run['stage'] = 'checking'
        run['label'] = '金额有修改，待重新确认'

    return run, stats


def _payment_payload(conn, customer_id: int, period: str, service_id: int):
    items, stats = _review_snapshot(conn, customer_id, period)
    item = next((x for x in items if int(x['row']['id']) == int(service_id)), None)
    if not item:
        raise HTTPException(400, '该业务本月不在缴费清单中')
    pe = item['payment']
    amount = float(pe['amount'] or 0)
    display_amount = str(int(amount)) if abs(amount - round(amount)) < 0.000001 else f'{amount:.2f}'.rstrip('0').rstrip('.')
    return {
        'ok': True,
        'service_id': int(service_id),
        'amount': amount,
        'display_amount': display_amount,
        'confirmed': bool(pe['confirmed']),
        'mode': item['rule']['mode'],
        'delta': item['delta'],
        **stats,
    }


def _fixed_amount_review(conn, customer_id: int, period: str, run, items, stats):
    """Whole-review withdrawal affects variable rows only; untouched fixed rows stay automatic."""
    now = now_iso()
    run_id = int(run['id'])
    items, stats = _review_snapshot(conn, customer_id, period)

    if run['reviewed']:
        if run['notified'] or run['initiated'] or run['paid']:
            raise HTTPException(409, '请先撤回后续步骤，再取消金额核对')

        variable_ids = []
        for item in items:
            if item['rule']['mode'] != 'variable':
                continue
            pe = item['payment']
            sid = int(item['row']['id'])
            conn.execute(
                'UPDATE payment_entries SET confirmed=0,updated_at=? WHERE id=?',
                (now, pe['id']),
            )
            variable_ids.append(sid)

        # For an all-fixed customer there is nothing meaningful to withdraw.
        if not variable_ids:
            return {
                'review_reset_all': False,
                'review_reset_service_ids': [],
                'fixed_auto_confirmed': True,
                'review_auto_completed': True,
            }

        conn.execute(
            "UPDATE customer_payment_runs SET reviewed_at='',updated_at=? WHERE id=?",
            (now, run_id),
        )
        return {
            'review_reset_all': True,
            'review_reset_service_ids': variable_ids,
            'fixed_auto_confirmed': True,
        }

    if stats['pending']:
        raise HTTPException(400, f"还有 {stats['pending']} 项金额未核对")

    conn.execute(
        'UPDATE customer_payment_runs SET reviewed_at=?,updated_at=? WHERE id=?',
        (now, now, run_id),
    )
    return {
        'review_reconfirmed_service_ids': [],
        'fixed_auto_confirmed': True,
    }


@router.post('/services/{service_id}/payment-current')
def payment_save_preserve_reviews_v032(
    request: Request,
    service_id: int,
    csrf: str = Form(...),
    amount: str = Form(...),
):
    """Save one amount; only that changed row loses confirmation.

    Any real amount change silently invalidates stages 1-3. Untouched payment
    rows retain their confirmation state. Completed payments remain locked for
    safety and must still be explicitly withdrawn before editing.
    """
    check_csrf(request, csrf)
    period = current_period()
    value = parse_money(amount)

    with db() as conn:
        service = service_or_404(conn, service_id)
        if not service_active_in_period(service, period) or not service_is_due(service):
            return JSONResponse({'ok': False, 'error': '这项业务本月不在缴费范围内'}, status_code=400)

        entry, rule = ensure_payment_entry(conn, service, period)
        previous = float(entry['amount'] or 0)
        amount_changed = abs(float(value) - previous) > 0.000001
        run = None
        if amount_changed:
            run, _ = workflow._run_v031(conn, service['customer_id'], period)
            if run['paid']:
                return JSONResponse(
                    {'ok': False, 'error': '本月缴费已经完成，请先撤回“完成缴费”后再修改金额'},
                    status_code=409,
                )

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

        if amount_changed:
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
    """Confirm the changed row without disturbing any other row."""
    check_csrf(request, csrf)
    period = current_period()
    with db() as conn:
        service = service_or_404(conn, service_id)
        if not service_active_in_period(service, period) or not service_is_due(service):
            return JSONResponse({'ok': False, 'error': '该业务本月无需缴费'}, status_code=400)

        pe, rule = ensure_payment_entry(conn, service, period)
        if rule['mode'] == 'fixed':
            if bool(pe['confirmed']):
                new_confirmed = 1
            else:
                # A manually changed fixed amount needs exactly one explicit
                # reconfirmation. Legacy fixed rows are repaired the same way.
                new_confirmed = 1
                conn.execute(
                    "UPDATE payment_entries SET confirmed=1,source='fixed',updated_at=? WHERE id=?",
                    (now_iso(), pe['id']),
                )
        else:
            new_confirmed = 0 if bool(pe['confirmed']) else 1
            conn.execute(
                'UPDATE payment_entries SET confirmed=?,updated_at=? WHERE id=?',
                (new_confirmed, now_iso(), pe['id']),
            )

        payload = _payment_payload(conn, service['customer_id'], period, service_id)
        current_run, current_stats = workflow._run_v031(conn, service['customer_id'], period)
        payload.update(current_stats)
        payload['workflow_run'] = current_run
        return JSONResponse(payload)


# Public payment rendering and workflow state use the same row-level truth.
core.payment_snapshot_v0212 = _review_snapshot
workflow._run_v031 = _auto_review_run
workflow._paint_review_reset = _fixed_amount_review
