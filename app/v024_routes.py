from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from . import config
from .db import db, now_iso
from .security import require_csrf
from .payment_v02 import (
    current_period,
    customer_is_due,
    service_active_in_period,
    effective_status,
    effective_payment_rule,
    payment_snapshot,
)
from .v023_routes import ATTR_OPTIONS, ATTR_LABELS, VALID_ATTR_KEYS, attr_value, customer_or_404

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')
APP_VERSION = '0.2.4'


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


def enrich_customer_display(item, key1: str, key2: str):
    s = item['row']
    if key1 not in VALID_ATTR_KEYS:
        key1 = 'service_type'
    if key2 not in VALID_ATTR_KEYS or key2 == key1:
        key2 = 'holder_name' if key1 != 'holder_name' else 'service_type'
    item['display_attr_1'] = key1
    item['display_attr_2'] = key2
    item['display_label_1'] = ATTR_LABELS[key1]
    item['display_label_2'] = ATTR_LABELS[key2]
    item['display_value_1'] = attr_value(s, key1)
    item['display_value_2'] = attr_value(s, key2)
    return item


@router.get('/health')
def health_v024():
    return {'ok': True, 'version': APP_VERSION}


@router.get('/', response_class=HTMLResponse)
def dashboard_v024(request: Request, home: str = 'tasks'):
    today_iso = date.today().isoformat()
    active_home_tab = home if home in {'tasks', 'payment', 'promos', 'recent'} else 'tasks'
    with db() as conn:
        tasks = conn.execute(
            '''SELECT t.*, c.name customer_name
               FROM tasks t LEFT JOIN customers c ON c.id=t.customer_id
               WHERE t.done=0 AND (t.remind_date='' OR t.remind_date<=?)
               ORDER BY CASE WHEN t.remind_date='' THEN 1 ELSE 0 END, t.remind_date
               LIMIT 30''',
            (today_iso,),
        ).fetchall()
        customers = conn.execute('SELECT * FROM customers ORDER BY updated_at DESC').fetchall()
        wait_notice, wait_payment, done_payment = [], [], []
        for c in customers:
            if not c['payment_enabled'] or not customer_is_due(conn, c['id']):
                continue
            status = effective_status(c)
            item = {'id': c['id'], 'name': c['name']}
            if status['completed']:
                done_payment.append(item)
            elif status['notified']:
                wait_payment.append(item)
            else:
                wait_notice.append(item)
        promotions = conn.execute(
            '''SELECT p.*, s.number, s.service_type, c.id customer_id, c.name customer_name
               FROM promotions p
               JOIN services s ON s.id=p.service_id
               JOIN customers c ON c.id=s.customer_id
               WHERE s.service_type='成员' AND p.expiry_date<>''
                 AND p.expiry_date<=date(?, '+60 day')
               ORDER BY p.expiry_date LIMIT 40''',
            (today_iso,),
        ).fetchall()
        recent = conn.execute(
            'SELECT id,name,group_code,tax_id FROM customers ORDER BY updated_at DESC LIMIT 12'
        ).fetchall()
    return templates.TemplateResponse(
        'dashboard_v024.html',
        ctx(
            request,
            active_home_tab=active_home_tab,
            tasks=tasks,
            wait_notice=wait_notice,
            wait_payment=wait_payment,
            done_payment=done_payment,
            promotions=promotions,
            recent=recent,
        ),
    )


@router.get('/customers/{customer_id}', response_class=HTMLResponse)
def customer_workspace_v024(request: Request, customer_id: int, tab: str = 'payment'):
    period = current_period()
    active_tab = tab if tab in {'payment', 'services', 'contacts', 'tasks', 'visits'} else 'payment'
    with db() as conn:
        customer = customer_or_404(conn, customer_id)
        display1 = (customer['payment_display_attr_1'] or 'service_type').strip()
        display2 = (customer['payment_display_attr_2'] or 'holder_name').strip()
        if display1 not in VALID_ATTR_KEYS:
            display1 = 'service_type'
        if display2 not in VALID_ATTR_KEYS or display2 == display1:
            display2 = 'holder_name' if display1 != 'holder_name' else 'service_type'

        payment_items, payment_stats = payment_snapshot(conn, customer_id, period)
        payment_items = [enrich_customer_display(dict(item), display1, display2) for item in payment_items]
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
            customer_display_attr_1=display1,
            customer_display_attr_2=display2,
        ),
    )


@router.post('/customers/{customer_id}/display-attributes')
def set_customer_display_attributes_v024(
    request: Request,
    customer_id: int,
    csrf: str = Form(...),
    display_attr_1: str = Form(...),
    display_attr_2: str = Form(...),
):
    check_csrf(request, csrf)
    if display_attr_1 not in VALID_ATTR_KEYS or display_attr_2 not in VALID_ATTR_KEYS:
        raise HTTPException(400, '默认显示属性无效')
    if display_attr_1 == display_attr_2:
        return JSONResponse({'ok': False, 'error': '两个默认属性不能相同'}, status_code=400)
    with db() as conn:
        customer_or_404(conn, customer_id)
        conn.execute(
            '''UPDATE customers
               SET payment_display_attr_1=?,payment_display_attr_2=?,updated_at=?
               WHERE id=?''',
            (display_attr_1, display_attr_2, now_iso(), customer_id),
        )
    return JSONResponse({
        'ok': True,
        'display_attr_1': display_attr_1,
        'display_attr_2': display_attr_2,
        'display_label_1': ATTR_LABELS[display_attr_1],
        'display_label_2': ATTR_LABELS[display_attr_2],
    })
