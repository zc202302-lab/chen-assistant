from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from . import config
from .db import db, now_iso
from .payment_v02 import current_period, payment_snapshot
from .v025_routes import customer_or_404, service_or_404, promotion_or_404, _payment_run
from .v026_routes import check_csrf, parse_date_text, date_text
from .v027_routes import _column_widths
from .v028_routes import (
    _template,
    _display_pair,
    _custom_map,
    _display_attr,
    _promo_columns,
    _business_payload,
    _attribute_options,
)

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')
APP_VERSION = '0.2.9'


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


@router.get('/health')
def health_v029():
    return {'ok': True, 'version': APP_VERSION}


@router.get('/customers/{customer_id}', response_class=HTMLResponse)
def customer_workspace_v029(request: Request, customer_id: int, tab: str = 'payment'):
    period = current_period()
    tabs = {'payment', 'services', 'promotions', 'contacts', 'tasks', 'visits'}
    active_tab = tab if tab in tabs else 'payment'
    with db() as conn:
        customer = customer_or_404(conn, customer_id)
        template = _template(conn)
        display1, display2 = _display_pair(conn, customer, template)
        col_widths = _column_widths(conn, customer_id)

        invoice_groups = conn.execute('SELECT * FROM invoice_groups WHERE customer_id=? ORDER BY id', (customer_id,)).fetchall()
        services = conn.execute(
            '''SELECT s.*,g.name invoice_group_name FROM services s
               LEFT JOIN invoice_groups g ON g.id=s.invoice_group_id
               WHERE s.customer_id=?
               ORDER BY CASE WHEN COALESCE(s.sort_order,0)>0 THEN s.sort_order ELSE 100000000+s.id END,s.id''',
            (customer_id,),
        ).fetchall()
        custom = _custom_map(conn, [s['id'] for s in services])

        payment_items, payment_stats = payment_snapshot(conn, customer_id, period)
        enriched_payment = []
        for raw in payment_items:
            item = dict(raw)
            s = item['row']
            full = next((x for x in services if x['id'] == s['id']), s)
            item['display_value_1'] = _display_attr(full, display1, custom[s['id']]) if display1 else '—'
            item['display_value_2'] = _display_attr(full, display2, custom[s['id']]) if display2 else '—'
            enriched_payment.append(item)
        payment_run = _payment_run(conn, customer_id, period, payment_stats)

        promo_rows = conn.execute(
            '''SELECT p.*,s.service_type,s.holder_name,s.number,s.account,s.customer_id
               FROM promotions p JOIN services s ON s.id=p.service_id
               WHERE s.customer_id=? AND COALESCE(p.status,'active')='active'
               ORDER BY p.expiry_date,p.id''',
            (customer_id,),
        ).fetchall()
        promo_columns = _promo_columns(conn, customer_id, promo_rows)
        promo_attention = sum(len(g['items']) for groups in promo_columns.values() for g in groups)

        business_rows, _ = _business_payload(conn, customer_id, template, services, promo_rows)
        for item in business_rows:
            # 业务列表只负责快速扫视。严格采用编辑器中的属性顺序，只展示前5项；
            # 完整属性仍全部保留在“编辑业务”中。
            attrs = item.get('attributes') or []
            item['preview_attributes'] = attrs[:5]

        service_types = []
        seen_types = set()
        for item in business_rows:
            typ = (item['row']['service_type'] or '未分类').strip() or '未分类'
            if typ not in seen_types:
                seen_types.add(typ)
                service_types.append(typ)

        contacts = conn.execute('SELECT * FROM contacts WHERE customer_id=? ORDER BY id', (customer_id,)).fetchall()
        tasks = conn.execute('SELECT * FROM tasks WHERE customer_id=? ORDER BY done,remind_date,id DESC', (customer_id,)).fetchall()
        open_tasks = [t for t in tasks if not t['done']]
        visits = conn.execute('SELECT * FROM visits WHERE customer_id=? ORDER BY visit_date DESC,id DESC', (customer_id,)).fetchall()

    return templates.TemplateResponse(
        'customer_workspace_v029.html',
        ctx(
            request,
            customer=customer,
            active_tab=active_tab,
            payment_period=period,
            payment_items=enriched_payment,
            payment_stats=payment_stats,
            payment_run=payment_run,
            col_widths=col_widths,
            invoice_groups=invoice_groups,
            business_rows=business_rows,
            service_types=service_types,
            promo_columns=promo_columns,
            promo_attention=promo_attention,
            contacts=contacts,
            tasks=tasks,
            open_tasks=open_tasks,
            visits=visits,
            attr_template=template,
            attr_options=_attribute_options(template),
            customer_display_attr_1=display1,
            customer_display_attr_2=display2,
        ),
    )


@router.get('/services/{service_id}/promotions-editor-v029')
def service_promotions_editor_v029(service_id: int):
    with db() as conn:
        service = service_or_404(conn, service_id)
        rows = conn.execute(
            '''SELECT id,name,expiry_date,notes,status FROM promotions
               WHERE service_id=? AND COALESCE(status,'active')='active'
               ORDER BY expiry_date,id''',
            (service_id,),
        ).fetchall()
    return JSONResponse({
        'ok': True,
        'service_id': service_id,
        'number': service['number'] or '',
        'promotions': [
            {
                'id': row['id'],
                'name': row['name'] or '',
                'expiry_date': date_text(row['expiry_date']),
                'notes': row['notes'] or '',
            }
            for row in rows
        ],
    })


@router.post('/services/{service_id}/promotions-editor-v029')
def save_service_promotion_v029(
    request: Request,
    service_id: int,
    csrf: str = Form(...),
    promotion_id: str = Form(''),
    name: str = Form(...),
    expiry_date: str = Form(...),
    notes: str = Form(''),
):
    check_csrf(request, csrf)
    clean_name = name.strip()[:200]
    if not clean_name:
        raise HTTPException(400, '优惠名称不能为空')
    expiry_iso = parse_date_text(expiry_date, required=True, field='优惠到期日期')
    clean_notes = notes.strip()[:2000]
    with db() as conn:
        service = service_or_404(conn, service_id)
        if promotion_id.strip():
            try:
                pid = int(promotion_id)
            except ValueError:
                raise HTTPException(400, '优惠编号无效')
            row = promotion_or_404(conn, pid)
            if row['service_id'] != service_id:
                raise HTTPException(400, '优惠不属于当前业务')
            conn.execute(
                "UPDATE promotions SET name=?,expiry_date=?,notes=?,status='active',renewed_at=? WHERE id=?",
                (clean_name, expiry_iso, clean_notes, now_iso(), pid),
            )
        else:
            cur = conn.execute(
                '''INSERT INTO promotions(service_id,name,start_date,expiry_date,remind_days,status,notes,created_at)
                   VALUES(?,?,?,?,?,?,?,?)''',
                (service_id, clean_name, '', expiry_iso, 60, 'active', clean_notes, now_iso()),
            )
            pid = int(cur.lastrowid)
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), service['customer_id']))
    return JSONResponse({'ok': True, 'id': pid, 'name': clean_name, 'expiry_date': date_text(expiry_iso), 'notes': clean_notes})


@router.post('/promotions/{promotion_id}/close-editor-v029')
def close_service_promotion_v029(request: Request, promotion_id: int, csrf: str = Form(...)):
    check_csrf(request, csrf)
    with db() as conn:
        row = promotion_or_404(conn, promotion_id)
        conn.execute("UPDATE promotions SET status='closed' WHERE id=?", (promotion_id,))
        service = service_or_404(conn, row['service_id'])
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), service['customer_id']))
    return JSONResponse({'ok': True})