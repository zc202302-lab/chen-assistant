from __future__ import annotations

from fastapi import HTTPException

from .db import now_iso
from . import v031_payment_workflow_routes as workflow


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


# The public workflow endpoint resolves this module global at request time.
workflow._paint_review_reset = _fixed_amount_review
