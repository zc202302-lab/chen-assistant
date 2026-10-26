from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from urllib.parse import quote

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, JSONResponse
from .templating import Jinja2Templates

from . import config
from .db import db, now_iso
from .security import require_csrf
from .payment_v02 import (
    current_period,
    cycle_months,
    service_is_due,
    service_active_in_period,
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
APP_VERSION = '0.2.1'


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


def _service_or_404(conn, service_id: int):
    row = conn.execute('SELECT * FROM services WHERE id=?', (service_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    return row


def _payment_json(conn, customer_id: int, period: str, service_id: int | None = None):
    items, stats = payment_snapshot(conn, customer_id, period)
    item = next((x for x in items if service_id and x['row']['id'] == service_id), None)
    payload = {
        'ok': True,
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
def health_v021():
    return {'ok': True, 'version': APP_VERSION}


@router.get('/customers/{customer_id}', response_class=HTMLResponse)
def customer_home_v021(request: Request, customer_id: int):
    period = current_period()
    with db() as conn:
        customer = customer_or_404(conn, customer_id)
        payment_items, payment_stats = payment_snapshot(conn, customer_id, period)
        active_services = conn.execute(
            '''SELECT COUNT(*) n FROM services
               WHERE customer_id=?
                 AND (active_from_period='' OR active_from_period<=?)
                 AND (inactive_from_period='' OR inactive_from_period>?)''',
            (customer_id, period, period),
        ).fetchone()['n']
        contacts_count = conn.execute('SELECT COUNT(*) n FROM contacts WHERE customer_id=?', (customer_id,)).fetchone()['n']
        open_tasks = conn.execute('SELECT COUNT(*) n FROM tasks WHERE customer_id=? AND done=0', (customer_id,)).fetchone()['n']
        visits_count = conn.execute('SELECT COUNT(*) n FROM visits WHERE customer_id=?', (customer_id,)).fetchone()['n']
        invoice_group_count = conn.execute('SELECT COUNT(*) n FROM invoice_groups WHERE customer_id=?', (customer_id,)).fetchone()['n']
        status = effective_status(customer)
    return templates.TemplateResponse(
        'customer_home_v021.html',
        ctx(
            request,
            customer=customer,
            payment_period=period,
            payment_stats=payment_stats,
            payment_count=len(payment_items),
            active_services=active_services,
            contacts_count=contacts_count,
            open_tasks=open_tasks,
            visits_count=visits_count,
            invoice_group_count=invoice_group_count,
            payment_status=status,
        ),
    )


@router.get('/customers/{customer_id}/payment', response_class=HTMLResponse)
def customer_payment_v021(request: Request, customer_id: int):
    period = current_period()
    with db() as conn:
        customer = customer_or_404(conn, customer_id)
        items, stats = payment_snapshot(conn, customer_id, period)
        status = effective_status(customer)
    return templates.TemplateResponse(
        'payment_v021.html',
        ctx(
            request,
            customer=customer,
            payment_period=period,
            payment_items=items,
            stats=stats,
            payment_status=status,
        ),
    )


@router.post('/services/{service_id}/payment-current')
def payment_save_v021(
    request: Request,
    service_id: int,
    csrf: str = Form(...),
    amount: str = Form(...),
):
    check_csrf(request, csrf)
    period = current_period()
    value = parse_money(amount)
    with db() as conn:
        service = _service_or_404(conn, service_id)
        if not service_active_in_period(service, period) or not service_is_due(service):
            return JSONResponse({'ok': False, 'error': '这项业务本月不在缴费范围内'}, status_code=400)
        entry, rule = ensure_payment_entry(conn, service, period)
        reference = entry['reference_amount']
        if reference is None:
            reference = float(entry['amount'] or 0)
        source = 'fixed' if rule['mode'] == 'fixed' else 'manual'
        conn.execute(
            '''UPDATE payment_entries
               SET amount=?, reference_amount=?, source=?, confirmed=1, updated_at=?
               WHERE id=?''',
            (value, reference, source, now_iso(), entry['id']),
        )
        conn.execute('UPDATE services SET monthly_fee=? WHERE id=?', (value, service_id))
        if rule['mode'] == 'fixed':
            conn.execute(
                '''INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(service_id,effective_period)
                   DO UPDATE SET mode='fixed', fixed_amount=excluded.fixed_amount''',
                (service_id, period, 'fixed', value, now_iso()),
            )
            conn.execute('UPDATE services SET fixed_fee=1 WHERE id=?', (service_id,))
        return JSONResponse(_payment_json(conn, service['customer_id'], period, service_id))


@router.post('/services/{service_id}/toggle-fixed')
def toggle_fixed_v021(
    request: Request,
    service_id: int,
    csrf: str = Form(...),
):
    check_csrf(request, csrf)
    period = current_period()
    with db() as conn:
        service = _service_or_404(conn, service_id)
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
            'UPDATE services SET fixed_fee=?, monthly_fee=? WHERE id=?',
            (1 if new_mode == 'fixed' else 0, amount, service_id),
        )
        if new_mode == 'fixed':
            conn.execute(
                '''UPDATE payment_entries SET source='fixed',confirmed=1,updated_at=? WHERE id=?''',
                (now_iso(), entry['id']),
            )
        else:
            conn.execute(
                '''UPDATE payment_entries SET source='inherited',confirmed=0,updated_at=? WHERE id=?''',
                (now_iso(), entry['id']),
            )
        payload = _payment_json(conn, service['customer_id'], period, service_id)
        payload['mode'] = new_mode
        return JSONResponse(payload)


@router.post('/services/{service_id}/quick-edit')
def quick_edit_v021(
    request: Request,
    service_id: int,
    csrf: str = Form(...),
    service_type: str = Form(''),
    holder_name: str = Form(''),
    number: str = Form(''),
    account: str = Form(''),
):
    check_csrf(request, csrf)
    with db() as conn:
        service = _service_or_404(conn, service_id)
        conn.execute(
            '''UPDATE services
               SET service_type=?,holder_name=?,number=?,account=?
               WHERE id=?''',
            (service_type.strip(), holder_name.strip(), number.strip(), account.strip(), service_id),
        )
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), service['customer_id']))
    return JSONResponse({
        'ok': True,
        'service_id': service_id,
        'service_type': service_type.strip(),
        'holder_name': holder_name.strip(),
        'number': number.strip(),
        'account': account.strip(),
    })


@router.get('/customers/{customer_id}/payment.txt')
def payment_txt_v021(customer_id: int):
    period = current_period()
    with db() as conn:
        customer = customer_or_404(conn, customer_id)
        items, stats = payment_snapshot(conn, customer_id, period)
        if not stats['txt_ready']:
            raise HTTPException(409, f"还有 {stats['pending']} 项待核对，暂不能生成正式缴费TXT")
        lines = []
        for item in items:
            service = item['row']
            entry = item['payment']
            amount = float(entry['amount'] or 0)
            if not entry['confirmed'] or amount <= 0 or not (service['number'] or '').strip():
                continue
            lines.append(f"{service['number'].strip()}|{format_fee(amount)}")
    body = '\r\n'.join(lines)
    safe = ''.join(ch for ch in customer['name'] if ch not in '\\/:*?"<>|') or '缴费'
    headers = {'Content-Disposition': f"attachment; filename=\"payment.txt\"; filename*=UTF-8''{quote(safe + '.txt')}"}
    return PlainTextResponse(body, media_type='text/plain; charset=utf-8', headers=headers)


@router.get('/customers/{customer_id}/services', response_class=HTMLResponse)
def customer_services_v021(request: Request, customer_id: int):
    period = current_period()
    with db() as conn:
        customer = customer_or_404(conn, customer_id)
        invoice_groups = conn.execute('SELECT * FROM invoice_groups WHERE customer_id=? ORDER BY id', (customer_id,)).fetchall()
        rows = conn.execute(
            '''SELECT s.*, g.name invoice_group_name FROM services s
               LEFT JOIN invoice_groups g ON g.id=s.invoice_group_id
               WHERE s.customer_id=? ORDER BY s.service_type,s.source_row,s.id''',
            (customer_id,),
        ).fetchall()
        groups = defaultdict(list)
        inactive = []
        for service in rows:
            if not service_active_in_period(service, period):
                inactive.append(service)
                continue
            rule = effective_payment_rule(conn, service['id'], period, service)
            groups[service['service_type']].append({'row': service, 'rule': rule})
    return templates.TemplateResponse(
        'services_v021.html',
        ctx(request, customer=customer, service_groups=dict(groups), invoice_groups=invoice_groups, inactive_services=inactive, payment_period=period),
    )


@router.post('/customers/{customer_id}/invoice-groups')
def invoice_group_add_v021(request: Request, customer_id: int, csrf: str = Form(...), name: str = Form(...), note: str = Form('')):
    check_csrf(request, csrf)
    name = name.strip()
    if not name:
        raise HTTPException(400, '分组名称不能为空')
    with db() as conn:
        customer_or_404(conn, customer_id)
        conn.execute(
            'INSERT INTO invoice_groups(customer_id,name,note,created_at) VALUES(?,?,?,?)',
            (customer_id, name, note.strip(), now_iso()),
        )
    return RedirectResponse(f'/customers/{customer_id}/services', 303)


@router.post('/invoice-groups/{group_id}/delete')
def invoice_group_delete_v021(request: Request, group_id: int, csrf: str = Form(...)):
    check_csrf(request, csrf)
    with db() as conn:
        row = conn.execute('SELECT customer_id FROM invoice_groups WHERE id=?', (group_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        conn.execute('UPDATE services SET invoice_group_id=NULL WHERE invoice_group_id=?', (group_id,))
        conn.execute('DELETE FROM invoice_groups WHERE id=?', (group_id,))
    return RedirectResponse(f"/customers/{row['customer_id']}/services", 303)


@router.post('/customers/{customer_id}/services')
def service_add_v021(
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
    period = current_period()
    mode = 'fixed' if payment_mode == 'fixed' else 'variable'
    initial_amount = parse_money(fixed_amount or '0')
    with db() as conn:
        customer_or_404(conn, customer_id)
        gid = valid_invoice_group(conn, customer_id, invoice_group_id)
        cur = conn.execute(
            '''INSERT INTO services
               (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,payment_cycle,payment_method,invoice_type,package_type,last_payment_date,invoice_group_id,active_from_period)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (customer_id, service_type.strip(), holder_name.strip(), number.strip(), account.strip(), initial_amount,
             1 if mode == 'fixed' else 0, payment_cycle.strip(), payment_method.strip(), invoice_type.strip(),
             package_type.strip(), last_payment_date.strip(), gid, period),
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
                (sid, period, initial_amount, initial_amount, 'fixed' if mode == 'fixed' else 'manual',
                 1 if mode == 'fixed' else 0, now, now),
            )
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), customer_id))
    return RedirectResponse(f'/customers/{customer_id}/services', 303)


@router.post('/services/{service_id}/edit')
def service_edit_v021(
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
    period = current_period()
    mode = 'fixed' if payment_mode == 'fixed' else 'variable'
    fixed = parse_money(fixed_amount or '0')
    with db() as conn:
        old = _service_or_404(conn, service_id)
        gid = valid_invoice_group(conn, old['customer_id'], invoice_group_id)
        entry, old_rule = ensure_payment_entry(conn, old, period)
        current_amount = float(entry['amount'] or 0)
        conn.execute(
            '''UPDATE services SET service_type=?,holder_name=?,number=?,account=?,fixed_fee=?,payment_cycle=?,payment_method=?,
               invoice_type=?,package_type=?,last_payment_date=?,invoice_group_id=?,monthly_fee=? WHERE id=?''',
            (service_type.strip(), holder_name.strip(), number.strip(), account.strip(), 1 if mode == 'fixed' else 0,
             payment_cycle.strip(), payment_method.strip(), invoice_type.strip(), package_type.strip(), last_payment_date.strip(),
             gid, fixed if mode == 'fixed' else current_amount, service_id),
        )
        conn.execute(
            '''INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(service_id,effective_period)
               DO UPDATE SET mode=excluded.mode,fixed_amount=excluded.fixed_amount''',
            (service_id, period, mode, fixed if mode == 'fixed' else 0, now_iso()),
        )
        if mode == 'fixed':
            conn.execute(
                '''UPDATE payment_entries SET amount=?,source='fixed',confirmed=1,updated_at=? WHERE id=?''',
                (fixed, now_iso(), entry['id']),
            )
        elif old_rule['mode'] == 'fixed':
            conn.execute(
                '''UPDATE payment_entries SET source='inherited',confirmed=0,updated_at=? WHERE id=?''',
                (now_iso(), entry['id']),
            )
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), old['customer_id']))
    return RedirectResponse(f"/customers/{old['customer_id']}/services", 303)


@router.post('/services/{service_id}/delete')
def service_stop_v021(request: Request, service_id: int, csrf: str = Form(...)):
    check_csrf(request, csrf)
    period = current_period()
    with db() as conn:
        service = _service_or_404(conn, service_id)
        conn.execute('UPDATE services SET inactive_from_period=? WHERE id=?', (period, service_id))
        conn.execute('DELETE FROM payment_entries WHERE service_id=? AND period=?', (service_id, period))
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), service['customer_id']))
    return RedirectResponse(f"/customers/{service['customer_id']}/services", 303)


@router.get('/customers/{customer_id}/contacts', response_class=HTMLResponse)
def customer_contacts_v021(request: Request, customer_id: int):
    with db() as conn:
        customer = customer_or_404(conn, customer_id)
        contacts = conn.execute('SELECT * FROM contacts WHERE customer_id=? ORDER BY id', (customer_id,)).fetchall()
    return templates.TemplateResponse('contacts_v021.html', ctx(request, customer=customer, contacts=contacts))


@router.post('/customers/{customer_id}/contacts')
def contact_add_v021(
    request: Request, customer_id: int, csrf: str = Form(...),
    kind: str = Form(''), name: str = Form(''), relationship: str = Form(''), phone: str = Form('')
):
    check_csrf(request, csrf)
    with db() as conn:
        customer_or_404(conn, customer_id)
        conn.execute(
            'INSERT INTO contacts(customer_id,kind,name,relationship,phone) VALUES(?,?,?,?,?)',
            (customer_id, kind.strip(), name.strip(), relationship.strip(), phone.strip()),
        )
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), customer_id))
    return RedirectResponse(f'/customers/{customer_id}/contacts', 303)


@router.post('/contacts/{contact_id}/delete')
def contact_delete_v021(request: Request, contact_id: int, csrf: str = Form(...)):
    check_csrf(request, csrf)
    with db() as conn:
        row = conn.execute('SELECT customer_id FROM contacts WHERE id=?', (contact_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        conn.execute('DELETE FROM contacts WHERE id=?', (contact_id,))
    return RedirectResponse(f"/customers/{row['customer_id']}/contacts", 303)


@router.get('/customers/{customer_id}/tasks', response_class=HTMLResponse)
def customer_tasks_v021(request: Request, customer_id: int):
    with db() as conn:
        customer = customer_or_404(conn, customer_id)
        tasks = conn.execute('SELECT * FROM tasks WHERE customer_id=? ORDER BY done,remind_date,id DESC', (customer_id,)).fetchall()
    return templates.TemplateResponse('tasks_v021.html', ctx(request, customer=customer, tasks=tasks))


def _task_reminder_value(remind_at: str = '', remind_date: str = '') -> tuple[str, str]:
    raw = (remind_at or '').strip() or (remind_date or '').strip()
    if not raw:
        return '', ''
    normalized = raw.replace(' ', 'T')
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = datetime.strptime(raw, '%Y-%m-%d')
        except ValueError:
            raise HTTPException(400, '提醒时间格式无效')
    if 'T' in normalized:
        value = parsed.strftime('%Y-%m-%dT%H:%M')
    else:
        value = parsed.strftime('%Y-%m-%d')
    return value, parsed.strftime('%Y-%m-%d')


@router.post('/customers/{customer_id}/tasks')
def task_add_v021(
    request: Request, customer_id: int, csrf: str = Form(...),
    title: str = Form(...), remind_at: str = Form(''), remind_date: str = Form(''),
    note: str = Form(''), is_payment_review: str = Form('0')
):
    check_csrf(request, csrf)
    title = title.strip()
    if not title:
        raise HTTPException(400, '待办内容不能为空')
    reminder, legacy_date = _task_reminder_value(remind_at, remind_date)
    now = now_iso()
    with db() as conn:
        customer_or_404(conn, customer_id)
        conn.execute(
            '''INSERT INTO tasks
               (customer_id,title,remind_date,remind_at,note,is_payment_review,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?)''',
            (customer_id, title, legacy_date, reminder, note.strip(), 1 if is_payment_review == '1' else 0, now, now),
        )
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now, customer_id))
    return RedirectResponse(f'/customers/{customer_id}?tab=tasks', 303)


@router.post('/tasks/{task_id}/edit')
def task_edit_v164(
    request: Request, task_id: int, csrf: str = Form(...),
    title: str = Form(...), remind_at: str = Form(''), remind_date: str = Form(''),
    note: str = Form(''), is_payment_review: str = Form('0')
):
    check_csrf(request, csrf)
    title = title.strip()
    if not title:
        raise HTTPException(400, '待办内容不能为空')
    reminder, legacy_date = _task_reminder_value(remind_at, remind_date)
    with db() as conn:
        row = conn.execute('SELECT customer_id FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        now = now_iso()
        conn.execute(
            '''UPDATE tasks
               SET title=?,remind_date=?,remind_at=?,note=?,is_payment_review=?,updated_at=?
               WHERE id=?''',
            (title, legacy_date, reminder, note.strip(), 1 if is_payment_review == '1' else 0, now, task_id),
        )
        if row['customer_id']:
            conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now, row['customer_id']))
    return RedirectResponse(f"/customers/{row['customer_id']}?tab=tasks" if row['customer_id'] else '/', 303)


@router.post('/tasks/{task_id}/toggle')
def task_toggle_v021(request: Request, task_id: int, csrf: str = Form(...), finish_delete: str = Form('0')):
    check_csrf(request, csrf)
    with db() as conn:
        row = conn.execute('SELECT customer_id,done FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        now = now_iso()
        if finish_delete == '1':
            if row['done']:
                raise HTTPException(409, '待办已办结')
            conn.execute('DELETE FROM tasks WHERE id=? AND done=0', (task_id,))
        else:
            conn.execute('UPDATE tasks SET done=?,updated_at=? WHERE id=?', (0 if row['done'] else 1, now, task_id))
        if row['customer_id']:
            conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now, row['customer_id']))
    return RedirectResponse(f"/customers/{row['customer_id']}?tab=tasks" if row['customer_id'] else '/', 303)


@router.get('/customers/{customer_id}/visits', response_class=HTMLResponse)
def customer_visits_v021(request: Request, customer_id: int):
    with db() as conn:
        customer = customer_or_404(conn, customer_id)
        visits = conn.execute('SELECT * FROM visits WHERE customer_id=? ORDER BY visit_date DESC,id DESC', (customer_id,)).fetchall()
    return templates.TemplateResponse('visits_v021.html', ctx(request, customer=customer, visits=visits))


@router.post('/customers/{customer_id}/visits')
def visit_add_v021(
    request: Request, customer_id: int, csrf: str = Form(...),
    visit_date: str = Form(''), kind: str = Form('拜访'), result: str = Form(''), plan: str = Form(''),
    create_task: str = Form('0'), task_date: str = Form('')
):
    check_csrf(request, csrf)
    with db() as conn:
        customer_or_404(conn, customer_id)
        conn.execute(
            'INSERT INTO visits(customer_id,visit_date,kind,result,plan,created_at) VALUES(?,?,?,?,?,?)',
            (customer_id, visit_date.strip() or date.today().isoformat(), kind.strip(), result.strip(), plan.strip(), now_iso()),
        )
        if create_task == '1' and plan.strip():
            conn.execute(
                'INSERT INTO tasks(customer_id,title,remind_date,note,created_at) VALUES(?,?,?,?,?)',
                (customer_id, plan.strip(), task_date.strip(), '由跟进记录自动创建', now_iso()),
            )
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), customer_id))
    return RedirectResponse(f'/customers/{customer_id}/visits', 303)


@router.post('/customers/{customer_id}/payment-status')
def payment_status_v021(request: Request, customer_id: int, csrf: str = Form(...), action: str = Form(...)):
    check_csrf(request, csrf)
    period = current_period()
    with db() as conn:
        customer_or_404(conn, customer_id)
        if action == 'notify':
            conn.execute('UPDATE customers SET notified=1,completed=0,payment_period=?,updated_at=? WHERE id=?', (period, now_iso(), customer_id))
        elif action == 'complete':
            _, stats = payment_snapshot(conn, customer_id, period)
            if not stats['txt_ready']:
                raise HTTPException(409, f"还有 {stats['pending']} 项待核对")
            conn.execute('UPDATE customers SET notified=1,completed=1,payment_period=?,updated_at=? WHERE id=?', (period, now_iso(), customer_id))
            rows = conn.execute('SELECT id,payment_cycle FROM services WHERE customer_id=?', (customer_id,)).fetchall()
            for service in rows:
                months = cycle_months(service['payment_cycle'])
                if months and months > 1:
                    conn.execute('UPDATE services SET last_payment_date=? WHERE id=?', (date.today().isoformat(), service['id']))
        elif action == 'reset':
            conn.execute('UPDATE customers SET notified=0,completed=0,payment_period=?,updated_at=? WHERE id=?', (period, now_iso(), customer_id))
        else:
            raise HTTPException(400)
    return RedirectResponse(f'/customers/{customer_id}/payment', 303)

