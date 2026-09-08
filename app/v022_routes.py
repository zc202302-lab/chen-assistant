from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from . import config
from .db import db
from .payment_v02 import (
    current_period,
    service_active_in_period,
    effective_status,
    effective_payment_rule,
    payment_snapshot,
)

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')
APP_VERSION = '0.2.2'


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


def customer_or_404(conn, customer_id: int):
    row = conn.execute('SELECT * FROM customers WHERE id=?', (customer_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    return row


@router.get('/health')
def health_v022():
    return {'ok': True, 'version': APP_VERSION}


@router.get('/customers/{customer_id}', response_class=HTMLResponse)
def customer_workspace_v022(request: Request, customer_id: int, tab: str = 'payment'):
    period = current_period()
    active_tab = tab if tab in {'payment', 'services', 'contacts', 'tasks', 'visits'} else 'payment'
    with db() as conn:
        customer = customer_or_404(conn, customer_id)
        payment_items, payment_stats = payment_snapshot(conn, customer_id, period)
        invoice_groups = conn.execute(
            'SELECT * FROM invoice_groups WHERE customer_id=? ORDER BY id', (customer_id,)
        ).fetchall()
        rows = conn.execute(
            '''SELECT s.*, g.name invoice_group_name FROM services s
               LEFT JOIN invoice_groups g ON g.id=s.invoice_group_id
               WHERE s.customer_id=? ORDER BY s.service_type,s.source_row,s.id''',
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
        'customer_workspace_v022.html',
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
        ),
    )
