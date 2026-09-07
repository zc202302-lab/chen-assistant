from __future__ import annotations

from collections import defaultdict
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from . import config
from .db import db, now_iso
from .security import require_csrf
from .payment_v02 import (
    current_period,
    cycle_months,
    service_is_due,
    service_active_in_period,
    customer_is_due,
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
APP_VERSION = '0.2'


def ctx(request: Request, **extra):
    session = getattr(request.state, 'session', None)
    base = {
        'request': request,
        'csrf': session['csrf_token'] if session else '',
        'app_username': config.APP_USERNAME,
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


@router.get('/health')
def health_v02():
    return {'ok': True, 'version': APP_VERSION}


@router.get('/', response_class=HTMLResponse)
def dashboard_v02(request: Request):
    today = date.today().isoformat()
    with db() as conn:
        tasks = conn.execute(
            '''SELECT t.*, c.name customer_name FROM tasks t LEFT JOIN customers c ON c.id=t.customer_id
               WHERE t.done=0 AND (t.remind_date='' OR t.remind_date<=?)
               ORDER BY CASE WHEN t.remind_date='' THEN 1 ELSE 0 END, t.remind_date LIMIT 20''',
            (today,),
        ).fetchall()
        customers = conn.execute('SELECT * FROM customers ORDER BY updated_at DESC').fetchall()
        wait_notice, wait_payment, done_payment = [], [], []
        for customer in customers:
            if not customer['payment_enabled'] or not customer_is_due(conn, customer['id']):
                continue
            status = effective_status(customer)
            item = {'id': customer['id'], 'name': customer['name']}
            if status['completed']:
                done_payment.append(item)
            elif status['notified']:
                wait_payment.append(item)
            else:
                wait_notice.append(item)
        promo_rows = conn.execute(
            '''SELECT p.*, s.number, s.service_type, c.id customer_id, c.name customer_name
               FROM promotions p JOIN services s ON s.id=p.service_id JOIN customers c ON c.id=s.customer_id
               WHERE s.service_type='成员' AND p.expiry_date<>'' AND p.expiry_date<=date(?, '+60 day')
                 AND (s.inactive_from_period='' OR s.inactive_from_period>?)
               ORDER BY p.expiry_date LIMIT 30''',
            (today, current_period()),
        ).fetchall()
        recent = conn.execute('SELECT id,name,group_code,tax_id FROM customers ORDER BY updated_at DESC LIMIT 6').fetchall()
        product_count = conn.execute(
            "SELECT COUNT(DISTINCT service_type) n FROM services WHERE service_type<>'' AND (inactive_from_period='' OR inactive_from_period>?)",
            (current_period(),),
        ).fetchone()['n']
    return templates.TemplateResponse(
        'dashboard.html',
        ctx(request, tasks=tasks, wait_notice=wait_notice, wait_payment=wait_payment, done_payment=done_payment,
            promotions=promo_rows, recent=recent, product_count=product_count),
    )


@router.get('/customers', response_class=HTMLResponse)
def customers_v02(request: Request, q: str = '', product: str = ''):
    period = current_period()
    with db() as conn:
        params = []
        where = []
        join = ''
        if q.strip():
            like = f'%{q.strip()}%'
            join = 'LEFT JOIN services s ON s.customer_id=c.id LEFT JOIN contacts k ON k.customer_id=c.id'
            where.append('(c.name LIKE ? OR c.group_code LIKE ? OR c.tax_id LIKE ? OR s.number LIKE ? OR s.account LIKE ? OR k.name LIKE ?)')
            params.extend([like] * 6)
        if product.strip():
            join = 'LEFT JOIN services s ON s.customer_id=c.id LEFT JOIN contacts k ON k.customer_id=c.id'
            where.append('s.service_type=?')
            params.append(product.strip())
        sql = '''SELECT DISTINCT c.*,
                 (SELECT COUNT(*) FROM services ss WHERE ss.customer_id=c.id AND (ss.active_from_period='' OR ss.active_from_period<=?) AND (ss.inactive_from_period='' OR ss.inactive_from_period>?)) service_count,
                 (SELECT COALESCE(SUM(monthly_fee),0) FROM services ss WHERE ss.customer_id=c.id AND (ss.active_from_period='' OR ss.active_from_period<=?) AND (ss.inactive_from_period='' OR ss.inactive_from_period>?)) monthly_total
                 FROM customers c ''' + join
        params = [period, period, period, period] + params
        if where:
            sql += ' WHERE ' + ' AND '.join(where)
        sql += ' ORDER BY c.name'
        rows = conn.execute(sql, params).fetchall()
        product_types = conn.execute(
            "SELECT service_type, COUNT(DISTINCT customer_id) customers FROM services WHERE service_type<>'' AND (active_from_period='' OR active_from_period<=?) AND (inactive_from_period='' OR inactive_from_period>?) GROUP BY service_type ORDER BY customers DESC, service_type",
            (period, period),
        ).fetchall()
    return templates.TemplateResponse('customers.html', ctx(request, customers=rows, q=q, product=product, product_types=product_types))


@router.get('/products', response_class=HTMLResponse)
def products_v02(request: Request):
    period = current_period()
    with db() as conn:
        rows = conn.execute(
            '''SELECT service_type,COUNT(*) service_count,COUNT(DISTINCT customer_id) customer_count,COALESCE(SUM(monthly_fee),0) monthly_total
               FROM services
               WHERE service_type<>'' AND (active_from_period='' OR active_from_period<=?) AND (inactive_from_period='' OR inactive_from_period>?)
               GROUP BY service_type ORDER BY customer_count DESC,service_count DESC''',
            (period, period),
        ).fetchall()
    return templates.TemplateResponse('products.html', ctx(request, products=rows))


@router.get('/customers/{customer_id}', response_class=HTMLResponse)
def customer_detail_v02(request: Request, customer_id: int):
    period = current_period()
    with db() as conn:
        customer = conn.execute('SELECT * FROM customers WHERE id=?', (customer_id,)).fetchone()
        if not customer:
            raise HTTPException(404)
        entities = conn.execute('SELECT * FROM customer_entities WHERE customer_id=? ORDER BY id', (customer_id,)).fetchall()
        contacts = conn.execute('SELECT * FROM contacts WHERE customer_id=? ORDER BY id', (customer_id,)).fetchall()
        invoice_groups = conn.execute('SELECT * FROM invoice_groups WHERE customer_id=? ORDER BY id', (customer_id,)).fetchall()
        all_services = conn.execute(
            '''SELECT s.*, g.name invoice_group_name FROM services s
               LEFT JOIN invoice_groups g ON g.id=s.invoice_group_id
               WHERE s.customer_id=? ORDER BY s.service_type,s.source_row,s.id''',
            (customer_id,),
        ).fetchall()
        groups = defaultdict(list)
        inactive_services = []
        for service in all_services:
            if not service_active_in_period(service, period):
                inactive_services.append(service)
                continue
            promos = conn.execute('SELECT * FROM promotions WHERE service_id=? ORDER BY expiry_date', (service['id'],)).fetchall()
            rule = effective_payment_rule(conn, service['id'], period, service)
            groups[service['service_type']].append({'row': service, 'promotions': promos, 'payment_rule': rule})
        tasks = conn.execute('SELECT * FROM tasks WHERE customer_id=? ORDER BY done,remind_date,id DESC', (customer_id,)).fetchall()
        open_tasks = [t for t in tasks if not t['done']]
        visits = conn.execute('SELECT * FROM visits WHERE customer_id=? ORDER BY visit_date DESC,id DESC', (customer_id,)).fetchall()
        promo_count = conn.execute(
            '''SELECT COUNT(*) n FROM promotions p JOIN services s ON s.id=p.service_id
               WHERE s.customer_id=? AND s.service_type='成员' AND p.expiry_date<>'' AND p.expiry_date<=date('now','+60 day')''',
            (customer_id,),
        ).fetchone()['n']
        payment_items, stats = payment_snapshot(conn, customer_id, period)
        status = effective_status(customer)
    return templates.TemplateResponse(
        'customer_detail.html',
        ctx(
            request,
            customer=customer,
            entities=entities,
            contacts=contacts,
            invoice_groups=invoice_groups,
            service_groups=dict(groups),
            inactive_services=inactive_services,
            tasks=tasks,
            open_tasks=open_tasks,
            visits=visits,
            promo_count=promo_count,
            payment_status=status,
            payment_period=period,
            due_services=payment_items,
            current_payment_total=stats['total'],
            pending_payment_count=stats['pending'],
            changed_payment_count=stats['changed'],
            zero_payment_count=stats['zero'],
            payment_txt_ready=stats['txt_ready'],
        ),
    )


@router.post('/customers/{customer_id}/invoice-groups')
def invoice_group_add_v02(request: Request, customer_id: int, csrf: str = Form(...), name: str = Form(...), note: str = Form('')):
    check_csrf(request, csrf)
    name = name.strip()
    if not name:
        raise HTTPException(400, '分组名称不能为空')
    with db() as conn:
        if not conn.execute('SELECT id FROM customers WHERE id=?', (customer_id,)).fetchone():
            raise HTTPException(404)
        conn.execute('INSERT INTO invoice_groups(customer_id,name,note,created_at) VALUES(?,?,?,?)', (customer_id, name, note.strip(), now_iso()))
    return RedirectResponse(f'/customers/{customer_id}#services', 303)


@router.post('/invoice-groups/{group_id}/delete')
def invoice_group_delete_v02(request: Request, group_id: int, csrf: str = Form(...)):
    check_csrf(request, csrf)
    with db() as conn:
        row = conn.execute('SELECT customer_id FROM invoice_groups WHERE id=?', (group_id,)).fetchone()
        if row:
            conn.execute('UPDATE services SET invoice_group_id=NULL WHERE invoice_group_id=?', (group_id,))
            conn.execute('DELETE FROM invoice_groups WHERE id=?', (group_id,))
    return RedirectResponse(f"/customers/{row['customer_id']}#services" if row else '/customers', 303)


@router.post('/customers/{customer_id}/services')
def service_add_v02(
    request: Request,
    customer_id: int,
    csrf: str = Form(...),
    service_type: str = Form(...),
    holder_name: str = Form(''),
    number: str = Form(''),
    account: str = Form(''),
    payment_mode: str = Form('variable'),
    fixed_amount: str = Form('0'),
    payment_cycle: str = Form(''),
    payment_method: str = Form(''),
    invoice_type: str = Form(''),
    invoice_group_id: str = Form(''),
    package_type: str = Form(''),
    last_payment_date: str = Form(''),
):
    check_csrf(request, csrf)
    mode = 'fixed' if payment_mode == 'fixed' else 'variable'
    initial_amount = parse_money(fixed_amount or '0')
    period = current_period()
    with db() as conn:
        if not conn.execute('SELECT id FROM customers WHERE id=?', (customer_id,)).fetchone():
            raise HTTPException(404)
        gid = valid_invoice_group(conn, customer_id, invoice_group_id)
        cur = conn.execute(
            '''INSERT INTO services(customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,payment_cycle,payment_method,invoice_type,package_type,last_payment_date,invoice_group_id,active_from_period)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (customer_id, service_type.strip(), holder_name.strip(), number.strip(), account.strip(), initial_amount, 1 if mode == 'fixed' else 0,
             payment_cycle.strip(), payment_method.strip(), invoice_type.strip(), package_type.strip(), last_payment_date.strip(), gid, period),
        )
        sid = cur.lastrowid
        conn.execute(
            '''INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at)
               VALUES(?,?,?,?,?)''',
            (sid, period, mode, initial_amount if mode == 'fixed' else 0, now_iso()),
        )
        service = conn.execute('SELECT * FROM services WHERE id=?', (sid,)).fetchone()
        if service_is_due(service):
            now = now_iso()
            conn.execute(
                '''INSERT INTO payment_entries(service_id,period,amount,reference_amount,source,confirmed,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)''',
                (sid, period, initial_amount, initial_amount, 'fixed' if mode == 'fixed' else 'manual', 1 if mode == 'fixed' else 0, now, now),
            )
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), customer_id))
    return RedirectResponse(f'/customers/{customer_id}#services', 303)


@router.post('/services/{service_id}/edit')
def service_edit_v02(
    request: Request,
    service_id: int,
    csrf: str = Form(...),
    service_type: str = Form(...),
    holder_name: str = Form(''),
    number: str = Form(''),
    account: str = Form(''),
    payment_mode: str = Form('variable'),
    fixed_amount: str = Form('0'),
    payment_cycle: str = Form(''),
    payment_method: str = Form(''),
    invoice_type: str = Form(''),
    invoice_group_id: str = Form(''),
    package_type: str = Form(''),
    last_payment_date: str = Form(''),
):
    check_csrf(request, csrf)
    mode = 'fixed' if payment_mode == 'fixed' else 'variable'
    fixed = parse_money(fixed_amount or '0')
    period = current_period()
    with db() as conn:
        old = conn.execute('SELECT * FROM services WHERE id=?', (service_id,)).fetchone()
        if not old:
            raise HTTPException(404)
        customer_id = old['customer_id']
        gid = valid_invoice_group(conn, customer_id, invoice_group_id)
        old_rule = effective_payment_rule(conn, service_id, period, old)
        existing_entry = conn.execute('SELECT * FROM payment_entries WHERE service_id=? AND period=?', (service_id, period)).fetchone()
        conn.execute(
            '''UPDATE services SET service_type=?,holder_name=?,number=?,account=?,fixed_fee=?,payment_cycle=?,payment_method=?,invoice_type=?,package_type=?,last_payment_date=?,invoice_group_id=? WHERE id=?''',
            (service_type.strip(), holder_name.strip(), number.strip(), account.strip(), 1 if mode == 'fixed' else 0,
             payment_cycle.strip(), payment_method.strip(), invoice_type.strip(), package_type.strip(), last_payment_date.strip(), gid, service_id),
        )
        conn.execute(
            '''INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(service_id,effective_period) DO UPDATE SET mode=excluded.mode,fixed_amount=excluded.fixed_amount''',
            (service_id, period, mode, fixed if mode == 'fixed' else 0, now_iso()),
        )
        if mode == 'fixed':
            conn.execute('UPDATE services SET monthly_fee=? WHERE id=?', (fixed, service_id))
            if existing_entry:
                reference = existing_entry['reference_amount'] if existing_entry['reference_amount'] is not None else existing_entry['amount']
                conn.execute(
                    '''UPDATE payment_entries SET amount=?,reference_amount=?,source='fixed',confirmed=1,updated_at=? WHERE id=?''',
                    (fixed, reference, now_iso(), existing_entry['id']),
                )
        elif old_rule['mode'] != 'variable' and existing_entry:
            conn.execute(
                '''UPDATE payment_entries SET reference_amount=amount,source='inherited',confirmed=0,updated_at=? WHERE id=?''',
                (now_iso(), existing_entry['id']),
            )
        new_service = conn.execute('SELECT * FROM services WHERE id=?', (service_id,)).fetchone()
        if service_active_in_period(new_service, period) and service_is_due(new_service):
            ensure_payment_entry(conn, new_service, period)
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), customer_id))
    return RedirectResponse(f'/customers/{customer_id}#services', 303)


@router.post('/services/{service_id}/delete')
def service_delete_v02(request: Request, service_id: int, csrf: str = Form(...)):
    check_csrf(request, csrf)
    period = current_period()
    with db() as conn:
        row = conn.execute('SELECT customer_id FROM services WHERE id=?', (service_id,)).fetchone()
        if row:
            conn.execute('UPDATE services SET inactive_from_period=? WHERE id=?', (period, service_id))
            conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), row['customer_id']))
    return RedirectResponse(f"/customers/{row['customer_id']}#services" if row else '/customers', 303)


@router.post('/services/{service_id}/payment-current')
def payment_current_v02(request: Request, service_id: int, csrf: str = Form(...), amount: str = Form(...)):
    check_csrf(request, csrf)
    value = parse_money(amount)
    period = current_period()
    with db() as conn:
        service = conn.execute('SELECT * FROM services WHERE id=?', (service_id,)).fetchone()
        if not service:
            raise HTTPException(404)
        if not service_active_in_period(service, period) or not service_is_due(service):
            raise HTTPException(400, '该业务本周期无需缴费')
        entry, rule = ensure_payment_entry(conn, service, period)
        reference = entry['reference_amount'] if entry['reference_amount'] is not None else entry['amount']
        if rule['mode'] == 'fixed' and abs(value - float(rule['fixed_amount'])) >= 0.005:
            conn.execute(
                '''INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(service_id,effective_period) DO UPDATE SET mode='fixed',fixed_amount=excluded.fixed_amount''',
                (service_id, period, 'fixed', value, now_iso()),
            )
            conn.execute('UPDATE services SET fixed_fee=1,monthly_fee=? WHERE id=?', (value, service_id))
        else:
            conn.execute('UPDATE services SET monthly_fee=? WHERE id=?', (value, service_id))
        conn.execute(
            '''UPDATE payment_entries SET amount=?,reference_amount=?,source=?,confirmed=1,updated_at=? WHERE id=?''',
            (value, reference, 'fixed' if rule['mode'] == 'fixed' else 'manual', now_iso(), entry['id']),
        )
        items, stats = payment_snapshot(conn, service['customer_id'], period)
        saved = next(x for x in items if x['row']['id'] == service_id)
    return JSONResponse({
        'ok': True,
        'amount': value,
        'delta': saved['delta'],
        'pending': stats['pending'],
        'changed': stats['changed'],
        'zero': stats['zero'],
        'total': stats['total'],
        'txt_ready': stats['txt_ready'],
    })


@router.post('/customers/{customer_id}/payment-status')
def payment_status_v02(request: Request, customer_id: int, csrf: str = Form(...), action: str = Form(...)):
    check_csrf(request, csrf)
    period = current_period()
    with db() as conn:
        if action == 'notify':
            conn.execute('UPDATE customers SET notified=1,completed=0,payment_period=?,updated_at=? WHERE id=?', (period, now_iso(), customer_id))
        elif action == 'complete':
            _, stats = payment_snapshot(conn, customer_id, period)
            if stats['pending']:
                raise HTTPException(409, f"还有{stats['pending']}项金额未核对")
            conn.execute('UPDATE customers SET notified=1,completed=1,payment_period=?,updated_at=? WHERE id=?', (period, now_iso(), customer_id))
            rows = conn.execute('SELECT * FROM services WHERE customer_id=?', (customer_id,)).fetchall()
            for service in rows:
                months = cycle_months(service['payment_cycle'])
                if months and months > 1 and service_active_in_period(service, period) and service_is_due(service):
                    conn.execute('UPDATE services SET last_payment_date=? WHERE id=?', (date.today().isoformat(), service['id']))
        elif action == 'reset':
            conn.execute('UPDATE customers SET notified=0,completed=0,payment_period=?,updated_at=? WHERE id=?', (period, now_iso(), customer_id))
        else:
            raise HTTPException(400)
    return RedirectResponse(f'/customers/{customer_id}#payment', 303)


@router.get('/customers/{customer_id}/payment.txt')
def payment_txt_v02(customer_id: int):
    period = current_period()
    with db() as conn:
        customer = conn.execute('SELECT name FROM customers WHERE id=?', (customer_id,)).fetchone()
        if not customer:
            raise HTTPException(404)
        items, stats = payment_snapshot(conn, customer_id, period)
        if stats['pending']:
            raise HTTPException(409, f"还有{stats['pending']}项金额未核对，不能生成正式缴费TXT")
        missing_number = [x for x in items if float(x['payment']['amount'] or 0) > 0 and not (x['row']['number'] or '').strip()]
        if missing_number:
            raise HTTPException(409, '存在非0元缴费业务未填写号码，请先补充号码')
        lines = []
        for item in items:
            amount = float(item['payment']['amount'] or 0)
            number = (item['row']['number'] or '').strip()
            if amount <= 0 or not number:
                continue
            lines.append(f'{number}|{format_fee(amount)}')
    body = '\r\n'.join(lines)
    safe = ''.join(ch for ch in customer['name'] if ch not in '\\/:*?"<>|') or '缴费'
    headers = {'Content-Disposition': f"attachment; filename=\"payment.txt\"; filename*=UTF-8''{quote(safe + '.txt')}"}
    return PlainTextResponse(body, media_type='text/plain; charset=utf-8', headers=headers)
