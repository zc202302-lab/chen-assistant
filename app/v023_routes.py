from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from .templating import Jinja2Templates

from . import config
from .db import db, now_iso
from .security import require_csrf
from .payment_v02 import (
    current_period,
    service_active_in_period,
    service_is_due,
    effective_status,
    effective_payment_rule,
    ensure_payment_entry,
    payment_snapshot,
    parse_money,
    format_fee,
    valid_invoice_group,
)

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')
APP_VERSION = '0.2.3'

ATTR_OPTIONS = [
    ('service_type', '类型'),
    ('holder_name', '姓名/属性'),
    ('invoice_group', '发票组'),
    ('payment_cycle', '缴费周期'),
    ('payment_method', '付款方式'),
    ('invoice_type', '发票类型'),
    ('package_type', '套餐类型'),
    ('last_payment_date', '上次缴费'),
    ('notes', '备注'),
]
ATTR_LABELS = dict(ATTR_OPTIONS)
VALID_ATTR_KEYS = set(ATTR_LABELS)


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


def check_csrf(request: Request, token: str):
    try:
        require_csrf(request.state.session, token)
    except ValueError:
        raise HTTPException(403)


def customer_or_404(conn, customer_id: int):
    row = conn.execute('SELECT * FROM customers WHERE id=?', (customer_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    return row


def service_or_404(conn, service_id: int):
    row = conn.execute('SELECT * FROM services WHERE id=?', (service_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    return row


def service_with_group(conn, service_id: int):
    row = conn.execute(
        '''SELECT s.*, g.name invoice_group_name
           FROM services s LEFT JOIN invoice_groups g ON g.id=s.invoice_group_id
           WHERE s.id=?''',
        (service_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404)
    return row


def attr_value(service, key: str) -> str:
    if key == 'invoice_group':
        return (service['invoice_group_name'] or '未分组') if 'invoice_group_name' in service.keys() else '未分组'
    if key in service.keys():
        value = service[key]
        return str(value).strip() if value not in (None, '') else '—'
    return '—'


def enrich_display(item):
    s = item['row']
    key1 = (s['display_attr_1'] or 'service_type') if 'display_attr_1' in s.keys() else 'service_type'
    key2 = (s['display_attr_2'] or 'holder_name') if 'display_attr_2' in s.keys() else 'holder_name'
    if key1 not in VALID_ATTR_KEYS:
        key1 = 'service_type'
    if key2 not in VALID_ATTR_KEYS:
        key2 = 'holder_name'
    item['display_attr_1'] = key1
    item['display_attr_2'] = key2
    item['display_label_1'] = ATTR_LABELS[key1]
    item['display_label_2'] = ATTR_LABELS[key2]
    item['display_value_1'] = attr_value(s, key1)
    item['display_value_2'] = attr_value(s, key2)
    return item


def payment_json(conn, customer_id: int, period: str, service_id: int | None = None):
    items, stats = payment_snapshot(conn, customer_id, period)
    item = next((x for x in items if service_id and x['row']['id'] == service_id), None)
    payload = {
        'ok': True,
        'required': stats.get('required', 0),
        'pending': stats['pending'],
        'changed': stats['changed'],
        'zero': stats['zero'],
        'total': stats['total'],
        'txt_ready': stats['txt_ready'],
    }
    if item:
        pe = item['payment']
        payload.update({
            'service_id': service_id,
            'amount': float(pe['amount'] or 0),
            'display_amount': format_fee(float(pe['amount'] or 0)),
            'confirmed': bool(pe['confirmed']),
            'mode': item['rule']['mode'],
            'delta': item['delta'],
        })
    return payload


@router.get('/health')
def health_v023():
    return {'ok': True, 'version': APP_VERSION}


@router.get('/customers/{customer_id}', response_class=HTMLResponse)
def customer_workspace_v023(request: Request, customer_id: int, tab: str = 'payment'):
    period = current_period()
    active_tab = tab if tab in {'payment', 'services', 'contacts', 'tasks', 'visits'} else 'payment'
    with db() as conn:
        customer = customer_or_404(conn, customer_id)
        payment_items, payment_stats = payment_snapshot(conn, customer_id, period)
        payment_items = [enrich_display(dict(item)) for item in payment_items]
        invoice_groups = conn.execute(
            'SELECT * FROM invoice_groups WHERE customer_id=? ORDER BY id', (customer_id,)
        ).fetchall()
        rows = conn.execute(
            '''SELECT s.*, g.name invoice_group_name FROM services s
               LEFT JOIN invoice_groups g ON g.id=s.invoice_group_id
               WHERE s.customer_id=?
               ORDER BY CASE WHEN COALESCE(s.sort_order,0)>0 THEN s.sort_order ELSE 100000000+s.id END,
                        s.source_row,s.id''',
            (customer_id,),
        ).fetchall()
        groups = defaultdict(list)
        inactive_services = []
        active_services = 0
        for service in rows:
            if not service_active_in_period(service, period):
                inactive_services.append(service)
                continue
            active_services += 1
            rule = effective_payment_rule(conn, service['id'], period, service)
            groups[service['service_type']].append({'row': service, 'rule': rule})
        contacts = conn.execute(
            'SELECT * FROM contacts WHERE customer_id=? ORDER BY id', (customer_id,)
        ).fetchall()
        tasks = conn.execute(
            'SELECT * FROM tasks WHERE customer_id=? ORDER BY done,remind_date,id DESC', (customer_id,)
        ).fetchall()
        open_tasks = [t for t in tasks if not t['done']]
        visits = conn.execute(
            'SELECT * FROM visits WHERE customer_id=? ORDER BY visit_date DESC,id DESC', (customer_id,)
        ).fetchall()
        status = effective_status(customer)

    return templates.TemplateResponse(
        'customer_workspace_v023.html',
        ctx(
            request,
            customer=customer,
            active_tab=active_tab,
            payment_period=period,
            payment_items=payment_items,
            payment_stats=payment_stats,
            payment_status=status,
            service_groups=dict(groups),
            invoice_groups=invoice_groups,
            inactive_services=inactive_services,
            active_services=active_services,
            contacts=contacts,
            tasks=tasks,
            open_tasks=open_tasks,
            visits=visits,
            attr_options=ATTR_OPTIONS,
        ),
    )


@router.get('/customers/{customer_id}/payment')
@router.get('/customers/{customer_id}/services')
@router.get('/customers/{customer_id}/contacts')
@router.get('/customers/{customer_id}/tasks')
@router.get('/customers/{customer_id}/visits')
def old_customer_subpage_redirect_v023(request: Request, customer_id: int):
    tail = request.url.path.rsplit('/', 1)[-1]
    tab = {'payment': 'payment', 'services': 'services', 'contacts': 'contacts', 'tasks': 'tasks', 'visits': 'visits'}.get(tail, 'payment')
    suffix = '' if tab == 'payment' else f'?tab={tab}'
    return RedirectResponse(f'/customers/{customer_id}{suffix}', 303)


@router.post('/services/{service_id}/payment-current')
def payment_save_v023(request: Request, service_id: int, csrf: str = Form(...), amount: str = Form(...)):
    check_csrf(request, csrf)
    period = current_period()
    value = parse_money(amount)
    with db() as conn:
        service = service_or_404(conn, service_id)
        if not service_active_in_period(service, period) or not service_is_due(service):
            return JSONResponse({'ok': False, 'error': '这项业务本月不在缴费范围内'}, status_code=400)
        entry, rule = ensure_payment_entry(conn, service, period)
        reference = entry['reference_amount']
        if reference is None:
            reference = float(entry['amount'] or 0)
        source = 'fixed' if rule['mode'] == 'fixed' else 'manual'
        conn.execute(
            '''UPDATE payment_entries
               SET amount=?,reference_amount=?,source=?,confirmed=1,updated_at=? WHERE id=?''',
            (value, reference, source, now_iso(), entry['id']),
        )
        conn.execute('UPDATE services SET monthly_fee=? WHERE id=?', (value, service_id))
        if rule['mode'] == 'fixed':
            conn.execute(
                '''INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(service_id,effective_period)
                   DO UPDATE SET mode='fixed',fixed_amount=excluded.fixed_amount''',
                (service_id, period, 'fixed', value, now_iso()),
            )
            conn.execute('UPDATE services SET fixed_fee=1 WHERE id=?', (service_id,))
        return JSONResponse(payment_json(conn, service['customer_id'], period, service_id))


@router.post('/services/{service_id}/toggle-fixed')
def toggle_fixed_v023(request: Request, service_id: int, csrf: str = Form(...)):
    check_csrf(request, csrf)
    period = current_period()
    with db() as conn:
        service = service_or_404(conn, service_id)
        entry, rule = ensure_payment_entry(conn, service, period)
        amount = float(entry['amount'] or 0)
        new_mode = 'variable' if rule['mode'] == 'fixed' else 'fixed'
        fixed_amount = amount if new_mode == 'fixed' else 0
        conn.execute(
            '''INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(service_id,effective_period)
               DO UPDATE SET mode=excluded.mode,fixed_amount=excluded.fixed_amount''',
            (service_id, period, new_mode, fixed_amount, now_iso()),
        )
        conn.execute(
            'UPDATE services SET fixed_fee=?,monthly_fee=? WHERE id=?',
            (1 if new_mode == 'fixed' else 0, amount, service_id),
        )
        conn.execute(
            '''UPDATE payment_entries SET source=?,confirmed=?,updated_at=? WHERE id=?''',
            ('fixed' if new_mode == 'fixed' else 'inherited', 1 if new_mode == 'fixed' else 0, now_iso(), entry['id']),
        )
        payload = payment_json(conn, service['customer_id'], period, service_id)
        payload['mode'] = new_mode
        return JSONResponse(payload)


@router.post('/customers/{customer_id}/services/reorder')
def reorder_services_v023(request: Request, customer_id: int, csrf: str = Form(...), service_ids: str = Form(...)):
    check_csrf(request, csrf)
    try:
        ids = [int(x) for x in service_ids.split(',') if x.strip()]
    except ValueError:
        raise HTTPException(400, '排序数据无效')
    if not ids or len(ids) != len(set(ids)):
        raise HTTPException(400, '排序数据无效')
    with db() as conn:
        customer_or_404(conn, customer_id)
        placeholders = ','.join('?' for _ in ids)
        found = conn.execute(
            f'SELECT id FROM services WHERE customer_id=? AND id IN ({placeholders})',
            (customer_id, *ids),
        ).fetchall()
        if len(found) != len(ids):
            raise HTTPException(400, '排序包含其他客户业务')
        for pos, sid in enumerate(ids, 1):
            conn.execute('UPDATE services SET sort_order=? WHERE id=?', (pos * 10, sid))
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), customer_id))
    return JSONResponse({'ok': True})


@router.post('/services/{service_id}/attributes')
def edit_service_attributes_v023(
    request: Request,
    service_id: int,
    csrf: str = Form(...),
    service_type: str = Form(''),
    holder_name: str = Form(''),
    number: str = Form(''),
    account: str = Form(''),
    payment_cycle: str = Form(''),
    payment_method: str = Form(''),
    invoice_type: str = Form(''),
    invoice_group_id: str = Form(''),
    package_type: str = Form(''),
    last_payment_date: str = Form(''),
    notes: str = Form(''),
    display_attr_1: str = Form('service_type'),
    display_attr_2: str = Form('holder_name'),
):
    check_csrf(request, csrf)
    if display_attr_1 not in VALID_ATTR_KEYS or display_attr_2 not in VALID_ATTR_KEYS:
        raise HTTPException(400, '默认显示属性无效')
    with db() as conn:
        old = service_or_404(conn, service_id)
        gid = valid_invoice_group(conn, old['customer_id'], invoice_group_id)
        conn.execute(
            '''UPDATE services SET
               service_type=?,holder_name=?,number=?,account=?,payment_cycle=?,payment_method=?,
               invoice_type=?,invoice_group_id=?,package_type=?,last_payment_date=?,notes=?,
               display_attr_1=?,display_attr_2=? WHERE id=?''',
            (
                service_type.strip(), holder_name.strip(), number.strip(), account.strip(),
                payment_cycle.strip(), payment_method.strip(), invoice_type.strip(), gid,
                package_type.strip(), last_payment_date.strip(), notes.strip(),
                display_attr_1, display_attr_2, service_id,
            ),
        )
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), old['customer_id']))
        service = service_with_group(conn, service_id)
    return JSONResponse({
        'ok': True,
        'service_id': service_id,
        'service_type': service['service_type'],
        'holder_name': service['holder_name'],
        'number': service['number'],
        'account': service['account'],
        'payment_cycle': service['payment_cycle'],
        'payment_method': service['payment_method'],
        'invoice_type': service['invoice_type'],
        'invoice_group_id': service['invoice_group_id'] or '',
        'invoice_group_name': service['invoice_group_name'] or '',
        'package_type': service['package_type'],
        'last_payment_date': service['last_payment_date'],
        'notes': service['notes'],
        'display_attr_1': display_attr_1,
        'display_attr_2': display_attr_2,
        'display_label_1': ATTR_LABELS[display_attr_1],
        'display_label_2': ATTR_LABELS[display_attr_2],
        'display_value_1': attr_value(service, display_attr_1),
        'display_value_2': attr_value(service, display_attr_2),
    })

