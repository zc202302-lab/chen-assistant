"""Current payment review services. Routes and legacy facades call these explicitly."""
from fastapi import HTTPException
from .db import now_iso
from .payment_v02 import current_period, effective_payment_rule, ensure_payment_entry as _base_ensure_payment_entry
from . import v0212_routes as core
from . import v031_payment_workflow_routes as workflow

_base_run_v031 = workflow._run_base_v031
from .v0212_business_display_routes import _payment_snapshot_customer_gate_v143 as _base_snapshot_v0212
MANUAL_CHANGED_SOURCE = 'manual_changed'
MANUAL_UNCHECKED_SOURCE = 'manual_unchecked'
MANUAL_PENDING_SOURCES = {MANUAL_CHANGED_SOURCE, MANUAL_UNCHECKED_SOURCE}


def _ensure_payment_entry_review_aware(conn, service, period: str):
    """Preserve a deliberate row-level pending state, including fixed amounts."""
    existing = conn.execute(
        'SELECT * FROM payment_entries WHERE service_id=? AND period=?',
        (service['id'], period),
    ).fetchone()
    if existing and (existing['source'] or '') in MANUAL_PENDING_SOURCES and not bool(existing['confirmed']):
        rule = effective_payment_rule(conn, service['id'], period, service)
        if rule['mode'] == 'fixed':
            return existing, rule
    return _base_ensure_payment_entry(conn, service, period)


def _review_snapshot(conn, customer_id: int, period: str | None = None):
    """Return the payment snapshot using row-level review semantics.

    Fixed amounts are normally automatic confirmations, but a fixed row may be
    explicitly made pending by either an amount edit or a manual click. Those
    deliberate pending states survive refreshes until the user confirms that row.
    Every untouched row keeps its own confirmation state.
    """
    period = period or current_period()
    items, stats = _base_snapshot_v0212(conn, customer_id, period)

    repair_ids = [
        int(item['payment']['id'])
        for item in items
        if item['rule']['mode'] == 'fixed'
        and not bool(item['payment']['confirmed'])
        and (item['payment']['source'] or '') not in MANUAL_PENDING_SOURCES
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
        or (item['payment']['source'] or '') in MANUAL_PENDING_SOURCES
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
        # Once any row becomes pending, every communication step based on the old
        # total is stale. Only workflow timestamps are reset; untouched payment
        # rows retain their existing confirmation state.
        now = now_iso()
        conn.execute(
            """UPDATE customer_payment_runs
               SET reviewed_at='',notified_at='',initiated_at='',initiate_prepared_at='',updated_at=?
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
        run['initiate_prepared'] = False
        run['reviewed_at'] = ''
        run['notified_at'] = ''
        run['initiated_at'] = ''
        run['initiate_prepared_at'] = ''
        run['stage'] = 'checking'
        run['label'] = '存在未核对金额，待重新确认'

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


def _rollback_completed_payment_exact(conn, customer_id: int, period: str, run):
    """Restore the pre-payment schedule before a row-level change rolls stage 4 back."""
    run_id = int(run['id'])
    snapshots = conn.execute(
        '''SELECT * FROM payment_run_service_snapshots_v03
           WHERE run_id=? ORDER BY service_id''',
        (run_id,),
    ).fetchall()
    if not snapshots:
        raise HTTPException(
            409,
            '这条完成缴费记录来自旧版本，没有保存缴费前周期快照；请不要直接修改金额。',
        )

    for snap in snapshots:
        conn.execute(
            'UPDATE services SET last_payment_date=?,next_payment_period=? WHERE id=?',
            (snap['last_payment_date'], snap['next_payment_period'], snap['service_id']),
        )
        core._save_runtime(
            conn,
            int(snap['service_id']),
            deferred_until_period=snap['deferred_until_period'],
        )

    conn.execute('DELETE FROM payment_run_service_snapshots_v03 WHERE run_id=?', (run_id,))
    now = now_iso()
    conn.execute(
        '''UPDATE customer_payment_runs
           SET reviewed_at='',notified_at='',initiated_at='',initiate_prepared_at='',paid_at='',
               emailed_at='',email_to='',email_subject='',updated_at=?
           WHERE id=?''',
        (now, run_id),
    )
    conn.execute(
        'UPDATE customers SET payment_period=?,notified=0,completed=0,updated_at=? WHERE id=?',
        (period, now, customer_id),
    )


