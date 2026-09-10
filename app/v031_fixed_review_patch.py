from __future__ import annotations

from fastapi import HTTPException

from .db import now_iso
from . import v031_payment_workflow_routes as workflow


_base_run_v031 = workflow._run_v031


def _auto_review_run(conn, customer_id: int, period: str | None = None):
    """Keep stage 1 derived from the authoritative row-level confirmation state.

    When every due variable amount is confirmed (fixed amounts are automatic),
    stage 1 completes by itself. If a row later becomes pending, stage 1 and any
    not-yet-paid downstream communication state are invalidated automatically.
    """
    run, stats = _base_run_v031(conn, customer_id, period)
    due_count = int(stats.get('due_count', 0))
    pending = int(stats.get('pending', 0))
    all_confirmed = due_count > 0 and pending == 0
    run = dict(run)
    run['ready'] = all_confirmed

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

    elif not all_confirmed and run['reviewed'] and not run['paid']:
        # A pending amount means any previously prepared customer notice/email is
        # stale. Reconcile the whole pre-payment chain from the row data itself.
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
        run['label'] = '正在核对金额'

    return run, stats


def _fixed_amount_review(conn, customer_id: int, period: str, run, items, stats):
    """Amount-review reset applies only to variable fees; fixed fees stay confirmed."""
    now = now_iso()
    run_id = int(run['id'])

    # Repair rows created by the old whole-reset behavior. Fixed fees are automatic
    # confirmations and must never wait for a manual review click.
    fixed_ids = [
        int(item['row']['id'])
        for item in items
        if item['rule']['mode'] == 'fixed'
    ]
    if fixed_ids:
        placeholders = ','.join('?' for _ in fixed_ids)
        conn.execute(
            f"""UPDATE payment_entries
                SET confirmed=1,
                    source=CASE WHEN source='fixed_review_reset' THEN 'fixed' ELSE source END,
                    updated_at=?
                WHERE period=? AND service_id IN ({placeholders})""",
            (now, period, *fixed_ids),
        )

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

        # For an all-fixed customer there is nothing meaningful to withdraw:
        # fixed rows are always confirmed, so stage 1 remains automatically done.
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
        raise HTTPException(400, f"还有 {stats['pending']} 项变动金额未核对")

    conn.execute(
        'UPDATE customer_payment_runs SET reviewed_at=?,updated_at=? WHERE id=?',
        (now, now, run_id),
    )
    return {
        'review_reconfirmed_service_ids': [],
        'fixed_auto_confirmed': True,
    }


# Public workflow endpoints resolve these module globals at request time.
workflow._run_v031 = _auto_review_run
workflow._paint_review_reset = _fixed_amount_review
