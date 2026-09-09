from __future__ import annotations

from fastapi import APIRouter, Request, Form
from fastapi.responses import JSONResponse

from .db import db, now_iso
from .payment_v02 import current_period
from .v025_routes import customer_or_404
from .v026_routes import check_csrf
from . import v0212_routes as core
from . import v03_routes as v03

router = APIRouter()


# v0.3 supports an explicit "whole review reset". Fixed-fee rows normally auto-confirm,
# but after the user deliberately undoes the whole amount-review step we must preserve
# their unconfirmed state until the whole review is confirmed again. A small source marker
# lets the normal fixed-fee engine distinguish this deliberate reset from an ordinary fixed
# entry that should auto-confirm immediately.
_original_ensure_payment_entry = core.ensure_payment_entry


def _ensure_payment_entry_review_aware(conn, service, period: str):
    existing = conn.execute(
        'SELECT * FROM payment_entries WHERE service_id=? AND period=?',
        (service['id'], period),
    ).fetchone()
    if existing and (existing['source'] or '') == 'fixed_review_reset' and not bool(existing['confirmed']):
        rule = core.effective_payment_rule(conn, service['id'], period, service)
        if rule['mode'] == 'fixed':
            desired = float(rule['fixed_amount'] or 0)
            if abs(float(existing['amount'] or 0) - desired) >= 0.005:
                reference = existing['reference_amount']
                if reference is None:
                    reference = float(existing['amount'] or 0)
                conn.execute(
                    '''UPDATE payment_entries
                       SET amount=?,reference_amount=?,updated_at=? WHERE id=?''',
                    (desired, reference, now_iso(), existing['id']),
                )
                existing = conn.execute('SELECT * FROM payment_entries WHERE id=?', (existing['id'],)).fetchone()
            return existing, rule
    return _original_ensure_payment_entry(conn, service, period)


core.ensure_payment_entry = _ensure_payment_entry_review_aware


def _review_action(request: Request, customer_id: int, csrf: str):
    """Own the review toggle so undo resets every visible row review state.

    Variable rows become manually pending again. Fixed rows also visibly lose their
    review check, but retain a fixed-review-reset marker so they are automatically
    re-confirmed the next time the user confirms the whole amount-review step.
    """
    check_csrf(request, csrf)
    period = current_period()
    now = now_iso()

    with db() as conn:
        customer_or_404(conn, customer_id)
        v03._ensure_v03(conn)
        items, stats = core.payment_snapshot_v0212(conn, customer_id, period)
        run = v03._payment_run_v03(conn, customer_id, period, stats)
        run_id = run['id']

        if run['reviewed']:
            if run['notified'] or run['paid']:
                return JSONResponse(
                    {'ok': False, 'error': '请先撤回后续步骤，再取消金额核对'},
                    status_code=409,
                )

            reset_ids = []
            for item in items:
                pe = item['payment']
                sid = int(item['row']['id'])
                if item['rule']['mode'] == 'fixed':
                    conn.execute(
                        '''UPDATE payment_entries
                           SET confirmed=0,source='fixed_review_reset',updated_at=? WHERE id=?''',
                        (now, pe['id']),
                    )
                else:
                    conn.execute(
                        'UPDATE payment_entries SET confirmed=0,updated_at=? WHERE id=?',
                        (now, pe['id']),
                    )
                reset_ids.append(sid)

            conn.execute(
                "UPDATE customer_payment_runs SET reviewed_at='',updated_at=? WHERE id=?",
                (now, run_id),
            )
            _, stats2 = core.payment_snapshot_v0212(conn, customer_id, period)
            updated = v03._payment_run_v03(conn, customer_id, period, stats2)
            return JSONResponse({
                'ok': True,
                'run': updated,
                'stats': stats2,
                'review_reset_all': True,
                'review_reset_service_ids': reset_ids,
            })

        # Starting/re-confirming the whole review still requires all variable rows to
        # be manually confirmed. Fixed rows that were reset above are re-confirmed here
        # in one operation, preserving the original fixed-fee convenience.
        if stats['pending']:
            return JSONResponse(
                {'ok': False, 'error': f"还有 {stats['pending']} 项金额未核对"},
                status_code=400,
            )

        fixed_reset_ids = [
            int(item['row']['id'])
            for item in items
            if item['rule']['mode'] == 'fixed'
            and (item['payment']['source'] or '') == 'fixed_review_reset'
            and not bool(item['payment']['confirmed'])
        ]
        if fixed_reset_ids:
            placeholders = ','.join('?' for _ in fixed_reset_ids)
            conn.execute(
                f'''UPDATE payment_entries
                    SET confirmed=1,source='fixed',updated_at=?
                    WHERE period=? AND service_id IN ({placeholders})''',
                (now, period, *fixed_reset_ids),
            )

        conn.execute(
            'UPDATE customer_payment_runs SET reviewed_at=?,updated_at=? WHERE id=?',
            (now, now, run_id),
        )
        _, stats2 = core.payment_snapshot_v0212(conn, customer_id, period)
        updated = v03._payment_run_v03(conn, customer_id, period, stats2)
        return JSONResponse({
            'ok': True,
            'run': updated,
            'stats': stats2,
            'review_reconfirmed_service_ids': fixed_reset_ids,
        })


@router.post('/customers/{customer_id}/payment-run')
def set_payment_run_v03_safe(
    request: Request,
    customer_id: int,
    csrf: str = Form(...),
    action: str = Form(...),
):
    """Guard reversible v0.3 workflow operations and own the review reset."""
    if action == 'review':
        return _review_action(request, customer_id, csrf)

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
