from __future__ import annotations

import base64

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import JSONResponse

from . import config
from .db import db, now_iso
from .payment_v02 import (
    current_period,
    service_active_in_period,
    service_is_due,
    ensure_payment_entry,
    parse_money,
)
from .v023_routes import service_or_404, payment_json
from .v025_routes import customer_or_404
from .v026_routes import check_csrf
from . import v0212_routes as core
from . import v03_routes as v03
from .v03_mail_draft_routes import (
    _get_template,
    _recipient,
    _clean_header,
    _attachment_filename,
    _b64_text,
)

router = APIRouter()


def _has_column(conn, table: str, column: str) -> bool:
    return any(row['name'] == column for row in conn.execute(f'PRAGMA table_info({table})').fetchall())


def ensure_v031(conn):
    """Migrate the existing v0.3 payment run into the four-stage v0.3.1 workflow once."""
    v03._ensure_v03(conn)
    added_initiated = False
    if not _has_column(conn, 'customer_payment_runs', 'initiated_at'):
        conn.execute("ALTER TABLE customer_payment_runs ADD COLUMN initiated_at TEXT DEFAULT ''")
        added_initiated = True
    if not _has_column(conn, 'customer_payment_runs', 'initiate_prepared_at'):
        conn.execute("ALTER TABLE customer_payment_runs ADD COLUMN initiate_prepared_at TEXT DEFAULT ''")

    # Migration backfill must run only when the column is first introduced.
    # Re-running it on every state read would recreate a deliberately withdrawn
    # "发起缴费" state from historical emailed_at and make the workflow appear broken.
    if added_initiated:
        conn.execute(
            """UPDATE customer_payment_runs
               SET initiated_at=CASE
                 WHEN COALESCE(initiated_at,'')<>'' THEN initiated_at
                 WHEN COALESCE(paid_at,'')<>'' THEN paid_at
                 WHEN COALESCE(emailed_at,'')<>'' THEN emailed_at
                 ELSE '' END"""
        )


def _run_v031(conn, customer_id: int, period: str | None = None):
    period = period or current_period()
    customer_or_404(conn, customer_id)
    ensure_v031(conn)
    _, stats = core.payment_snapshot_v0212(conn, customer_id, period)
    # Let the mature v0.3 helper create the row when this is a customer's first run.
    v03._payment_run_v03(conn, customer_id, period, stats)
    row = conn.execute(
        'SELECT * FROM customer_payment_runs WHERE customer_id=? AND period=?',
        (customer_id, period),
    ).fetchone()

    ready = int(stats.get('pending', 0)) == 0
    reviewed = bool((row['reviewed_at'] or '').strip())
    notified = bool((row['notified_at'] or '').strip())
    initiated = bool((row['initiated_at'] or '').strip())
    initiate_prepared = bool((row['initiate_prepared_at'] or '').strip()) and notified and not initiated
    paid = bool((row['paid_at'] or '').strip())

    if paid:
        stage, label = 'paid', '已完成缴费'
    elif initiated:
        stage, label = 'initiated', '已发起缴费，待完成支付'
    elif notified:
        stage, label = 'notified', '已通知客户，待发起缴费'
    elif reviewed:
        stage, label = 'reviewed', '金额已核对，待通知客户'
    elif ready:
        stage, label = 'ready', '金额可核对'
    else:
        stage, label = 'checking', '正在核对金额'

    run = {
        'id': int(row['id']),
        'period': period,
        'stage': stage,
        'label': label,
        'ready': ready,
        'reviewed': reviewed,
        'notified': notified,
        'initiated': initiated,
        'initiate_prepared': initiate_prepared,
        'paid': paid,
        'pending': int(stats.get('pending', 0)),
        'reviewed_at': row['reviewed_at'] or '',
        'notified_at': row['notified_at'] or '',
        'initiated_at': row['initiated_at'] or '',
        'initiate_prepared_at': row['initiate_prepared_at'] or '',
        'paid_at': row['paid_at'] or '',
    }
    return run, stats


def _paint_review_reset(conn, customer_id: int, period: str, run, items, stats):
    """Preserve v0.3's reversible whole-review semantics, including fixed rows."""
    now = now_iso()
    run_id = int(run['id'])

    if run['reviewed']:
        if run['notified'] or run['initiated'] or run['paid']:
            raise HTTPException(409, '请先撤回后续步骤，再取消金额核对')
        reset_ids = []
        for item in items:
            pe = item['payment']
            sid = int(item['row']['id'])
            if item['rule']['mode'] == 'fixed':
                conn.execute(
                    """UPDATE payment_entries
                       SET confirmed=0,source='fixed_review_reset',updated_at=? WHERE id=?""",
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
        return {'review_reset_all': True, 'review_reset_service_ids': reset_ids}

    if stats['pending']:
        raise HTTPException(400, f"还有 {stats['pending']} 项金额未核对")

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
            f"""UPDATE payment_entries
                SET confirmed=1,source='fixed',updated_at=?
                WHERE period=? AND service_id IN ({placeholders})""",
            (now, period, *fixed_reset_ids),
        )
    conn.execute(
        'UPDATE customer_payment_runs SET reviewed_at=?,updated_at=? WHERE id=?',
        (now, now, run_id),
    )
    return {'review_reconfirmed_service_ids': fixed_reset_ids}


def _set_notify(conn, customer_id: int, period: str, run, stats):
    now = now_iso()
    run_id = int(run['id'])
    if run['notified']:
        if run['initiated'] or run['paid']:
            raise HTTPException(409, '请先撤回“发起缴费”，再撤回通知客户')
        conn.execute(
            "UPDATE customer_payment_runs SET notified_at='',initiate_prepared_at='',updated_at=? WHERE id=?",
            (now, run_id),
        )
        conn.execute(
            'UPDATE customers SET payment_period=?,notified=0,completed=0,updated_at=? WHERE id=?',
            (period, now, customer_id),
        )
        return

    if stats['pending']:
        raise HTTPException(400, f"还有 {stats['pending']} 项金额未核对")
    if not run['reviewed']:
        raise HTTPException(400, '请先完成“金额核对”')
    conn.execute(
        'UPDATE customer_payment_runs SET notified_at=?,updated_at=? WHERE id=?',
        (now, now, run_id),
    )
    conn.execute(
        'UPDATE customers SET payment_period=?,notified=1,completed=0,updated_at=? WHERE id=?',
        (period, now, customer_id),
    )


def _set_initiate_prepared(conn, customer_id: int, period: str, run):
    """Persist the external-mail handoff so refresh/restart cannot lose '待确认'."""
    if run['initiated']:
        return
    if not run['notified']:
        raise HTTPException(400, '请先完成“通知客户”')
    now = now_iso()
    conn.execute(
        'UPDATE customer_payment_runs SET initiate_prepared_at=?,updated_at=? WHERE id=?',
        (now, now, int(run['id'])),
    )


def _set_initiated(conn, customer_id: int, period: str, run):
    now = now_iso()
    run_id = int(run['id'])
    if run['initiated']:
        if run['paid']:
            raise HTTPException(409, '请先撤回“完成缴费”，再撤回发起缴费')
        conn.execute(
            "UPDATE customer_payment_runs SET initiated_at='',initiate_prepared_at='',updated_at=? WHERE id=?",
            (now, run_id),
        )
        return
    if not run['notified']:
        raise HTTPException(400, '请先完成“通知客户”')
    conn.execute(
        "UPDATE customer_payment_runs SET initiated_at=?,initiate_prepared_at='',updated_at=? WHERE id=?",
        (now, now, run_id),
    )


def _invalidate_after_amount_change(conn, customer_id: int, period: str, run):
    """Any amount change invalidates all approval/communication stages after entry."""
    if run['paid']:
        raise HTTPException(409, '请先撤回“完成缴费”后再修改金额')
    now = now_iso()
    conn.execute(
        """UPDATE customer_payment_runs
           SET reviewed_at='',notified_at='',initiated_at='',initiate_prepared_at='',updated_at=?
           WHERE id=?""",
        (now, int(run['id'])),
    )
    conn.execute(
        'UPDATE customers SET payment_period=?,notified=0,completed=0,updated_at=? WHERE id=?',
        (period, now, customer_id),
    )


def _legacy_paid_schedule_recovery(conn, customer_id: int, period: str, run) -> None:
    """Safely reopen an old completed run that predates schedule snapshots.

    Exact historical last-payment dates do not exist for these records. Preserve the
    stored historical date instead of inventing one; for multi-month services, move
    next_payment_period back to this run's period so its existing payment entry can
    participate again. Newer runs still use the exact snapshot restore path below.
    """
    rows = conn.execute(
        '''SELECT DISTINCT s.*
           FROM services s
           JOIN payment_entries pe ON pe.service_id=s.id AND pe.period=?
           WHERE s.customer_id=?''',
        (period, customer_id),
    ).fetchall()
    for service in rows:
        months = core.service_interval_months(service)
        if months and months > 1:
            conn.execute(
                'UPDATE services SET next_payment_period=? WHERE id=?',
                (period, int(service['id'])),
            )
        core._save_runtime(conn, int(service['id']), deferred_until_period='')

    now = now_iso()
    conn.execute(
        '''UPDATE customer_payment_runs
           SET paid_at='',emailed_at='',email_to='',email_subject='',updated_at=?
           WHERE id=?''',
        (now, int(run['id'])),
    )
    conn.execute(
        'UPDATE customers SET payment_period=?,notified=1,completed=0,updated_at=? WHERE id=?',
        (period, now, customer_id),
    )


def _response_state(customer_id: int, extra: dict | None = None):
    with db() as conn:
        run, stats = _run_v031(conn, customer_id)
    payload = {'ok': True, 'run': run, 'stats': stats}
    if extra:
        payload.update(extra)
    return JSONResponse(payload)


@router.get('/health')
def health_v031():
    return {'ok': True, 'version': config.APP_VERSION}


@router.get('/customers/{customer_id}/payment-workflow-v031')
def payment_workflow_v031(customer_id: int):
    return _response_state(customer_id)


@router.post('/services/{service_id}/payment-current')
def payment_save_v031(
    request: Request,
    service_id: int,
    csrf: str = Form(...),
    amount: str = Form(...),
):
    """Save an amount and invalidate downstream workflow state in the same transaction."""
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
        had_downstream_state = False
        if amount_changed:
            run, _ = _run_v031(conn, service['customer_id'], period)
            if run['paid']:
                return JSONResponse(
                    {'ok': False, 'error': '本月缴费已经完成，请先撤回“完成缴费”后再修改金额'},
                    status_code=409,
                )
            had_downstream_state = bool(run['reviewed'] or run['notified'] or run['initiated'])

        reference = entry['reference_amount']
        if reference is None:
            reference = previous
        source = 'fixed' if rule['mode'] == 'fixed' else 'manual'
        now = now_iso()
        conn.execute(
            '''UPDATE payment_entries
               SET amount=?,reference_amount=?,source=?,confirmed=1,updated_at=? WHERE id=?''',
            (value, reference, source, now, entry['id']),
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

        if amount_changed and had_downstream_state:
            _invalidate_after_amount_change(conn, service['customer_id'], period, run)

        payload = payment_json(conn, service['customer_id'], period, service_id)
        current_run, _ = _run_v031(conn, service['customer_id'], period)
        payload['workflow_invalidated'] = bool(amount_changed and had_downstream_state)
        payload['workflow_run'] = current_run
        return JSONResponse(payload)


@router.post('/customers/{customer_id}/payment-workflow-v031')
def update_payment_workflow_v031(
    request: Request,
    customer_id: int,
    csrf: str = Form(...),
    action: str = Form(...),
):
    check_csrf(request, csrf)
    period = current_period()

    if action == 'paid':
        # Keep the v0.3 snapshot/restore implementation as the single authority for
        # modern runs. Old runs created before snapshots existed use a deliberately
        # conservative recovery path that preserves their known historical date.
        legacy_recovered = False
        with db() as conn:
            run, _ = _run_v031(conn, customer_id, period)
            if not run['paid'] and not run['initiated']:
                raise HTTPException(400, '请先完成“发起缴费”')
            if run['paid']:
                n = conn.execute(
                    'SELECT COUNT(*) n FROM payment_run_service_snapshots_v03 WHERE run_id=?',
                    (run['id'],),
                ).fetchone()['n']
                if not n:
                    _legacy_paid_schedule_recovery(conn, customer_id, period, run)
                    legacy_recovered = True
        if legacy_recovered:
            return _response_state(customer_id, {'legacy_schedule_recovered': True})

        result = v03.set_payment_run_v03(
            request=request,
            customer_id=customer_id,
            csrf=csrf,
            action='paid',
        )
        if getattr(result, 'status_code', 200) >= 400:
            return result
        return _response_state(customer_id)

    extra = {}
    with db() as conn:
        customer_or_404(conn, customer_id)
        run, stats = _run_v031(conn, customer_id, period)
        items, stats = core.payment_snapshot_v0212(conn, customer_id, period)

        if action == 'review':
            extra = _paint_review_reset(conn, customer_id, period, run, items, stats)
        elif action == 'notify':
            _set_notify(conn, customer_id, period, run, stats)
        elif action == 'prepare_initiate':
            _set_initiate_prepared(conn, customer_id, period, run)
        elif action == 'initiate':
            _set_initiated(conn, customer_id, period, run)
        elif action == 'invalidate':
            _invalidate_after_amount_change(conn, customer_id, period, run)
        else:
            raise HTTPException(400, '状态操作无效')

    return _response_state(customer_id, extra)


@router.get('/customers/{customer_id}/payment-mail-compose-v031')
def payment_mail_compose_v031(customer_id: int):
    """Prepare Foxmail before stage 3 is confirmed; stage 2 is the prerequisite."""
    period = current_period()
    with db() as conn:
        customer, txt_content, _ = v03._payment_txt_content(conn, customer_id, period)
        run, _ = _run_v031(conn, customer_id, period)
        if not run['notified']:
            raise HTTPException(400, '请先完成“通知客户”，再调用Foxmail')
        template = _get_template(conn, customer_id)
        recipient = _recipient(conn)

    subject = _clean_header(template['subject'])
    if not subject:
        raise HTTPException(400, '请先在“缴费模板”中保存邮件主题')

    customer_name = customer['name'] or '客户'
    txt_name = _attachment_filename(template, customer_name, period)
    return JSONResponse({
        'ok': True,
        'recipient_b64': _b64_text(recipient),
        'subject_b64': _b64_text(subject),
        'body_b64': _b64_text(template['body']),
        'attachment_filename_b64': _b64_text(txt_name),
        'attachment_content_base64': base64.b64encode(txt_content.encode('utf-8')).decode('ascii'),
        'period': period,
    })
