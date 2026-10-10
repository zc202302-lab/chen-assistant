from __future__ import annotations

from collections import defaultdict
from datetime import date
from types import SimpleNamespace
import json

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from .templating import Jinja2Templates

from . import config
from .db import db, now_iso
from .payment_v02 import current_period, service_active_in_period, service_is_due, effective_payment_rule, payment_snapshot
from .v025_routes import customer_or_404, promotion_or_404, _payment_run
from .v026_routes import check_csrf, parse_date_text, date_text, month_text, promotion_bucket, display_pair, display_value, ATTR_OPTIONS_026

from .promotions import expiry_text, available_slot

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')
APP_VERSION = '0.2.7'

DEFAULT_COL_WIDTHS = {'attr': 190, 'number': 260, 'account': 300, 'amount': 170}
COL_LIMITS = {'attr': (110, 520), 'number': (150, 760), 'account': (160, 820), 'amount': (120, 320)}


def ctx(request: Request, **extra):
    session = getattr(request.state, 'session', None)
    base = {'request': request, 'csrf': session['csrf_token'] if session else '', 'today': date.today(), 'app_version': APP_VERSION}
    base.update(extra)
    return base


def _meta_get(conn, key: str, default=''):
    row = conn.execute('SELECT value FROM app_meta WHERE key=?', (key,)).fetchone()
    return row['value'] if row else default


def _meta_set(conn, key: str, value: str):
    conn.execute('INSERT OR REPLACE INTO app_meta(key,value) VALUES(?,?)', (key, value))


def _column_widths(conn, customer_id: int):
    raw = _meta_get(conn, f'payment_col_widths:{customer_id}', '')
    result = dict(DEFAULT_COL_WIDTHS)
    if raw:
        try:
            saved = json.loads(raw)
            for key, (lo, hi) in COL_LIMITS.items():
                if key in saved:
                    result[key] = max(lo, min(hi, int(saved[key])))
        except Exception:
            pass
    return result


def _promo_order(conn, customer_id: int, group_key: str):
    raw = _meta_get(conn, f'promo_order:{customer_id}:{group_key}', '')
    if not raw:
        return []
    try:
        return [int(x) for x in json.loads(raw)]
    except Exception:
        return []


def _promo_group_key(row) -> str:
    number = (row['number'] or '').strip()
    return number if number else f"__service_{row['service_id']}"


@router.get('/health')
def health_v027():
    return {'ok': True, 'version': APP_VERSION}


@router.get('/customers/{customer_id}', response_class=HTMLResponse)
def customer_workspace_v027(request: Request, customer_id: int, tab: str = 'payment'):
    period = current_period()
    tabs = {'payment', 'services', 'promotions', 'contacts', 'tasks', 'visits'}
    active_tab = tab if tab in tabs else 'payment'
    with db() as conn:
        customer = customer_or_404(conn, customer_id)
        display1, display2 = display_pair(customer)
        col_widths = _column_widths(conn, customer_id)

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
               WHERE s.customer_id=? AND COALESCE(p.status,'active')='active'
               ORDER BY p.expiry_date,p.id''',
            (customer_id,),
        ).fetchall()
        active_promos_by_service = defaultdict(list)
        attention_rows = []
        for p in promo_rows:
            bucket = promotion_bucket(p['expiry_date'], p['status'])
            info = {'row': p, 'bucket': bucket, 'expiry_display': expiry_text(p['expiry_date']), 'start_display': date_text(p['start_date'])}
            active_promos_by_service[p['service_id']].append(info)
            if bucket in {'expired', 'soon'}:
                attention_rows.append(info)

        promo_groups_map = {}
        for info in attention_rows:
            p = info['row']
            key = _promo_group_key(p)
            group = promo_groups_map.setdefault(key, {
                'key': key,
                'number': (p['number'] or '').strip(),
                'account': (p['account'] or '').strip(),
                'service_type': p['service_type'] or '',
                'holder_name': p['holder_name'] or '',
                'service_id': p['service_id'],
                'items': [],
                'expired_count': 0,
                'soon_count': 0,
            })
            group['items'].append(info)
            group[f"{info['bucket']}_count"] += 1

        promo_groups = []
        for group in promo_groups_map.values():
            order = _promo_order(conn, customer_id, group['key'])
            rank = {pid: i for i, pid in enumerate(order)}
            group['items'].sort(key=lambda x: (rank.get(x['row']['id'], 10**9), x['row']['expiry_date'] or '9999-12-31', x['row']['id']))
            promo_groups.append(SimpleNamespace(**group))
        promo_groups.sort(key=lambda g: (0 if g.expired_count else 1, g.number or g.account, g.service_id))
        promo_attention = sum(len(g.items) for g in promo_groups)

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
            promos = active_promos_by_service.get(s['id'], [])
            expired_n = sum(1 for p in promos if p['bucket'] == 'expired')
            soon_n = sum(1 for p in promos if p['bucket'] == 'soon')
            if expired_n:
                promo_filter, promo_label = 'expired', f'已到期 {expired_n}'
            elif soon_n:
                promo_filter, promo_label = 'soon', f'即将到期 {soon_n}'
            elif promos:
                promo_filter, promo_label = 'normal', f'优惠 {len(promos)}'
            else:
                promo_filter, promo_label = 'none', '无优惠'
            nearest = min(promos, key=lambda p: p['row']['expiry_date'] or '9999-12-31') if promos else None
            business_rows.append({
                'row': s, 'rule': rule, 'due': service_is_due(s), 'months': int(s['payment_interval_months'] or 0),
                'last_payment_display': date_text(s['last_payment_date']), 'next_payment_display': month_text(s['next_payment_period']),
                'promo_count': len(promos), 'promo_filter': promo_filter, 'promo_label': promo_label, 'promo_nearest': nearest,
            })

        contacts = conn.execute('SELECT * FROM contacts WHERE customer_id=? ORDER BY id', (customer_id,)).fetchall()
        tasks = conn.execute('SELECT * FROM tasks WHERE customer_id=? ORDER BY done,remind_date,id DESC', (customer_id,)).fetchall()
        open_tasks = [t for t in tasks if not t['done']]
        visits = conn.execute('SELECT * FROM visits WHERE customer_id=? ORDER BY visit_date DESC,id DESC', (customer_id,)).fetchall()

    return templates.TemplateResponse(
        'customer_workspace_v027.html',
        ctx(request, customer=customer, active_tab=active_tab, payment_period=period, payment_items=enriched_payment,
            payment_stats=payment_stats, payment_run=payment_run, col_widths=col_widths, invoice_groups=invoice_groups,
            business_rows=business_rows, service_types=service_types, promo_groups=promo_groups, promo_attention=promo_attention,
            contacts=contacts, tasks=tasks, open_tasks=open_tasks, visits=visits, attr_options=ATTR_OPTIONS_026,
            customer_display_attr_1=display1, customer_display_attr_2=display2),
    )


@router.post('/customers/{customer_id}/payment-column-widths')
def payment_column_widths_v027(request: Request, customer_id: int, csrf: str = Form(...), attr: int = Form(...), number: int = Form(...), account: int = Form(...), amount: int = Form(...)):
    check_csrf(request, csrf)
    values = {'attr': attr, 'number': number, 'account': account, 'amount': amount}
    for key, value in values.items():
        lo, hi = COL_LIMITS[key]
        if value < lo or value > hi:
            raise HTTPException(400, f'{key}列宽超出允许范围')
    with db() as conn:
        customer_or_404(conn, customer_id)
        _meta_set(conn, f'payment_col_widths:{customer_id}', json.dumps(values, ensure_ascii=False))
    return JSONResponse({'ok': True, 'widths': values})


@router.post('/customers/{customer_id}/promotions-v027')
def add_promotion_by_number_v027(request: Request, customer_id: int, csrf: str = Form(...), number: str = Form(...), name: str = Form(...), expiry_date: str = Form(''), slot_number: str = Form(''), notes: str = Form('')):
    check_csrf(request, csrf)
    number = number.strip()
    if not number:
        raise HTTPException(400, '必须填写号码')
    expiry_iso = expiry_date
    with db(immediate=True) as conn:
        customer_or_404(conn, customer_id)
        candidates = conn.execute(
            '''SELECT * FROM services WHERE customer_id=? AND TRIM(number)=?
               ORDER BY CASE WHEN COALESCE(sort_order,0)>0 THEN sort_order ELSE 100000000+id END,id''',
            (customer_id, number),
        ).fetchall()
        service = next((s for s in candidates if service_active_in_period(s, current_period())), None)
        if not service:
            raise HTTPException(400, '没有找到这个客户下对应的在用号码，请先在“业务”中添加或核对号码')
        slot = available_slot(conn, service['id'], slot_number)
        conn.execute(
            '''INSERT INTO promotions(slot_number,service_id,name,start_date,expiry_date,remind_days,status,renewed_at,notes,created_at)
               VALUES(?,?,?,?,?,60,'active','',?,?)''',
            (slot, service['id'], name.strip(), '', expiry_iso, notes.strip(), now_iso()),
        )
    return RedirectResponse(f'/customers/{customer_id}?tab=promotions', 303)


@router.post('/promotions/{promotion_id}/expiry-v027')
def update_promotion_expiry_v027(request: Request, promotion_id: int, csrf: str = Form(...), expiry_date: str = Form('')):
    check_csrf(request, csrf)
    expiry_iso = expiry_date
    with db() as conn:
        old = promotion_or_404(conn, promotion_id)
        conn.execute("UPDATE promotions SET expiry_date=?,status='active',renewed_at=? WHERE id=?", (expiry_iso, now_iso(), promotion_id))
        cid = old['customer_id']
    return RedirectResponse(f'/customers/{cid}?tab=promotions', 303)


@router.post('/customers/{customer_id}/promotions/reorder-v027')
def reorder_promotions_v027(request: Request, customer_id: int, csrf: str = Form(...), group_key: str = Form(...), promotion_ids: str = Form(...)):
    check_csrf(request, csrf)
    try:
        ids = [int(x) for x in promotion_ids.split(',') if x.strip()]
    except ValueError:
        raise HTTPException(400, '排序数据无效')
    if not ids:
        return JSONResponse({'ok': True})
    with db() as conn:
        customer_or_404(conn, customer_id)
        placeholders = ','.join('?' for _ in ids)
        rows = conn.execute(
            f'''SELECT p.id,p.service_id,s.number,s.customer_id FROM promotions p JOIN services s ON s.id=p.service_id
                WHERE p.id IN ({placeholders})''', ids
        ).fetchall()
        if len(rows) != len(ids) or any(r['customer_id'] != customer_id for r in rows):
            raise HTTPException(400, '优惠排序数据不属于当前客户')
        for r in rows:
            key = (r['number'] or '').strip() or f"__service_{r['service_id']}"
            if key != group_key:
                raise HTTPException(400, '只能调整同一号码下优惠的顺序')
        _meta_set(conn, f'promo_order:{customer_id}:{group_key}', json.dumps(ids))
    return JSONResponse({'ok': True})

