from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

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
    service_interval_months,
    next_due_after_payment,
    effective_payment_rule,
    payment_snapshot,
    parse_money,
    format_fee,
    valid_invoice_group,
)
from .v023_routes import ATTR_OPTIONS, ATTR_LABELS, VALID_ATTR_KEYS, attr_value

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')
APP_VERSION = '0.2.5'


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
    row = conn.execute(
        '''SELECT s.*, g.name invoice_group_name
           FROM services s LEFT JOIN invoice_groups g ON g.id=s.invoice_group_id
           WHERE s.id=?''',
        (service_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404)
    return row


def promotion_or_404(conn, promotion_id: int):
    row = conn.execute(
        '''SELECT p.*,s.customer_id,s.number,s.account,s.holder_name,s.service_type
           FROM promotions p JOIN services s ON s.id=p.service_id WHERE p.id=?''',
        (promotion_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404)
    return row


def _display_pair(customer):
    key1 = (customer['payment_display_attr_1'] or 'service_type').strip()
    key2 = (customer['payment_display_attr_2'] or 'holder_name').strip()
    if key1 not in VALID_ATTR_KEYS:
        key1 = 'service_type'
    if key2 not in VALID_ATTR_KEYS or key2 == key1:
        key2 = 'holder_name' if key1 != 'holder_name' else 'service_type'
    return key1, key2


def _enrich_display(item, key1: str, key2: str):
    s = item['row']
    item['display_attr_1'] = key1
    item['display_attr_2'] = key2
    item['display_value_1'] = attr_value(s, key1)
    item['display_value_2'] = attr_value(s, key2)
    return item


def _payment_run(conn, customer_id: int, period: str, stats):
    row = conn.execute(
        'SELECT * FROM customer_payment_runs WHERE customer_id=? AND period=?',
        (customer_id, period),
    ).fetchone()
    if not row:
        now = now_iso()
        conn.execute(
            '''INSERT INTO customer_payment_runs(customer_id,period,notified_at,paid_at,created_at,updated_at)
               VALUES(?,?,\'\',\'\',?,?)''',
            (customer_id, period, now, now),
        )
        row = conn.execute(
            'SELECT * FROM customer_payment_runs WHERE customer_id=? AND period=?',
            (customer_id, period),
        ).fetchone()
    ready = int(stats.get('pending', 0)) == 0
    notified = bool((row['notified_at'] or '').strip())
    paid = bool((row['paid_at'] or '').strip())
    if paid:
        stage = 'paid'
        label = '已完成缴费'
    elif notified:
        stage = 'notified'
        label = '已通知客户，待完成缴费'
    elif ready:
        stage = 'ready'
        label = '金额已核对，待通知客户'
    else:
        stage = 'checking'
        label = '正在核对金额'
    return {
        'id': row['id'],
        'stage': stage,
        'label': label,
        'ready': ready,
        'notified': notified,
        'paid': paid,
        'notified_at': row['notified_at'],
        'paid_at': row['paid_at'],
    }


def _promotion_state(row):
    status = (row['status'] or 'active').strip()
    if status != 'active':
        return status, None
    expiry = (row['expiry_date'] or '').strip()
    if not expiry:
        return 'active', None
    try:
        end = date.fromisoformat(expiry[:10])
    except Exception:
        return 'active', None
    days = (end - date.today()).days
    if days < 0:
        return 'expired', days
    if days <= int(row['remind_days'] or 60):
        return 'due_soon', days
    return 'active', days


def _cycle_label(service):
    months = service_interval_months(service)
    if not months:
        return '不参与自动缴费'
    if months == 1:
        return '每月'
    next_period = (service['next_payment_period'] or '').strip()
    return f'每{months}个月' + (f' · 下次 {next_period}' if next_period else '')


@router.get('/health')
def health_v025():
    return {'ok': True, 'version': APP_VERSION}


@router.get('/customers/{customer_id}', response_class=HTMLResponse)
def customer_workspace_v025(request: Request, customer_id: int, tab: str = 'payment'):
    period = current_period()
    tabs = {'payment', 'services', 'promotions', 'contacts', 'tasks', 'visits'}
    active_tab = tab if tab in tabs else 'payment'
    with db() as conn:
        customer = customer_or_404(conn, customer_id)
        display1, display2 = _display_pair(customer)
        payment_items, payment_stats = payment_snapshot(conn, customer_id, period)
        payment_items = [_enrich_display(dict(item), display1, display2) for item in payment_items]
        payment_run = _payment_run(conn, customer_id, period, payment_stats)

        invoice_groups = conn.execute(
            'SELECT * FROM invoice_groups WHERE customer_id=? ORDER BY id', (customer_id,)
        ).fetchall()
        services = conn.execute(
            '''SELECT s.*,g.name invoice_group_name FROM services s
               LEFT JOIN invoice_groups g ON g.id=s.invoice_group_id
               WHERE s.customer_id=?
               ORDER BY CASE WHEN COALESCE(s.sort_order,0)>0 THEN s.sort_order ELSE 100000000+s.id END,s.id''',
            (customer_id,),
        ).fetchall()
        service_groups = defaultdict(list)
        active_services = []
        for s in services:
            if not service_active_in_period(s, period):
                continue
            rule = effective_payment_rule(conn, s['id'], period, s)
            due = service_is_due(s)
            item = {'row': s, 'rule': rule, 'due': due, 'cycle_label': _cycle_label(s)}
            service_groups[s['service_type'] or '未分类'].append(item)
            active_services.append(s)

        promo_rows = conn.execute(
            '''SELECT p.*,s.service_type,s.holder_name,s.number,s.account
               FROM promotions p JOIN services s ON s.id=p.service_id
               WHERE s.customer_id=? ORDER BY CASE WHEN p.status='active' THEN 0 ELSE 1 END,p.expiry_date,p.id DESC''',
            (customer_id,),
        ).fetchall()
        promotions = []
        promo_due = 0
        for p in promo_rows:
            state, days = _promotion_state(p)
            if state in {'due_soon', 'expired'}:
                promo_due += 1
            promotions.append({'row': p, 'state': state, 'days': days})

        contacts = conn.execute('SELECT * FROM contacts WHERE customer_id=? ORDER BY id', (customer_id,)).fetchall()
        tasks = conn.execute('SELECT * FROM tasks WHERE customer_id=? ORDER BY done,remind_date,id DESC', (customer_id,)).fetchall()
        open_tasks = [t for t in tasks if not t['done']]
        visits = conn.execute('SELECT * FROM visits WHERE customer_id=? ORDER BY visit_date DESC,id DESC', (customer_id,)).fetchall()

    return templates.TemplateResponse(
        'customer_workspace_v025.html',
        ctx(
            request,
            customer=customer,
            active_tab=active_tab,
            payment_period=period,
            payment_items=payment_items,
            payment_stats=payment_stats,
            payment_run=payment_run,
            invoice_groups=invoice_groups,
            service_groups=dict(service_groups),
            active_services=active_services,
            promotions=promotions,
            promo_due=promo_due,
            contacts=contacts,
            tasks=tasks,
            open_tasks=open_tasks,
            visits=visits,
            attr_options=ATTR_OPTIONS,
            customer_display_attr_1=display1,
            customer_display_attr_2=display2,
        ),
    )


@router.post('/customers/{customer_id}/payment-run')
def set_payment_run_v025(request: Request, customer_id: int, csrf: str = Form(...), action: str = Form(...)):
    check_csrf(request, csrf)
    period = current_period()
    with db() as conn:
        customer = customer_or_404(conn, customer_id)
        _, stats = payment_snapshot(conn, customer_id, period)
        run = _payment_run(conn, customer_id, period, stats)
        now = now_iso()
        if action == 'notify':
            if stats['pending']:
                return JSONResponse({'ok': False, 'error': f"还有 {stats['pending']} 项金额未核对，暂不能标记已通知"}, status_code=400)
            conn.execute(
                'UPDATE customer_payment_runs SET notified_at=?,updated_at=? WHERE id=?',
                (now, now, run['id']),
            )
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
                rows = conn.execute('SELECT * FROM services WHERE customer_id=?', (customer_id,)).fetchall()
                for s in rows:
                    if not service_active_in_period(s, period) or not service_is_due(s):
                        continue
                    months = service_interval_months(s)
                    next_period = next_due_after_payment(s, period) if months and months > 1 else ''
                    conn.execute(
                        'UPDATE services SET last_payment_date=?,next_payment_period=? WHERE id=?',
                        (today_iso, next_period, s['id']),
                    )
            conn.execute(
                'UPDATE customer_payment_runs SET paid_at=?,updated_at=? WHERE id=?',
                (now, now, run['id']),
            )
            conn.execute(
                'UPDATE customers SET payment_period=?,notified=1,completed=1,updated_at=? WHERE id=?',
                (period, now, customer_id),
            )
        else:
            raise HTTPException(400, '状态操作无效')
        _, stats2 = payment_snapshot(conn, customer_id, period)
        updated = _payment_run(conn, customer_id, period, stats2)
    return JSONResponse({'ok': True, 'run': updated, 'stats': stats2})


@router.post('/customers/{customer_id}/display-attributes')
def display_attributes_v025(
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
            'UPDATE customers SET payment_display_attr_1=?,payment_display_attr_2=?,updated_at=? WHERE id=?',
            (display_attr_1, display_attr_2, now_iso(), customer_id),
        )
        rows = conn.execute(
            '''SELECT s.*,g.name invoice_group_name FROM services s LEFT JOIN invoice_groups g ON g.id=s.invoice_group_id
               WHERE s.customer_id=?''', (customer_id,)
        ).fetchall()
        values = {
            str(s['id']): {
                'v1': attr_value(s, display_attr_1),
                'v2': attr_value(s, display_attr_2),
            } for s in rows
        }
    return JSONResponse({'ok': True, 'values': values})


@router.post('/services/{service_id}/attributes')
def edit_service_attributes_v025(
    request: Request,
    service_id: int,
    csrf: str = Form(...),
    service_type: str = Form(''), holder_name: str = Form(''), number: str = Form(''), account: str = Form(''),
    payment_cycle: str = Form(''), payment_interval_months: int = Form(0), next_payment_period: str = Form(''),
    payment_method: str = Form(''), invoice_type: str = Form(''), invoice_group_id: str = Form(''),
    package_type: str = Form(''), last_payment_date: str = Form(''), notes: str = Form(''),
):
    check_csrf(request, csrf)
    if payment_interval_months < 0 or payment_interval_months > 120:
        raise HTTPException(400, '缴费周期无效')
    if payment_interval_months == 1:
        next_payment_period = ''
    with db() as conn:
        old = service_or_404(conn, service_id)
        gid = valid_invoice_group(conn, old['customer_id'], invoice_group_id)
        conn.execute(
            '''UPDATE services SET service_type=?,holder_name=?,number=?,account=?,payment_cycle=?,
               payment_interval_months=?,next_payment_period=?,payment_method=?,invoice_type=?,invoice_group_id=?,
               package_type=?,last_payment_date=?,notes=? WHERE id=?''',
            (service_type.strip(), holder_name.strip(), number.strip(), account.strip(), payment_cycle.strip(),
             payment_interval_months, next_payment_period.strip(), payment_method.strip(), invoice_type.strip(), gid,
             package_type.strip(), last_payment_date.strip(), notes.strip(), service_id),
        )
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), old['customer_id']))
        service = service_or_404(conn, service_id)
    return JSONResponse({
        'ok': True, 'service_id': service_id, 'service_type': service['service_type'],
        'holder_name': service['holder_name'], 'number': service['number'], 'account': service['account'],
        'payment_cycle': service['payment_cycle'], 'payment_interval_months': service['payment_interval_months'],
        'next_payment_period': service['next_payment_period'], 'payment_method': service['payment_method'],
        'invoice_type': service['invoice_type'], 'invoice_group_id': service['invoice_group_id'] or '',
        'invoice_group_name': service['invoice_group_name'] or '', 'package_type': service['package_type'],
        'last_payment_date': service['last_payment_date'], 'notes': service['notes'],
    })


@router.post('/customers/{customer_id}/services-v025')
def add_service_v025(
    request: Request,
    customer_id: int,
    csrf: str = Form(...),
    service_type: str = Form(...), holder_name: str = Form(''), number: str = Form(''), account: str = Form(''),
    payment_mode: str = Form('variable'), fixed_amount: str = Form('0'), payment_cycle: str = Form('每月'),
    payment_interval_months: int = Form(1), next_payment_period: str = Form(''), payment_method: str = Form(''),
    invoice_type: str = Form(''), package_type: str = Form(''), last_payment_date: str = Form(''),
    invoice_group_id: str = Form(''), notes: str = Form(''),
):
    check_csrf(request, csrf)
    if payment_mode not in {'fixed', 'variable'}:
        raise HTTPException(400, '缴费规则无效')
    amount = parse_money(fixed_amount)
    if payment_interval_months < 0 or payment_interval_months > 120:
        raise HTTPException(400, '缴费周期无效')
    if payment_interval_months == 1:
        next_payment_period = ''
    period = current_period()
    with db() as conn:
        customer_or_404(conn, customer_id)
        gid = valid_invoice_group(conn, customer_id, invoice_group_id)
        max_sort = conn.execute('SELECT COALESCE(MAX(sort_order),0) m FROM services WHERE customer_id=?', (customer_id,)).fetchone()['m']
        cur = conn.execute(
            '''INSERT INTO services(customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
               payment_cycle,payment_interval_months,next_payment_period,payment_method,invoice_type,package_type,
               last_payment_date,invoice_group_id,active_from_period,sort_order,notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (customer_id, service_type.strip(), holder_name.strip(), number.strip(), account.strip(), amount,
             1 if payment_mode == 'fixed' else 0, payment_cycle.strip(), payment_interval_months,
             next_payment_period.strip(), payment_method.strip(), invoice_type.strip(), package_type.strip(),
             last_payment_date.strip(), gid, period, int(max_sort or 0) + 10, notes.strip()),
        )
        sid = cur.lastrowid
        conn.execute(
            '''INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at)
               VALUES(?,?,?,?,?)''',
            (sid, period, payment_mode, amount if payment_mode == 'fixed' else 0, now_iso()),
        )
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), customer_id))
    return RedirectResponse(f'/customers/{customer_id}?tab=services', 303)


@router.post('/services/{service_id}/edit-v025')
def edit_service_form_v025(
    request: Request,
    service_id: int,
    csrf: str = Form(...), service_type: str = Form(''), holder_name: str = Form(''), number: str = Form(''),
    account: str = Form(''), payment_cycle: str = Form(''), payment_interval_months: int = Form(0),
    next_payment_period: str = Form(''), payment_method: str = Form(''), invoice_type: str = Form(''),
    invoice_group_id: str = Form(''), package_type: str = Form(''), last_payment_date: str = Form(''), notes: str = Form(''),
):
    result = edit_service_attributes_v025(
        request, service_id, csrf, service_type, holder_name, number, account, payment_cycle,
        payment_interval_months, next_payment_period, payment_method, invoice_type, invoice_group_id,
        package_type, last_payment_date, notes,
    )
    with db() as conn:
        s = service_or_404(conn, service_id)
        cid = s['customer_id']
    return RedirectResponse(f'/customers/{cid}?tab=services', 303)


@router.post('/customers/{customer_id}/promotions')
def add_promotion_v025(
    request: Request,
    customer_id: int,
    csrf: str = Form(...), service_id: int = Form(...), name: str = Form(...),
    start_date: str = Form(''), expiry_date: str = Form(...), remind_days: int = Form(60), notes: str = Form(''),
):
    check_csrf(request, csrf)
    if remind_days < 0 or remind_days > 3650:
        raise HTTPException(400, '提醒天数无效')
    with db() as conn:
        customer_or_404(conn, customer_id)
        service = service_or_404(conn, service_id)
        if service['customer_id'] != customer_id:
            raise HTTPException(400, '业务不属于该客户')
        conn.execute(
            '''INSERT INTO promotions(service_id,name,start_date,expiry_date,remind_days,status,renewed_at,notes,created_at)
               VALUES(?,?,?,?,?,'active','',?,?)''',
            (service_id, name.strip(), start_date.strip(), expiry_date.strip(), remind_days, notes.strip(), now_iso()),
        )
    return RedirectResponse(f'/customers/{customer_id}?tab=promotions', 303)


@router.post('/promotions/{promotion_id}/renew')
def renew_promotion_v025(
    request: Request,
    promotion_id: int,
    csrf: str = Form(...), new_start_date: str = Form(''), new_expiry_date: str = Form(...), notes: str = Form(''),
):
    check_csrf(request, csrf)
    with db() as conn:
        old = promotion_or_404(conn, promotion_id)
        if old['status'] != 'active':
            raise HTTPException(400, '这条优惠已经结束或续约')
        start = new_start_date.strip() or old['expiry_date']
        cur = conn.execute(
            '''INSERT INTO promotions(service_id,name,start_date,expiry_date,remind_days,status,renewed_at,notes,created_at)
               VALUES(?,?,?,?,?,'active','',?,?)''',
            (old['service_id'], old['name'], start, new_expiry_date.strip(), int(old['remind_days'] or 60),
             notes.strip() or old['notes'], now_iso()),
        )
        new_id = cur.lastrowid
        conn.execute(
            "UPDATE promotions SET status='renewed',renewed_at=?,renewed_to_id=? WHERE id=?",
            (now_iso(), new_id, promotion_id),
        )
        cid = old['customer_id']
    return RedirectResponse(f'/customers/{cid}?tab=promotions', 303)


@router.post('/promotions/{promotion_id}/close')
def close_promotion_v025(request: Request, promotion_id: int, csrf: str = Form(...)):
    check_csrf(request, csrf)
    with db() as conn:
        old = promotion_or_404(conn, promotion_id)
        conn.execute("UPDATE promotions SET status='ended' WHERE id=?", (promotion_id,))
        cid = old['customer_id']
    return RedirectResponse(f'/customers/{cid}?tab=promotions', 303)

