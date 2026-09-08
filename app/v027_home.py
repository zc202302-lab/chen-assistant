from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from . import config
from .db import db
from .payment_v02 import customer_is_due, effective_status
from .v026_routes import promotion_bucket

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')


def ctx(request: Request, **extra):
    session = getattr(request.state, 'session', None)
    base = {'request': request, 'csrf': session['csrf_token'] if session else '', 'today': date.today(), 'app_version': '0.2.7'}
    base.update(extra)
    return base


@router.get('/', response_class=HTMLResponse)
def dashboard_v027(request: Request, home: str = 'tasks'):
    today_iso = date.today().isoformat()
    active_home_tab = home if home in {'tasks', 'payment', 'promos', 'recent'} else 'tasks'
    with db() as conn:
        tasks = conn.execute(
            '''SELECT t.*,c.name customer_name FROM tasks t LEFT JOIN customers c ON c.id=t.customer_id
               WHERE t.done=0 AND (t.remind_date='' OR t.remind_date<=?)
               ORDER BY CASE WHEN t.remind_date='' THEN 1 ELSE 0 END,t.remind_date LIMIT 30''',
            (today_iso,),
        ).fetchall()
        customers = conn.execute('SELECT * FROM customers ORDER BY updated_at DESC').fetchall()
        wait_notice, wait_payment, done_payment = [], [], []
        for c in customers:
            if not c['payment_enabled'] or not customer_is_due(conn, c['id']):
                continue
            s = effective_status(c)
            item = {'id': c['id'], 'name': c['name']}
            if s['completed']:
                done_payment.append(item)
            elif s['notified']:
                wait_payment.append(item)
            else:
                wait_notice.append(item)

        promo_rows = conn.execute(
            '''SELECT p.id,p.expiry_date,p.status,s.customer_id,c.name customer_name
               FROM promotions p JOIN services s ON s.id=p.service_id JOIN customers c ON c.id=s.customer_id
               WHERE COALESCE(p.status,'active')='active' AND COALESCE(p.expiry_date,'')<>''
               ORDER BY c.name,p.expiry_date,p.id'''
        ).fetchall()
        promo_map = {}
        for p in promo_rows:
            bucket = promotion_bucket(p['expiry_date'], p['status'])
            if bucket not in {'expired', 'soon'}:
                continue
            item = promo_map.setdefault(p['customer_id'], {
                'customer_id': p['customer_id'],
                'customer_name': p['customer_name'],
                'expired': 0,
                'soon': 0,
                'total': 0,
            })
            item[bucket] += 1
            item['total'] += 1
        promo_customers = sorted(promo_map.values(), key=lambda x: (0 if x['expired'] else 1, -x['total'], x['customer_name']))

        recent = conn.execute('SELECT id,name,group_code,tax_id FROM customers ORDER BY updated_at DESC LIMIT 12').fetchall()

    return templates.TemplateResponse(
        'dashboard_v027.html',
        ctx(
            request,
            active_home_tab=active_home_tab,
            tasks=tasks,
            wait_notice=wait_notice,
            wait_payment=wait_payment,
            done_payment=done_payment,
            promo_customers=promo_customers,
            recent=recent,
        ),
    )
