from __future__ import annotations

from collections import defaultdict
import json

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import JSONResponse

from .db import db, now_iso
from .payment_v02 import current_period, effective_payment_rule
from .v025_routes import customer_or_404, service_or_404
from .v026_routes import check_csrf, date_text, promotion_bucket
from .v027_routes import _meta_get, _meta_set
from .v028_routes import _template, _custom_map, _service_attrs
from . import v0212_routes as core

from .promotions import expiry_text

router = APIRouter()

SYSTEM_PAYMENT_STATE_KEY = '__payment_state__'
BUSINESS_DISPLAY_ORDER_KEY = 'business_display_order_v0212h2'


def _customer_display_key(customer_id: int) -> str:
    return f'{BUSINESS_DISPLAY_ORDER_KEY}:{int(customer_id)}'


def _normalize_loaded(template, loaded):
    valid = {str(x['key']) for x in template}
    valid.add(SYSTEM_PAYMENT_STATE_KEY)
    ordered = []
    seen = set()
    for raw_key in loaded if isinstance(loaded, list) else []:
        key = str(raw_key)
        if key in valid and key not in seen:
            ordered.append(key)
            seen.add(key)
    return ordered


def _legacy_default_order(conn, template):
    """Read old global settings only as a one-time migration source."""
    valid = [str(x['key']) for x in template]
    raw = _meta_get(conn, BUSINESS_DISPLAY_ORDER_KEY, '')
    if raw:
        try:
            loaded = json.loads(raw)
        except Exception:
            loaded = []
        normalized = _normalize_loaded(template, loaded)
        if normalized:
            return normalized

    legacy_raw = _meta_get(conn, core.BUSINESS_VISIBLE_KEY, '')
    try:
        legacy = json.loads(legacy_raw) if legacy_raw else valid[:5]
    except Exception:
        legacy = valid[:5]
    legacy = [str(x) for x in legacy] if isinstance(legacy, list) else valid[:5]
    return [SYSTEM_PAYMENT_STATE_KEY] + [x for x in legacy if x in set(valid)]


def _ordered_keys(conn, template, customer_id: int | None = None):
    """Business visibility/order is per customer; attribute definitions stay global."""
    if customer_id is None:
        return _legacy_default_order(conn, template)

    key = _customer_display_key(customer_id)
    raw = _meta_get(conn, key, '')
    if not raw:
        ordered = _legacy_default_order(conn, template)
        _meta_set(conn, key, json.dumps(ordered, ensure_ascii=False))
        return ordered

    try:
        loaded = json.loads(raw)
    except Exception:
        loaded = []
    ordered = _normalize_loaded(template, loaded)
    if ordered != loaded:
        _meta_set(conn, key, json.dumps(ordered, ensure_ascii=False))
    return ordered


def _normalize_requested(template, requested):
    valid = {str(x['key']) for x in template}
    valid.add(SYSTEM_PAYMENT_STATE_KEY)
    ordered = []
    seen = set()
    for raw in requested:
        key = str(raw)
        if key not in valid or key in seen:
            continue
        ordered.append(key)
        seen.add(key)
    return ordered


def _business_payload_ordered_base(conn, customer_id: int, template, services, promo_rows, visible_keys, runtime):
    custom = _custom_map(conn, [s['id'] for s in services])
    promo_by_service = defaultdict(list)
    for promo in promo_rows:
        promo_by_service[promo['service_id']].append(promo)

    rows = []
    period = current_period()
    ordered_keys = list(visible_keys or [])
    for service in services:
        promos = promo_by_service.get(service['id'], [])
        buckets = [promotion_bucket(p['expiry_date'], p['status']) for p in promos]
        expired_n = buckets.count('expired')
        soon_n = buckets.count('soon')
        if expired_n:
            promo_filter, promo_label = 'expired', f'已到期 {expired_n}'
        elif soon_n:
            promo_filter, promo_label = 'soon', f'即将到期 {soon_n}'
        elif promos:
            promo_filter, promo_label = 'normal', f'优惠 {len(promos)}'
        else:
            promo_filter, promo_label = 'none', '无优惠'
        nearest = min(promos, key=lambda p: p['expiry_date'] or '9999-12-31') if promos else None

        attrs = _service_attrs(service, template, custom[service['id']])
        by_key = {a['key']: a for a in attrs}
        state = core._schedule_state(service, runtime[service['id']], period)
        preview = []
        for key in ordered_keys:
            if key == SYSTEM_PAYMENT_STATE_KEY:
                preview.append({
                    'key': SYSTEM_PAYMENT_STATE_KEY,
                    'label': '缴费状态',
                    'kind': 'derived_state',
                    'value': state,
                    'raw': state,
                })
            elif key in by_key:
                preview.append(by_key[key])

        rows.append({
            'row': service,
            'attributes': attrs,
            'preview_attributes': preview,
            'rule': effective_payment_rule(conn, service['id'], period, service),
            'due': core._service_due(service, runtime[service['id']], period),
            'promo_filter': promo_filter,
            'promo_label': promo_label,
            'promo_nearest': expiry_text(nearest['expiry_date']) if nearest else '',
        })
    return rows


def _customer_rows_payload(conn, customer_id: int, template, ordered=None):
    if ordered is None:
        ordered = _ordered_keys(conn, template, customer_id)
    services = conn.execute(
        '''SELECT s.*,g.name invoice_group_name FROM services s
           LEFT JOIN invoice_groups g ON g.id=s.invoice_group_id
           WHERE s.customer_id=?
           ORDER BY CASE WHEN COALESCE(s.sort_order,0)>0 THEN s.sort_order ELSE 100000000+s.id END,s.id''',
        (customer_id,),
    ).fetchall()
    runtime = core._runtime_map(conn, [s['id'] for s in services])
    promo_rows = conn.execute(
        '''SELECT p.*,s.service_type,s.holder_name,s.number,s.account,s.customer_id
           FROM promotions p JOIN services s ON s.id=p.service_id
           WHERE s.customer_id=? AND COALESCE(p.status,'active')='active'
           ORDER BY p.expiry_date,p.id''',
        (customer_id,),
    ).fetchall()
    business_rows = _business_payload_ordered(
        conn, customer_id, template, services, promo_rows, ordered, runtime
    )
    return {
        str(item['row']['id']): {
            'preview_attributes': item['preview_attributes'],
            'due': bool(item['due']),
        }
        for item in business_rows
    }


# Existing customer workspace resolves these names at request time.




@router.get('/customers/{customer_id}/business-columns-v0212')
def get_business_columns_v0212(customer_id: int):
    with db() as conn:
        customer_or_404(conn, customer_id)
        template = _template(conn)
        ordered = _ordered_keys(conn, template, customer_id)
        rows = _customer_rows_payload(conn, customer_id, template, ordered)
    options = [
        {'key': SYSTEM_PAYMENT_STATE_KEY, 'label': '缴费状态', 'kind': 'derived_state'},
        *[
            {'key': str(item['key']), 'label': item['label'], 'kind': item.get('kind', 'text')}
            for item in template
        ],
    ]
    return JSONResponse({'ok': True, 'columns': ordered, 'options': options, 'rows': rows})


@router.post('/customers/{customer_id}/business-columns-v0212')
def save_business_columns_v0212(
    request: Request,
    customer_id: int,
    csrf: str = Form(...),
    columns_json: str = Form('[]'),
):
    check_csrf(request, csrf)
    try:
        requested = json.loads(columns_json)
    except Exception:
        raise HTTPException(400, '业务显示属性设置无效')
    if not isinstance(requested, list) or len(requested) > 41:
        raise HTTPException(400, '业务显示属性设置无效')

    with db() as conn:
        customer_or_404(conn, customer_id)
        template = _template(conn)
        ordered = _normalize_requested(template, requested)
        _meta_set(conn, _customer_display_key(customer_id), json.dumps(ordered, ensure_ascii=False))
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), customer_id))
        rows = _customer_rows_payload(conn, customer_id, template, ordered)
    return JSONResponse({'ok': True, 'columns': ordered, 'rows': rows})


@router.post('/services/{service_id}/runtime-v0212')
def save_service_runtime_display_order_v0212(
    request: Request,
    service_id: int,
    csrf: str = Form(...),
    status: str = Form(...),
    business_visible_json: str = Form('[]'),
):
    check_csrf(request, csrf)
    if status not in {'active', 'inactive'}:
        raise HTTPException(400, '业务状态无效')
    try:
        requested = json.loads(business_visible_json)
    except Exception:
        raise HTTPException(400, '业务显示顺序设置无效')
    if not isinstance(requested, list) or len(requested) > 41:
        raise HTTPException(400, '业务显示顺序设置无效')

    with db() as conn:
        service = service_or_404(conn, service_id)
        customer_id = int(service['customer_id'])
        template = _template(conn)
        ordered = _normalize_requested(template, requested)
        _meta_set(conn, _customer_display_key(customer_id), json.dumps(ordered, ensure_ascii=False))
        core._save_runtime(conn, service_id, status=status)
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), customer_id))
        result_rows = _customer_rows_payload(conn, customer_id, template, ordered)
        runtime = core._runtime_map(conn, [service_id])
        schedule_state = core._schedule_state(service, runtime[int(service_id)], current_period())

    return JSONResponse({
        'ok': True,
        'status': status,
        'business_visible_keys': ordered,
        'schedule_state': schedule_state,
        'rows': result_rows,
    })


# v1.4.3: customer-level active/inactive state. This is deliberately separate
# from per-service runtime state and from the older payment_enabled preference.
# Disabling a customer suppresses every payment reminder without mutating any
# service status, amount, review state, schedule, or historical payment run.
CUSTOMER_RUNTIME_TABLE = 'customer_runtime_v143'


def _ensure_customer_runtime_v143(conn):
    conn.execute(
        f'''CREATE TABLE IF NOT EXISTS {CUSTOMER_RUNTIME_TABLE} (
               customer_id INTEGER PRIMARY KEY REFERENCES customers(id) ON DELETE CASCADE,
               status TEXT NOT NULL DEFAULT 'active',
               updated_at TEXT NOT NULL DEFAULT ''
           )'''
    )


def _customer_status_v143(conn, customer_id: int) -> str:
    _ensure_customer_runtime_v143(conn)
    row = conn.execute(
        f'SELECT status FROM {CUSTOMER_RUNTIME_TABLE} WHERE customer_id=?',
        (int(customer_id),),
    ).fetchone()
    status = (row['status'] or 'active').strip() if row else 'active'
    return status if status in {'active', 'inactive'} else 'active'


def _customer_active_v143(conn, customer_id: int) -> bool:
    return _customer_status_v143(conn, customer_id) == 'active'


def _save_customer_status_v143(conn, customer_id: int, status: str):
    if status not in {'active', 'inactive'}:
        raise HTTPException(400, '客户状态无效')
    _ensure_customer_runtime_v143(conn)
    conn.execute(
        f'''INSERT INTO {CUSTOMER_RUNTIME_TABLE}(customer_id,status,updated_at)
            VALUES(?,?,?)
            ON CONFLICT(customer_id) DO UPDATE SET
              status=excluded.status,updated_at=excluded.updated_at''',
        (int(customer_id), status, now_iso()),
    )
    conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), int(customer_id)))


_BASE_PAYMENT_SNAPSHOT_V143 = core._payment_snapshot_base_v0212
_BASE_BUSINESS_PAYLOAD_V143 = _business_payload_ordered_base


def _payment_snapshot_customer_gate_v143(conn, customer_id: int, period: str | None = None):
    if not _customer_active_v143(conn, customer_id):
        return [], {
            'due_count': 0,
            'required': 0,
            'pending': 0,
            'changed': 0,
            'zero': 0,
            'total': 0.0,
            'txt_ready': False,
            'customer_active': False,
        }
    items, stats = _BASE_PAYMENT_SNAPSHOT_V143(conn, customer_id, period)
    stats = dict(stats)
    stats['customer_active'] = True
    return items, stats


def _business_payload_customer_gate_v143(conn, customer_id: int, template, services, promo_rows, visible_keys, runtime):
    rows = _BASE_BUSINESS_PAYLOAD_V143(
        conn, customer_id, template, services, promo_rows, visible_keys, runtime
    )
    if _customer_active_v143(conn, customer_id):
        return rows
    for item in rows:
        item['due'] = False
        for attr in item.get('preview_attributes', []):
            if attr.get('key') == SYSTEM_PAYMENT_STATE_KEY:
                attr['value'] = '客户停用'
                attr['raw'] = '客户停用'
    return rows


# Rebind the names looked up dynamically by the mature workspace. The v1.4.1
# row-review patch imports after this module, so its snapshot wrapper inherits
# this customer-level gate instead of bypassing it.





def _business_payload_ordered(conn, customer_id, template, services, promo_rows, visible_keys, runtime):
    return _business_payload_customer_gate_v143(conn, customer_id, template, services, promo_rows, visible_keys, runtime)


@router.get('/customers/{customer_id}/runtime-v143')
def get_customer_runtime_v143(customer_id: int):
    with db() as conn:
        customer_or_404(conn, customer_id)
        status = _customer_status_v143(conn, customer_id)
    return JSONResponse({
        'ok': True,
        'customer_id': int(customer_id),
        'status': status,
        'payment_reminders_enabled': status == 'active',
    })


@router.post('/customers/{customer_id}/runtime-v143')
def save_customer_runtime_v143(
    request: Request,
    customer_id: int,
    csrf: str = Form(...),
    status: str = Form(...),
):
    check_csrf(request, csrf)
    if status not in {'active', 'inactive'}:
        raise HTTPException(400, '客户状态无效')
    with db() as conn:
        customer_or_404(conn, customer_id)
        _save_customer_status_v143(conn, customer_id, status)
        template = _template(conn)
        rows = _customer_rows_payload(conn, customer_id, template)
    return JSONResponse({
        'ok': True,
        'customer_id': int(customer_id),
        'status': status,
        'payment_reminders_enabled': status == 'active',
        'rows': rows,
    })

