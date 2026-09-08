from __future__ import annotations

from collections import defaultdict
from datetime import date
import calendar
import re

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import config
from .db import db, now_iso
from .security import require_csrf
from .payment_v02 import (
    current_period,
    add_months,
    service_active_in_period,
    service_is_due,
    service_interval_months,
    effective_payment_rule,
    ensure_payment_entry,
    payment_snapshot,
    parse_money,
    format_fee,
    valid_invoice_group,
)
from .v023_routes import ATTR_OPTIONS, VALID_ATTR_KEYS, attr_value
from .v025_routes import customer_or_404, service_or_404, promotion_or_404, _payment_run

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')
APP_VERSION = '0.2.6'
DATE_RE = re.compile(r'^\d{4}/\d{2}/\d{2}$')

ATTR_OPTIONS_026 = [
    ('service_type', '类型'),
    ('holder_name', '姓名/属性'),
    ('invoice_group', '发票组'),
    ('payment_interval_months', '缴费周期（月）'),
    ('payment_method', '付款方式'),
    ('invoice_type', '发票类型'),
    ('package_type', '套餐类型'),
    ('last_payment_date', '上次缴费'),
    ('notes', '备注'),
]
VALID_ATTR_KEYS_026 = {k for k, _ in ATTR_OPTIONS_026}


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


def parse_date_text(value: str, *, required: bool = False, field: str = '日期') -> str:
    raw = (value or '').strip()
    if not raw:
        if required:
            raise HTTPException(400, f'{field}必须填写，格式如 1900/07/07')
        return ''
    if not DATE_RE.fullmatch(raw):
        raise HTTPException(400, f'{field}格式必须为 1900/07/07')
    try:
        d = date(int(raw[0:4]), int(raw[5:7]), int(raw[8:10]))
    except ValueError:
        raise HTTPException(400, f'{field}不是有效日期')
    return d.isoformat()


def date_text(value: str) -> str:
    raw = (value or '').strip()
    if not raw:
        return ''
    if '/' in raw and len(raw) >= 10:
        return raw[:10]
    if len(raw) >= 10 and raw[4] == '-' and raw[7] == '-':
        return raw[:10].replace('-', '/')
    return raw


def month_text(value: str) -> str:
    return (value or '').replace('-', '/')


def period_shift(period: str, months: int) -> str:
    y, m = [int(x) for x in period[:7].split('-')]
    idx = y * 12 + (m - 1) + months
    return f'{idx // 12:04d}-{idx % 12 + 1:02d}'


def promotion_bucket(expiry_date: str, status: str = 'active') -> str:
    if (status or 'active') != 'active':
        return 'history'
    raw = (expiry_date or '').strip()
    if not raw:
        return 'later'
    try:
        exp_period = date.fromisoformat(raw[:10]).strftime('%Y-%m')
    except Exception:
        return 'later'
    now_period = current_period()
    next_month = period_shift(now_period, 1)
    next_next = period_shift(now_period, 2)
    # 用户工作定义：到期月份在下个月或更早，视为“已经到期”；下下月视为“即将到期”。
    if exp_period <= next_month:
        return 'expired'
    if exp_period == next_next:
        return 'soon'
    return 'later'


def promotion_label(bucket: str) -> str:
    return {
        'expired': '已经到期',
        'soon': '即将到期',
        'later': '后续到期',
        'history': '历史',
        'none': '无优惠',
    }.get(bucket, '无优惠')


def display_pair(customer):
    k1 = (customer['payment_display_attr_1'] or 'service_type').strip()
    k2 = (customer['payment_display_attr_2'] or 'holder_name').strip()
    # v0.2.6 用“周期（月）”替代旧的自由文本缴费周期。
    if k1 == 'payment_cycle':
        k1 = 'payment_interval_months'
    if k2 == 'payment_cycle':
        k2 = 'payment_interval_months'
    if k1 not in VALID_ATTR_KEYS_026:
        k1 = 'service_type'
    if k2 not in VALID_ATTR_KEYS_026 or k2 == k1:
        k2 = 'holder_name' if k1 != 'holder_name' else 'service_type'
    return k1, k2


def display_value(service, key: str) -> str:
    if key == 'payment_interval_months':
        months = int(service['payment_interval_months'] or 0)
        return str(months) if months else '—'
    if key == 'last_payment_date':
        return date_text(service['last_payment_date']) or '—'
    return attr_value(service, key)


def payment_json(conn, service_id: int):
    period = current_period()
    items, stats = payment_snapshot(conn, conn.execute('SELECT customer_id FROM services WHERE id=?', (service_id,)).fetchone()['customer_id'], period)
    item = next((x for x in items if x['row']['id'] == service_id), None)
    if not item:
        raise HTTPException(400, '该业务本月不在缴费清单中')
    pe = item['payment']
    return {
        'ok': True,
        'amount': float(pe['amount'] or 0),
        'display_amount': format_fee(float(pe['amount'] or 0)),
        'confirmed': bool(pe['confirmed']),
        'mode': item['rule']['mode'],
        'delta': item['delta'],
        **stats,
    }


def derive_schedule(old, interval: int, last_iso: str) -> tuple[str, str]:
    interval = int(interval or 0)
    cycle_text = f'{interval}个月' if interval > 0 else ''
    if interval <= 1:
        return cycle_text, ''
    if last_iso:
        return cycle_text, add_months(date.fromisoformat(last_iso), interval).strftime('%Y-%m')
    old_interval = int(old['payment_interval_months'] or 0) if old is not None else 0
    old_next = (old['next_payment_period'] or '').strip() if old is not None else ''
    if old_next and old_interval == interval:
        return cycle_text, old_next
    return cycle_text, current_period()


@router.get('/health')
def health_v026():
    return {'ok': True, 'version': APP_VERSION}


@router.get('/customers/{customer_id}', response_class=HTMLResponse)
def customer_workspace_v026(request: Request, customer_id: int, tab: str = 'payment'):
    period = current_period()
    tabs = {'payment', 'services', 'promotions', 'contacts', 'tasks', 'visits'}
    active_tab = tab if tab in tabs else 'payment'
    with db() as conn:
        customer = customer_or_404(conn, customer_id)
        display1, display2 = display_pair(customer)
        payment_items, payment_stats = payment_snapshot(conn, customer_id, period)
        enriched_payment = []
        for raw in payment_items:
            item = dict(raw)
            s = item['row']
            item['display_value_1'] = display_value(s, display1)
            item['display_value_2'] = display_value(s, display2)
            item['last_payment_display'] = date_text(s['last_payment_date'])
            enriched_payment.append(item)
        payment_run = _payment_run(conn, customer_id, period, payment_stats)

        invoice_groups = conn.execute('SELECT * FROM invoice_groups WHERE customer_id=? ORDER BY id', (customer_id,)).fetchall()
        services = conn.execute(
            '''SELECT s.*,g.name invoice_group_name FROM services s
               LEFT JOIN invoice_groups g ON g.id=s.invoice_group_id
               WHERE s.customer_id=?
               ORDER BY CASE WHEN COALESCE(s.sort_order,0)>0 THEN s.sort_order ELSE 100000000+s.id END,s.id''',
            (customer_id,),
        ).fetchall()

        promo_rows = conn.execute(
            '''SELECT p.*,s.service_type,s.holder_name,s.number,s.account,s.customer_id
               FROM promotions p JOIN services s ON s.id=p.service_id
               WHERE s.customer_id=? ORDER BY CASE WHEN p.status='active' THEN 0 ELSE 1 END,p.expiry_date,p.id DESC''',
            (customer_id,),
        ).fetchall()
        active_promo_by_service = {}
        promotions = []
        promotion_groups = defaultdict(list)
        for p in promo_rows:
            bucket = promotion_bucket(p['expiry_date'], p['status'])
            info = {'row': p, 'bucket': bucket, 'label': promotion_label(bucket), 'expiry_display': date_text(p['expiry_date']), 'start_display': date_text(p['start_date'])}
            promotions.append(info)
            promotion_groups[bucket].append(info)
            if p['status'] == 'active' and p['service_id'] not in active_promo_by_service:
                active_promo_by_service[p['service_id']] = info

        business_rows = []
        service_types = []
        seen_types = set()
        for s in services:
            if not service_active_in_period(s, period):
                continue
            typ = (s['service_type'] or '未分类').strip() or '未分类'
            if typ not in seen_types:
                seen_types.add(typ)
                service_types.append(typ)
            rule = effective_payment_rule(conn, s['id'], period, s)
            promo = active_promo_by_service.get(s['id'])
            business_rows.append({
                'row': s,
                'rule': rule,
                'due': service_is_due(s),
                'months': int(s['payment_interval_months'] or 0),
                'last_payment_display': date_text(s['last_payment_date']),
                'next_payment_display': month_text(s['next_payment_period']),
                'promo': promo,
                'promo_bucket': promo['bucket'] if promo else 'none',
                'promo_label': promo['label'] if promo else '无优惠',
            })

        contacts = conn.execute('SELECT * FROM contacts WHERE customer_id=? ORDER BY id', (customer_id,)).fetchall()
        tasks = conn.execute('SELECT * FROM tasks WHERE customer_id=? ORDER BY done,remind_date,id DESC', (customer_id,)).fetchall()
        open_tasks = [t for t in tasks if not t['done']]
        visits = conn.execute('SELECT * FROM visits WHERE customer_id=? ORDER BY visit_date DESC,id DESC', (customer_id,)).fetchall()

    promo_attention = len(promotion_groups['expired']) + len(promotion_groups['soon'])
    return templates.TemplateResponse(
        'customer_workspace_v026.html',
        ctx(
            request,
            customer=customer,
            active_tab=active_tab,
            payment_period=period,
            payment_items=enriched_payment,
            payment_stats=payment_stats,
            payment_run=payment_run,
            invoice_groups=invoice_groups,
            business_rows=business_rows,
            service_types=service_types,
            promotions=promotions,
            promotion_groups=dict(promotion_groups),
            promo_attention=promo_attention,
            contacts=contacts,
            tasks=tasks,
            open_tasks=open_tasks,
            visits=visits,
            attr_options=ATTR_OPTIONS_026,
            customer_display_attr_1=display1,
            customer_display_attr_2=display2,
        ),
    )


@router.post('/services/{service_id}/payment-review-toggle')
def toggle_payment_review_v026(request: Request, service_id: int, csrf: str = Form(...)):
    check_csrf(request, csrf)
    period = current_period()
    with db() as conn:
        s = service_or_404(conn, service_id)
        if not service_active_in_period(s, period) or not service_is_due(s):
            return JSONResponse({'ok': False, 'error': '该业务本月无需缴费'}, status_code=400)
        pe, rule = ensure_payment_entry(conn, s, period)
        if rule['mode'] == 'fixed':
            return JSONResponse({'ok': False, 'error': '固定金额自动确认；如需人工核对请先改为变动金额'}, status_code=400)
        new_confirmed = 0 if bool(pe['confirmed']) else 1
        conn.execute('UPDATE payment_entries SET confirmed=?,updated_at=? WHERE id=?', (new_confirmed, now_iso(), pe['id']))
        data = payment_json(conn, service_id)
    return JSONResponse(data)


@router.post('/customers/{customer_id}/display-attributes')
def display_attributes_v026(request: Request, customer_id: int, csrf: str = Form(...), display_attr_1: str = Form(...), display_attr_2: str = Form(...)):
    check_csrf(request, csrf)
    if display_attr_1 not in VALID_ATTR_KEYS_026 or display_attr_2 not in VALID_ATTR_KEYS_026:
        raise HTTPException(400, '默认显示属性无效')
    if display_attr_1 == display_attr_2:
        return JSONResponse({'ok': False, 'error': '两个默认属性不能相同'}, status_code=400)
    with db() as conn:
        customer_or_404(conn, customer_id)
        conn.execute('UPDATE customers SET payment_display_attr_1=?,payment_display_attr_2=?,updated_at=? WHERE id=?',
                     (display_attr_1, display_attr_2, now_iso(), customer_id))
        rows = conn.execute('''SELECT s.*,g.name invoice_group_name FROM services s LEFT JOIN invoice_groups g ON g.id=s.invoice_group_id WHERE s.customer_id=?''', (customer_id,)).fetchall()
        values = {str(s['id']): {'v1': display_value(s, display_attr_1), 'v2': display_value(s, display_attr_2)} for s in rows}
    return JSONResponse({'ok': True, 'values': values})


@router.post('/services/{service_id}/attributes')
def edit_service_attributes_v026(
    request: Request,
    service_id: int,
    csrf: str = Form(...),
    service_type: str = Form(''), holder_name: str = Form(''), number: str = Form(''), account: str = Form(''),
    payment_interval_months: int = Form(0), payment_method: str = Form(''), invoice_type: str = Form(''),
    invoice_group_id: str = Form(''), package_type: str = Form(''), last_payment_date: str = Form(''), notes: str = Form(''),
):
    check_csrf(request, csrf)
    if payment_interval_months < 0 or payment_interval_months > 120:
        raise HTTPException(400, '缴费周期（月）必须是0到120之间的整数')
    last_iso = parse_date_text(last_payment_date, field='上次缴费日期')
    with db() as conn:
        old = service_or_404(conn, service_id)
        gid = valid_invoice_group(conn, old['customer_id'], invoice_group_id)
        cycle_text, next_period = derive_schedule(old, payment_interval_months, last_iso)
        conn.execute(
            '''UPDATE services SET service_type=?,holder_name=?,number=?,account=?,payment_cycle=?,payment_interval_months=?,next_payment_period=?,
               payment_method=?,invoice_type=?,invoice_group_id=?,package_type=?,last_payment_date=?,notes=? WHERE id=?''',
            (service_type.strip(), holder_name.strip(), number.strip(), account.strip(), cycle_text, payment_interval_months, next_period,
             payment_method.strip(), invoice_type.strip(), gid, package_type.strip(), last_iso, notes.strip(), service_id),
        )
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), old['customer_id']))
        s = service_or_404(conn, service_id)
    return JSONResponse({
        'ok': True, 'service_id': service_id, 'service_type': s['service_type'], 'holder_name': s['holder_name'],
        'number': s['number'], 'account': s['account'], 'payment_interval_months': s['payment_interval_months'],
        'payment_method': s['payment_method'], 'invoice_type': s['invoice_type'], 'invoice_group_id': s['invoice_group_id'] or '',
        'package_type': s['package_type'], 'last_payment_date': date_text(s['last_payment_date']), 'notes': s['notes'],
    })


@router.post('/customers/{customer_id}/services-v026')
def add_service_v026(
    request: Request,
    customer_id: int,
    csrf: str = Form(...),
    service_type: str = Form(...), holder_name: str = Form(''), number: str = Form(''), account: str = Form(''),
    payment_mode: str = Form('variable'), fixed_amount: str = Form('0'), payment_interval_months: int = Form(1),
    payment_method: str = Form(''), invoice_type: str = Form(''), package_type: str = Form(''), last_payment_date: str = Form(''),
    invoice_group_id: str = Form(''), notes: str = Form(''),
):
    check_csrf(request, csrf)
    if payment_mode not in {'fixed', 'variable'}:
        raise HTTPException(400, '缴费规则无效')
    if payment_interval_months < 0 or payment_interval_months > 120:
        raise HTTPException(400, '缴费周期（月）必须是0到120之间的整数')
    amount = parse_money(fixed_amount)
    last_iso = parse_date_text(last_payment_date, field='上次缴费日期')
    period = current_period()
    with db() as conn:
        customer_or_404(conn, customer_id)
        gid = valid_invoice_group(conn, customer_id, invoice_group_id)
        max_sort = conn.execute('SELECT COALESCE(MAX(sort_order),0) m FROM services WHERE customer_id=?', (customer_id,)).fetchone()['m']
        cycle_text = f'{payment_interval_months}个月' if payment_interval_months > 0 else ''
        next_period = ''
        if payment_interval_months > 1:
            next_period = add_months(date.fromisoformat(last_iso), payment_interval_months).strftime('%Y-%m') if last_iso else period
        cur = conn.execute(
            '''INSERT INTO services(customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,payment_cycle,
               payment_interval_months,next_payment_period,payment_method,invoice_type,package_type,last_payment_date,
               invoice_group_id,active_from_period,sort_order,notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (customer_id, service_type.strip(), holder_name.strip(), number.strip(), account.strip(), amount,
             1 if payment_mode == 'fixed' else 0, cycle_text, payment_interval_months, next_period,
             payment_method.strip(), invoice_type.strip(), package_type.strip(), last_iso, gid, period, int(max_sort or 0) + 10, notes.strip()),
        )
        sid = cur.lastrowid
        conn.execute('''INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at) VALUES(?,?,?,?,?)''',
                     (sid, period, payment_mode, amount if payment_mode == 'fixed' else 0, now_iso()))
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), customer_id))
    return RedirectResponse(f'/customers/{customer_id}?tab=services', 303)


@router.post('/services/{service_id}/edit-v026')
def edit_service_form_v026(
    request: Request,
    service_id: int,
    csrf: str = Form(...), service_type: str = Form(''), holder_name: str = Form(''), number: str = Form(''), account: str = Form(''),
    payment_interval_months: int = Form(0), payment_method: str = Form(''), invoice_type: str = Form(''),
    invoice_group_id: str = Form(''), package_type: str = Form(''), last_payment_date: str = Form(''), notes: str = Form(''),
):
    result = edit_service_attributes_v026(request, service_id, csrf, service_type, holder_name, number, account,
                                         payment_interval_months, payment_method, invoice_type, invoice_group_id,
                                         package_type, last_payment_date, notes)
    with db() as conn:
        cid = service_or_404(conn, service_id)['customer_id']
    return RedirectResponse(f'/customers/{cid}?tab=services', 303)


@router.post('/customers/{customer_id}/promotions')
def add_promotion_v026(
    request: Request,
    customer_id: int,
    csrf: str = Form(...), service_id: int = Form(...), name: str = Form(...),
    start_date: str = Form(''), expiry_date: str = Form(...), notes: str = Form(''),
):
    check_csrf(request, csrf)
    start_iso = parse_date_text(start_date, field='优惠开始日期')
    expiry_iso = parse_date_text(expiry_date, required=True, field='优惠到期日期')
    with db() as conn:
        customer_or_404(conn, customer_id)
        service = service_or_404(conn, service_id)
        if service['customer_id'] != customer_id:
            raise HTTPException(400, '业务不属于该客户')
        conn.execute(
            '''INSERT INTO promotions(service_id,name,start_date,expiry_date,remind_days,status,renewed_at,notes,created_at)
               VALUES(?,?,?,?,60,'active','',?,?)''',
            (service_id, name.strip(), start_iso, expiry_iso, notes.strip(), now_iso()),
        )
    return RedirectResponse(f'/customers/{customer_id}?tab=promotions', 303)


@router.post('/promotions/{promotion_id}/renew')
def renew_promotion_v026(
    request: Request,
    promotion_id: int,
    csrf: str = Form(...), new_start_date: str = Form(''), new_expiry_date: str = Form(...), notes: str = Form(''),
):
    check_csrf(request, csrf)
    with db() as conn:
        old = promotion_or_404(conn, promotion_id)
        if old['status'] != 'active':
            raise HTTPException(400, '这条优惠已经结束或续约')
        start_iso = parse_date_text(new_start_date, field='新优惠开始日期') or old['expiry_date']
        expiry_iso = parse_date_text(new_expiry_date, required=True, field='新优惠到期日期')
        cur = conn.execute(
            '''INSERT INTO promotions(service_id,name,start_date,expiry_date,remind_days,status,renewed_at,notes,created_at)
               VALUES(?,?,?,?,?,'active','',?,?)''',
            (old['service_id'], old['name'], start_iso, expiry_iso, int(old['remind_days'] or 60), notes.strip() or old['notes'], now_iso()),
        )
        new_id = cur.lastrowid
        conn.execute("UPDATE promotions SET status='renewed',renewed_at=?,renewed_to_id=? WHERE id=?", (now_iso(), new_id, promotion_id))
        cid = old['customer_id']
    return RedirectResponse(f'/customers/{cid}?tab=promotions', 303)
