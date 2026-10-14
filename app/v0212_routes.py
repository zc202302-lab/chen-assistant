from __future__ import annotations

from collections import defaultdict
from datetime import date
import json

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from .templating import Jinja2Templates

from . import config
from .db import db, now_iso
from .payment_schedule import explicit_due, explicit_payment_date, readable_date, computed_next_date
from .payment_v02 import (
    current_period,
    add_periods,
    service_active_in_period,
    service_interval_months,
    effective_payment_rule,
    ensure_payment_entry,
    next_due_after_payment,
    format_fee,
)
from .v025_routes import customer_or_404, service_or_404, _payment_run
from .v026_routes import check_csrf, date_text, promotion_bucket
from .v027_routes import _meta_get, _meta_set
from .v028_routes import _template, _custom_map, _service_attrs, _promo_columns
from .v0211_routes import _payment_columns, _payment_widths, _payment_cells

from .promotions import table_payload

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')
APP_VERSION = '0.2.12'
BUSINESS_VISIBLE_KEY = 'business_visible_attrs_v0212'


def ctx(request: Request, **extra):
    session = getattr(request.state, 'session', None)
    base = {
        'request': request,
        'csrf': session['csrf_token'] if session else '',
        'today': date.today(),
        'app_version': APP_VERSION,
    }
    base.update(extra)
    return base


def _ensure_runtime(conn):
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS service_runtime_v0212 (
               service_id INTEGER PRIMARY KEY REFERENCES services(id) ON DELETE CASCADE,
               status TEXT NOT NULL DEFAULT 'active',
               deferred_until_period TEXT NOT NULL DEFAULT '',
               updated_at TEXT NOT NULL DEFAULT ''
           )'''
    )
    conn.execute('CREATE INDEX IF NOT EXISTS idx_service_runtime_v0212_status ON service_runtime_v0212(status,deferred_until_period)')


def _runtime_map(conn, service_ids):
    _ensure_runtime(conn)
    result = {int(sid): {'status': 'active', 'deferred_until_period': ''} for sid in service_ids}
    ids = [int(x) for x in service_ids]
    if not ids:
        return result
    placeholders = ','.join('?' for _ in ids)
    rows = conn.execute(
        f'SELECT service_id,status,deferred_until_period FROM service_runtime_v0212 WHERE service_id IN ({placeholders})',
        ids,
    ).fetchall()
    for row in rows:
        result[int(row['service_id'])] = {
            'status': (row['status'] or 'active').strip() or 'active',
            'deferred_until_period': (row['deferred_until_period'] or '').strip(),
        }
    return result


def _runtime_for(conn, service_id: int):
    return _runtime_map(conn, [service_id])[int(service_id)]


def _save_runtime(conn, service_id: int, *, status: str | None = None, deferred_until_period: str | None = None):
    current = _runtime_for(conn, service_id)
    status = current['status'] if status is None else status
    deferred = current['deferred_until_period'] if deferred_until_period is None else deferred_until_period
    conn.execute(
        '''INSERT INTO service_runtime_v0212(service_id,status,deferred_until_period,updated_at)
           VALUES(?,?,?,?)
           ON CONFLICT(service_id) DO UPDATE SET
             status=excluded.status,
             deferred_until_period=excluded.deferred_until_period,
             updated_at=excluded.updated_at''',
        (service_id, status, deferred, now_iso()),
    )




def _natural_due(service, period: str) -> bool:
    override = explicit_due(service, period)
    if override is not None:
        return override
    months = service_interval_months(service)
    if not months or months < 1:
        return False
    if months == 1:
        return True
    next_period = (service['next_payment_period'] or '').strip() if 'next_payment_period' in service.keys() else ''
    if next_period:
        return period >= next_period
    last = (service['last_payment_date'] or '').strip()
    parsed_last = readable_date(last)
    if parsed_last:
        return period >= add_periods(parsed_last.strftime('%Y-%m'), months)
    return True


def _service_due(service, runtime, period: str) -> bool:
    if runtime.get('status') != 'active':
        return False
    if not service_active_in_period(service, period):
        return False
    deferred = (runtime.get('deferred_until_period') or '').strip()
    if deferred and period < deferred:
        return False
    return _natural_due(service, period)


def _natural_next_period(service, period: str) -> str:
    explicit = explicit_payment_date(service)
    if explicit:
        parsed = readable_date(explicit)
        return parsed.strftime('%Y-%m') if parsed else explicit
    months = service_interval_months(service)
    if not months:
        return ''
    if months == 1:
        return period
    nxt = (service['next_payment_period'] or '').strip()
    if nxt:
        return nxt
    last = (service['last_payment_date'] or '').strip()
    parsed_last = readable_date(last)
    if parsed_last:
        return add_periods(parsed_last.strftime('%Y-%m'), months)
    return period


def _schedule_state(service, runtime, period: str) -> str:
    if runtime.get('status') != 'active':
        return '停用'
    if not service_active_in_period(service, period):
        start = (service['active_from_period'] or '').strip() if 'active_from_period' in service.keys() else ''
        if start and period < start:
            return f"未启用 · {start.replace('-', '/')}起"
        return '停用'
    deferred = (runtime.get('deferred_until_period') or '').strip()
    if deferred and period < deferred:
        return f"延期至 {deferred.replace('-', '/')}"
    explicit = explicit_payment_date(service)
    if explicit and readable_date(explicit) is None:
        return '缴费时间待确认'
    if _natural_due(service, period):
        return '本月应缴'
    nxt = _natural_next_period(service, period)
    return f"下次 {nxt.replace('-', '/')}" if nxt else '暂不缴费'


def _payment_snapshot_base_v0212(conn, customer_id: int, period: str | None = None):
    period = period or current_period()
    rows = conn.execute(
        '''SELECT s.*, g.name invoice_group_name
           FROM services s
           LEFT JOIN invoice_groups g ON g.id=s.invoice_group_id
           WHERE s.customer_id=?
           ORDER BY CASE WHEN COALESCE(s.sort_order,0)>0 THEN s.sort_order ELSE 100000000+s.id END,
                    s.source_row,s.id''',
        (customer_id,),
    ).fetchall()
    runtime = _runtime_map(conn, [s['id'] for s in rows])
    # Keep the completed month's ledger visible for review and rollback, even
    # after renewal has advanced the reminder date. Future months remain gated.
    paid_ids = set()
    run = conn.execute('SELECT id,paid_at FROM customer_payment_runs WHERE customer_id=? AND period=?', (customer_id, period)).fetchone()
    if run and run['paid_at']:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='payment_run_service_snapshots_v03'").fetchone():
            paid_ids = {row['service_id'] for row in conn.execute('SELECT service_id FROM payment_run_service_snapshots_v03 WHERE run_id=?', (run['id'],))}
        if not paid_ids:
            paid_ids = {row['service_id'] for row in conn.execute('SELECT service_id FROM payment_entries WHERE period=? AND service_id IN (SELECT id FROM services WHERE customer_id=?)', (period, customer_id))}
    items = []
    required = pending = changed = zero = 0
    total = 0.0
    due_count = 0
    for service in rows:
        paid_visible = service['id'] in paid_ids and runtime[service['id']]['status'] == 'active' and service_active_in_period(service, period)
        if not paid_visible and not _service_due(service, runtime[service['id']], period):
            continue
        due_count += 1
        pe, rule = ensure_payment_entry(conn, service, period)
        amount = float(pe['amount'] or 0)
        reference = pe['reference_amount']
        confirmed = bool(pe['confirmed'])
        delta = None
        if confirmed and reference is not None:
            diff = round(amount - float(reference), 2)
            if abs(diff) >= 0.005:
                delta = diff
        if rule['mode'] == 'variable':
            required += 1
            if not confirmed:
                pending += 1
        if delta is not None:
            changed += 1
        if confirmed and abs(amount) < 0.005:
            zero += 1
        total += amount
        items.append({
            'row': service,
            'payment': pe,
            'rule': rule,
            'delta': delta,
            'invoice_group_name': service['invoice_group_name'] or '',
        })
    return items, {
        'due_count': due_count,
        'required': required,
        'pending': pending,
        'changed': changed,
        'zero': zero,
        'total': round(total, 2),
        'txt_ready': pending == 0,
    }




@router.get('/health')
def health_v0212():
    return {'ok': True, 'version': APP_VERSION}


@router.get('/customers/{customer_id}', response_class=HTMLResponse)
def customer_workspace_v0212(request: Request, customer_id: int, tab: str = 'payment'):
    period = current_period()
    tabs = {'payment', 'services', 'promotions', 'contacts', 'tasks', 'visits'}
    active_tab = tab if tab in tabs else 'payment'
    with db() as conn:
        _ensure_runtime(conn)
        customer = customer_or_404(conn, customer_id)
        template = _template(conn)
        payment_columns = _payment_columns(conn, customer_id, template)
        payment_widths = _payment_widths(conn, customer_id, payment_columns)
        visible_keys = _visible_keys(conn, template, customer_id)

        invoice_groups = conn.execute('SELECT * FROM invoice_groups WHERE customer_id=? ORDER BY id', (customer_id,)).fetchall()
        services = conn.execute(
            '''SELECT s.*,g.name invoice_group_name FROM services s
               LEFT JOIN invoice_groups g ON g.id=s.invoice_group_id
               WHERE s.customer_id=?
               ORDER BY CASE WHEN COALESCE(s.sort_order,0)>0 THEN s.sort_order ELSE 100000000+s.id END,s.id''',
            (customer_id,),
        ).fetchall()
        services_by_id = {s['id']: s for s in services}
        runtime = _runtime_map(conn, [s['id'] for s in services])
        custom = _custom_map(conn, [s['id'] for s in services])

        payment_items, payment_stats = payment_snapshot_v0212(conn, customer_id, period)
        enriched_payment = []
        for raw in payment_items:
            item = dict(raw)
            service = services_by_id.get(item['row']['id'], item['row'])
            item['row'] = service
            item['payment_cells'] = _payment_cells(
                service,
                custom[service['id']],
                template,
                payment_columns,
                item['payment'],
                item.get('delta'),
            )
            enriched_payment.append(item)
        payment_run = _payment_run(conn, customer_id, period, payment_stats)

        promo_rows = conn.execute(
            '''SELECT p.*,s.service_type,s.holder_name,s.number,s.account,s.customer_id
               FROM promotions p JOIN services s ON s.id=p.service_id
               WHERE s.customer_id=? AND COALESCE(p.status,'active')='active'
               ORDER BY p.expiry_date,p.id''',
            (customer_id,),
        ).fetchall()
        full_promotions = table_payload(conn, customer_id)
        promo_columns = _promo_columns(conn, customer_id, promo_rows)
        promo_attention = sum(len(g['items']) for groups in promo_columns.values() for g in groups)

        business_rows = _business_payload_v0212(
            conn, customer_id, template, services, promo_rows, visible_keys, runtime
        )
        service_types = []
        seen_types = set()
        for item in business_rows:
            typ = (item['row']['service_type'] or '未分类').strip() or '未分类'
            if typ not in seen_types:
                seen_types.add(typ)
                service_types.append(typ)

        contacts = conn.execute('SELECT * FROM contacts WHERE customer_id=? ORDER BY id', (customer_id,)).fetchall()
        tasks = conn.execute('SELECT * FROM tasks WHERE customer_id=? ORDER BY done,remind_date,id DESC', (customer_id,)).fetchall()
        open_tasks = [t for t in tasks if not t['done']]
        visits = conn.execute('SELECT * FROM visits WHERE customer_id=? ORDER BY visit_date DESC,id DESC', (customer_id,)).fetchall()

    payment_options = [
        {'key': item['key'], 'label': item['label'], 'kind': item.get('kind', 'text')}
        for item in template
    ] + [{'key': 'payment_amount', 'label': '缴费金额', 'kind': 'payment_amount'}]
    payment_keys = [item['key'] for item in payment_columns]
    payment_grid_widths = ' '.join(f"{payment_widths[key]}px" for key in payment_keys)

    return templates.TemplateResponse(
        'customer_workspace_v0211.html',
        ctx(
            request,
            customer=customer,
            active_tab=active_tab,
            payment_period=period,
            payment_items=enriched_payment,
            payment_stats=payment_stats,
            payment_run=payment_run,
            payment_columns=payment_columns,
            payment_column_keys=payment_keys,
            payment_column_options=payment_options,
            payment_column_options_json=json.dumps(payment_options, ensure_ascii=False),
            payment_grid_widths=payment_grid_widths,
            invoice_groups=invoice_groups,
            business_rows=business_rows,
            service_types=service_types,
            promo_columns=promo_columns,
            full_promotions=full_promotions,
            promo_attention=promo_attention,
            contacts=contacts,
            tasks=tasks,
            open_tasks=open_tasks,
            visits=visits,
            attr_template=template,
        ),
    )


@router.get('/services/{service_id}/runtime-v0212')
def service_runtime_v0212(service_id: int):
    with db() as conn:
        service = service_or_404(conn, service_id)
        template = _template(conn)
        visible = _visible_keys(conn, template, int(service['customer_id']))
        runtime = _runtime_for(conn, service_id)
        state = _schedule_state(service, runtime, current_period())
    return JSONResponse({
        'ok': True,
        'service_id': service_id,
        'status': runtime['status'],
        'deferred_until_period': runtime['deferred_until_period'],
        'schedule_state': state,
        'business_visible_keys': visible,
    })


@router.post('/services/{service_id}/runtime-v0212')
def save_service_runtime_v0212(
    request: Request,
    service_id: int,
    csrf: str = Form(...),
    status: str = Form(...),
    business_visible_json: str = Form('[]'),
):
    check_csrf(request, csrf)
    if status not in {'active', 'inactive'}:
        raise HTTPException(400, '业务状态无效')
    try:
        requested = json.loads(business_visible_json)
    except Exception:
        raise HTTPException(400, '业务显示属性设置无效')
    if not isinstance(requested, list) or len(requested) > 40:
        raise HTTPException(400, '业务显示属性设置无效')
    with db() as conn:
        service = service_or_404(conn, service_id)
        template = _template(conn)
        valid = {str(x['key']) for x in template}
        visible = []
        seen = set()
        for raw in requested:
            key = str(raw)
            if key not in valid or key in seen:
                continue
            visible.append(key)
            seen.add(key)
        _meta_set(conn, BUSINESS_VISIBLE_KEY, json.dumps(visible, ensure_ascii=False))
        _save_runtime(conn, service_id, status=status)
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), service['customer_id']))
        runtime = _runtime_for(conn, service_id)
        state = _schedule_state(service, runtime, current_period())
    return JSONResponse({'ok': True, 'status': status, 'business_visible_keys': visible, 'schedule_state': state})


@router.post('/services/{service_id}/defer-v0212')
def defer_service_v0212(
    request: Request,
    service_id: int,
    csrf: str = Form(...),
    months: int = Form(...),
):
    check_csrf(request, csrf)
    if months < 1 or months > 120:
        raise HTTPException(400, '延期月数必须是1到120之间的整数')
    period = current_period()
    with db() as conn:
        service = service_or_404(conn, service_id)
        runtime = _runtime_for(conn, service_id)
        if runtime['status'] != 'active' or not service_active_in_period(service, period):
            return JSONResponse({'ok': False, 'error': '停用业务不能延期缴费'}, status_code=400)
        if not _natural_due(service, period):
            return JSONResponse({'ok': False, 'error': '该业务当前尚未到缴费期'}, status_code=400)
        deferred_until = add_periods(period, months)
        _save_runtime(conn, service_id, deferred_until_period=deferred_until)
        conn.execute('DELETE FROM payment_entries WHERE service_id=? AND period=?', (service_id, period))
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), service['customer_id']))
    return JSONResponse({
        'ok': True,
        'service_id': service_id,
        'months': months,
        'deferred_until_period': deferred_until,
        'label': f"延期至 {deferred_until.replace('-', '/')}再次进入缴费",
    })


@router.post('/services/{service_id}/delete-v0212')
def delete_service_v0212(request: Request, service_id: int, csrf: str = Form(...)):
    check_csrf(request, csrf)
    with db() as conn:
        service = service_or_404(conn, service_id)
        customer_id = int(service['customer_id'])
        conn.execute('DELETE FROM services WHERE id=?', (service_id,))
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), customer_id))
    return JSONResponse({'ok': True, 'service_id': service_id, 'customer_id': customer_id})


@router.post('/customers/{customer_id}/payment-run')
def set_payment_run_v0212(request: Request, customer_id: int, csrf: str = Form(...), action: str = Form(...)):
    check_csrf(request, csrf)
    period = current_period()
    with db() as conn:
        customer = customer_or_404(conn, customer_id)
        items, stats = payment_snapshot_v0212(conn, customer_id, period)
        run = _payment_run(conn, customer_id, period, stats)
        now = now_iso()
        if action == 'notify':
            if stats['pending']:
                return JSONResponse({'ok': False, 'error': f"还有 {stats['pending']} 项金额未核对，暂不能标记已通知"}, status_code=400)
            conn.execute('UPDATE customer_payment_runs SET notified_at=?,updated_at=? WHERE id=?', (now, now, run['id']))
            conn.execute(
                'UPDATE customers SET payment_period=?,notified=1,completed=0,updated_at=? WHERE id=?',
                (period, now, customer_id),
            )
        elif action == 'paid':
            if stats['pending']:
                return JSONResponse({'ok': False, 'error': f"还有 {stats['pending']} 项金额未核对，暂不能完成缴费"}, status_code=400)
            if not run['notified']:
                return JSONResponse({'ok': False, 'error': '请先标记“已通知客户”，再完成缴费'}, status_code=400)
            if not run['paid']:
                today_iso = date.today().isoformat()
                for item in items:
                    service = item['row']
                    months = service_interval_months(service)
                    next_period = next_due_after_payment(service, period) if months and months > 1 else ''
                    conn.execute(
                        'UPDATE services SET last_payment_date=?,next_payment_period=?,next_payment_date=? WHERE id=?',
                        (today_iso, next_period, computed_next_date(today_iso, months), service['id']),
                    )
                    _save_runtime(conn, service['id'], deferred_until_period='')
            conn.execute('UPDATE customer_payment_runs SET paid_at=?,updated_at=? WHERE id=?', (now, now, run['id']))
            conn.execute(
                'UPDATE customers SET payment_period=?,notified=1,completed=1,updated_at=? WHERE id=?',
                (period, now, customer_id),
            )
        else:
            raise HTTPException(400, '状态操作无效')
        _, stats2 = payment_snapshot_v0212(conn, customer_id, period)
        updated = _payment_run(conn, customer_id, period, stats2)
    return JSONResponse({'ok': True, 'run': updated, 'stats': stats2})


@router.get('/customers/{customer_id}/payment.txt', response_class=PlainTextResponse)
def payment_txt_v0212(customer_id: int):
    period = current_period()
    with db() as conn:
        customer_or_404(conn, customer_id)
        items, stats = payment_snapshot_v0212(conn, customer_id, period)
        if stats['pending']:
            raise HTTPException(400, f"还有 {stats['pending']} 项金额未核对，暂不能生成缴费TXT")
        lines = []
        for item in items:
            pe = item['payment']
            amount = float(pe['amount'] or 0)
            if abs(amount) < 0.005:
                continue
            number = (item['row']['number'] or '').strip()
            lines.append(f"{number}|{format_fee(amount)}")
    return PlainTextResponse('\n'.join(lines), media_type='text/plain; charset=utf-8')



# Stable compatibility entry points; providers are resolved at call time.
def ensure_payment_entry(conn, service, period):
    from .v031_fixed_review_patch import _ensure_payment_entry_review_aware
    return _ensure_payment_entry_review_aware(conn, service, period)


def payment_snapshot_v0212(conn, customer_id, period=None):
    from .v031_fixed_review_patch import _review_snapshot
    return _review_snapshot(conn, customer_id, period)


def _visible_keys(conn, template, customer_id=None):
    from .v0212_business_display_routes import _ordered_keys
    return _ordered_keys(conn, template, customer_id)


def _business_payload_v0212(conn, customer_id, template, services, promo_rows, visible_keys, runtime):
    from .v0212_business_display_routes import _business_payload_customer_gate_v143
    return _business_payload_customer_gate_v143(conn, customer_id, template, services, promo_rows, visible_keys, runtime)


def _payment_run(conn, customer_id, period, stats):
    from .v03_routes import _payment_run_v03
    return _payment_run_v03(conn, customer_id, period, stats)
