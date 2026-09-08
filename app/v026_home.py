from __future__ import annotations

from datetime import date
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from . import config
from .db import db
from .payment_v02 import customer_is_due, effective_status
from .v026_routes import promotion_bucket, date_text

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')


def ctx(request: Request, **extra):
    session = getattr(request.state, 'session', None)
    base = {'request': request, 'csrf': session['csrf_token'] if session else '', 'today': date.today(), 'app_version': '0.2.6'}
    base.update(extra)
    return base


@router.get('/', response_class=HTMLResponse)
def dashboard_v026(request: Request, home: str = 'tasks'):
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
        wait_notice, wait_payment = [], []
        for c in customers:
            if not c['payment_enabled'] or not customer_is_due(conn, c['id']):
                continue
            s = effective_status(c)
            item = {'id': c['id'], 'name': c['name']}
            if s['completed']:
                continue
            if s['notified']:
                wait_payment.append(item)
            else:
                wait_notice.append(item)
        promo_rows = conn.execute(
            '''SELECT p.*,s.number,s.account,s.service_type,c.id customer_id,c.name customer_name
               FROM promotions p JOIN services s ON s.id=p.service_id JOIN customers c ON c.id=s.customer_id
               WHERE COALESCE(p.status,'active')='active' AND COALESCE(p.expiry_date,'')<>''
               ORDER BY p.expiry_date,p.id'''
        ).fetchall()
        promo_expired, promo_soon = [], []
        for p in promo_rows:
            bucket = promotion_bucket(p['expiry_date'], p['status'])
            item = dict(p)
            item['expiry_display'] = date_text(p['expiry_date'])
            if bucket == 'expired':
                promo_expired.append(item)
            elif bucket == 'soon':
                promo_soon.append(item)
        recent = conn.execute('SELECT id,name,group_code,tax_id FROM customers ORDER BY updated_at DESC LIMIT 12').fetchall()
    return templates.TemplateResponse(
        'dashboard_v026.html',
        ctx(request, active_home_tab=active_home_tab, tasks=tasks, wait_notice=wait_notice, wait_payment=wait_payment,
            promo_expired=promo_expired, promo_soon=promo_soon, recent=recent),
    )
