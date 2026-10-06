from __future__ import annotations

from datetime import date
import json

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from .templating import Jinja2Templates

from . import config
from .db import db, now_iso
from .payment_v02 import current_period, payment_snapshot, format_fee
from .v025_routes import customer_or_404, _payment_run
from .v026_routes import check_csrf
from .v027_routes import _meta_get, _meta_set
from .v028_routes import (
    _template,
    _custom_map,
    _service_attrs,
    _promo_columns,
    _business_payload,
)

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')
APP_VERSION = '0.2.11'
PAYMENT_AMOUNT_KEY = 'payment_amount'
PAYMENT_COLUMNS_PREFIX = 'payment_columns_v0211:'
PAYMENT_WIDTHS_PREFIX = 'payment_widths_v0211:'


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


def _payment_catalog(template):
    result = {
        item['key']: {
            'key': item['key'],
            'label': item['label'],
            'kind': item.get('kind', 'text'),
            'source': 'business',
        }
        for item in template
    }
    result[PAYMENT_AMOUNT_KEY] = {
        'key': PAYMENT_AMOUNT_KEY,
        'label': '缴费金额',
        'kind': 'payment_amount',
        'source': 'payment',
    }
    return result


def _payment_columns(conn, customer_id: int, template):
    catalog = _payment_catalog(template)
    raw = _meta_get(conn, f'{PAYMENT_COLUMNS_PREFIX}{customer_id}', '')
    keys = []
    if raw:
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, list):
                keys = [str(x) for x in loaded]
        except Exception:
            keys = []
    if not keys:
        keys = [item['key'] for item in template[:4]]
        keys.append(PAYMENT_AMOUNT_KEY)

    normalized = []
    seen = set()
    for key in keys:
        if key in catalog and key not in seen:
            normalized.append(key)
            seen.add(key)
    if PAYMENT_AMOUNT_KEY not in seen:
        normalized.append(PAYMENT_AMOUNT_KEY)
    if not normalized:
        normalized = [PAYMENT_AMOUNT_KEY]

    if normalized != keys:
        _meta_set(conn, f'{PAYMENT_COLUMNS_PREFIX}{customer_id}', json.dumps(normalized, ensure_ascii=False))
    return [catalog[key] for key in normalized]


def _default_width(column):
    key = column['key']
    if key == PAYMENT_AMOUNT_KEY:
        return 190
    if key == 'number':
        return 250
    if key == 'account':
        return 290
    if column.get('kind') == 'textarea':
        return 280
    return 180


def _payment_widths(conn, customer_id: int, columns):
    raw = _meta_get(conn, f'{PAYMENT_WIDTHS_PREFIX}{customer_id}', '')
    saved = {}
    if raw:
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                saved = loaded
        except Exception:
            saved = {}
    result = {}
    for column in columns:
        key = column['key']
        try:
            width = int(saved.get(key, _default_width(column)))
        except Exception:
            width = _default_width(column)
        result[key] = max(110, min(900, width))
    return result


def _payment_cells(service, custom_values, template, columns, payment, delta):
    attrs = {item['key']: item for item in _service_attrs(service, template, custom_values)}
    result = []
    for column in columns:
        key = column['key']
        if key == PAYMENT_AMOUNT_KEY:
            result.append({
                'key': key,
                'label': '缴费金额',
                'kind': 'payment_amount',
                'value': format_fee(float(payment['amount'] or 0)),
                'raw': format_fee(float(payment['amount'] or 0)),
                'delta': delta,
            })
        else:
            item = attrs.get(key) or {
                'key': key,
                'label': column['label'],
                'kind': column.get('kind', 'text'),
                'value': '—',
                'raw': '',
            }
            result.append(item)
    return result


@router.get('/health')
def health_v0211():
    return {'ok': True, 'version': APP_VERSION}


@router.get('/customers/{customer_id}', response_class=HTMLResponse)
def customer_workspace_v0211(request: Request, customer_id: int, tab: str = 'payment'):
    period = current_period()
    tabs = {'payment', 'services', 'promotions', 'contacts', 'tasks', 'visits'}
    active_tab = tab if tab in tabs else 'payment'
    with db() as conn:
        customer = customer_or_404(conn, customer_id)
        template = _template(conn)
        payment_columns = _payment_columns(conn, customer_id, template)
        payment_widths = _payment_widths(conn, customer_id, payment_columns)

        invoice_groups = conn.execute('SELECT * FROM invoice_groups WHERE customer_id=? ORDER BY id', (customer_id,)).fetchall()
        services = conn.execute(
            '''SELECT s.*,g.name invoice_group_name FROM services s
               LEFT JOIN invoice_groups g ON g.id=s.invoice_group_id
               WHERE s.customer_id=?
               ORDER BY CASE WHEN COALESCE(s.sort_order,0)>0 THEN s.sort_order ELSE 100000000+s.id END,s.id''',
            (customer_id,),
        ).fetchall()
        services_by_id = {s['id']: s for s in services}
        custom = _custom_map(conn, [s['id'] for s in services])

        payment_items, payment_stats = payment_snapshot(conn, customer_id, period)
        enriched_payment = []
        for raw in payment_items:
            item = dict(raw)
            service = services_by_id.get(item['row']['id'], item['row'])
            item['row'] = service
            item['payment_cells'] = _payment_cells(
                service,
                custom[service['id']],
                template,
                payment_columns,
                item['payment'],
                item.get('delta'),
            )
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
            item['preview_attributes'] = (item.get('attributes') or [])[:5]

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

    payment_options = [
        {'key': item['key'], 'label': item['label'], 'kind': item.get('kind', 'text')}
        for item in template
    ] + [{'key': PAYMENT_AMOUNT_KEY, 'label': '缴费金额', 'kind': 'payment_amount'}]
    payment_keys = [item['key'] for item in payment_columns]
    payment_grid_widths = ' '.join(f"{payment_widths[key]}px" for key in payment_keys)

    return templates.TemplateResponse(
        'customer_workspace_v0211.html',
        ctx(
            request,
            customer=customer,
            active_tab=active_tab,
            payment_period=period,
            payment_items=enriched_payment,
            payment_stats=payment_stats,
            payment_run=payment_run,
            payment_columns=payment_columns,
            payment_column_keys=payment_keys,
            payment_column_options=payment_options,
            payment_column_options_json=json.dumps(payment_options, ensure_ascii=False),
            payment_grid_widths=payment_grid_widths,
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
        ),
    )


@router.post('/customers/{customer_id}/payment-columns-v0211')
def save_payment_columns_v0211(
    request: Request,
    customer_id: int,
    csrf: str = Form(...),
    columns_json: str = Form(...),
):
    check_csrf(request, csrf)
    try:
        requested = json.loads(columns_json)
    except Exception:
        raise HTTPException(400, '缴费属性设置无效')
    if not isinstance(requested, list) or len(requested) > 40:
        raise HTTPException(400, '缴费属性设置无效')
    with db() as conn:
        customer_or_404(conn, customer_id)
        template = _template(conn)
        catalog = _payment_catalog(template)
        keys = []
        seen = set()
        for raw in requested:
            key = str(raw).strip()
            if key not in catalog:
                raise HTTPException(400, '包含已经不存在的业务属性')
            if key in seen:
                raise HTTPException(400, '同一个缴费属性不能重复')
            seen.add(key)
            keys.append(key)
        if PAYMENT_AMOUNT_KEY not in seen:
            keys.append(PAYMENT_AMOUNT_KEY)
        if not keys:
            keys = [PAYMENT_AMOUNT_KEY]
        _meta_set(conn, f'{PAYMENT_COLUMNS_PREFIX}{customer_id}', json.dumps(keys, ensure_ascii=False))
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), customer_id))
        columns = [catalog[key] for key in keys]
    return JSONResponse({'ok': True, 'columns': columns})


@router.post('/customers/{customer_id}/payment-column-widths-v0211')
def save_payment_widths_v0211(
    request: Request,
    customer_id: int,
    csrf: str = Form(...),
    widths_json: str = Form(...),
):
    check_csrf(request, csrf)
    try:
        requested = json.loads(widths_json)
    except Exception:
        raise HTTPException(400, '列宽数据无效')
    if not isinstance(requested, dict):
        raise HTTPException(400, '列宽数据无效')
    with db() as conn:
        customer_or_404(conn, customer_id)
        template = _template(conn)
        columns = _payment_columns(conn, customer_id, template)
        valid = {item['key'] for item in columns}
        widths = {}
        for column in columns:
            key = column['key']
            try:
                width = int(requested.get(key, _default_width(column)))
            except Exception:
                raise HTTPException(400, '列宽数据无效')
            if width < 110 or width > 900:
                raise HTTPException(400, '列宽超出允许范围')
            widths[key] = width
        extra = {str(k) for k in requested} - valid
        if extra:
            raise HTTPException(400, '列宽包含未知属性')
        _meta_set(conn, f'{PAYMENT_WIDTHS_PREFIX}{customer_id}', json.dumps(widths, ensure_ascii=False))
    return JSONResponse({'ok': True, 'widths': widths})


@router.post('/customers/{customer_id}/services/reorder')
def reorder_services_v0211(
    request: Request,
    customer_id: int,
    csrf: str = Form(...),
    service_ids: str = Form(...),
):
    check_csrf(request, csrf)
    try:
        ids = [int(x) for x in service_ids.split(',') if x.strip()]
    except ValueError:
        raise HTTPException(400, '排序数据无效')
    if not ids or len(ids) != len(set(ids)):
        raise HTTPException(400, '排序数据无效')

    with db() as conn:
        customer_or_404(conn, customer_id)
        rows = conn.execute(
            '''SELECT id FROM services WHERE customer_id=?
               ORDER BY CASE WHEN COALESCE(sort_order,0)>0 THEN sort_order ELSE 100000000+id END,id''',
            (customer_id,),
        ).fetchall()
        current = [int(row['id']) for row in rows]
        current_set = set(current)
        if any(sid not in current_set for sid in ids):
            raise HTTPException(400, '排序包含其他客户业务')

        subset = set(ids)
        positions = [idx for idx, sid in enumerate(current) if sid in subset]
        if len(positions) != len(ids):
            raise HTTPException(400, '排序数据无效')
        reordered = list(current)
        for idx, sid in zip(positions, ids):
            reordered[idx] = sid

        for pos, sid in enumerate(reordered, 1):
            conn.execute('UPDATE services SET sort_order=? WHERE id=?', (pos * 10, sid))
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), customer_id))

    return JSONResponse({'ok': True, 'order': reordered})

