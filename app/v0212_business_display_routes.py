from __future__ import annotations

from collections import defaultdict
import json

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import JSONResponse

from .db import db, now_iso
from .payment_v02 import current_period, effective_payment_rule
from .v025_routes import service_or_404
from .v026_routes import check_csrf, date_text, promotion_bucket
from .v027_routes import _meta_get, _meta_set
from .v028_routes import _template, _custom_map, _service_attrs
from . import v0212_routes as core

router = APIRouter()

SYSTEM_PAYMENT_STATE_KEY = '__payment_state__'
BUSINESS_DISPLAY_ORDER_KEY = 'business_display_order_v0212h2'


def _ordered_keys(conn, template):
    valid = [str(x['key']) for x in template]
    raw = _meta_get(conn, BUSINESS_DISPLAY_ORDER_KEY, '')
    if not raw:
        # Migrate once from the previous checkbox-based setting. Payment state used to be
        # forcibly displayed, so preserve it as an ordinary ordered attribute on migration.
        legacy_raw = _meta_get(conn, core.BUSINESS_VISIBLE_KEY, '')
        try:
            legacy = json.loads(legacy_raw) if legacy_raw else valid[:5]
        except Exception:
            legacy = valid[:5]
        legacy = [str(x) for x in legacy] if isinstance(legacy, list) else valid[:5]
        ordered = [SYSTEM_PAYMENT_STATE_KEY] + [x for x in legacy if x in valid]
        _meta_set(conn, BUSINESS_DISPLAY_ORDER_KEY, json.dumps(ordered, ensure_ascii=False))
        return ordered

    try:
        loaded = json.loads(raw)
    except Exception:
        loaded = []
    if not isinstance(loaded, list):
        loaded = []

    allowed = set(valid)
    allowed.add(SYSTEM_PAYMENT_STATE_KEY)
    ordered = []
    seen = set()
    for raw_key in loaded:
        key = str(raw_key)
        if key in allowed and key not in seen:
            ordered.append(key)
            seen.add(key)
    if ordered != loaded:
        _meta_set(conn, BUSINESS_DISPLAY_ORDER_KEY, json.dumps(ordered, ensure_ascii=False))
    return ordered


def _business_payload_ordered(conn, customer_id: int, template, services, promo_rows, visible_keys, runtime):
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
            'promo_nearest': date_text(nearest['expiry_date']) if nearest else '',
        })
    return rows


# The existing customer workspace resolves these functions at request time, so replacing
# them here upgrades the current page without duplicating the whole customer route.
core._visible_keys = _ordered_keys
core._business_payload_v0212 = _business_payload_ordered


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
        template = _template(conn)
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

        _meta_set(conn, BUSINESS_DISPLAY_ORDER_KEY, json.dumps(ordered, ensure_ascii=False))
        core._save_runtime(conn, service_id, status=status)
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), service['customer_id']))

        services = conn.execute(
            '''SELECT s.*,g.name invoice_group_name FROM services s
               LEFT JOIN invoice_groups g ON g.id=s.invoice_group_id
               WHERE s.customer_id=?
               ORDER BY CASE WHEN COALESCE(s.sort_order,0)>0 THEN s.sort_order ELSE 100000000+s.id END,s.id''',
            (service['customer_id'],),
        ).fetchall()
        runtime = core._runtime_map(conn, [s['id'] for s in services])
        promo_rows = conn.execute(
            '''SELECT p.*,s.service_type,s.holder_name,s.number,s.account,s.customer_id
               FROM promotions p JOIN services s ON s.id=p.service_id
               WHERE s.customer_id=? AND COALESCE(p.status,'active')='active'
               ORDER BY p.expiry_date,p.id''',
            (service['customer_id'],),
        ).fetchall()
        business_rows = _business_payload_ordered(
            conn, int(service['customer_id']), template, services, promo_rows, ordered, runtime
        )
        result_rows = {
            str(item['row']['id']): {
                'preview_attributes': item['preview_attributes'],
                'due': bool(item['due']),
            }
            for item in business_rows
        }
        current_runtime = runtime[int(service_id)]
        schedule_state = core._schedule_state(service, current_runtime, current_period())

    return JSONResponse({
        'ok': True,
        'status': status,
        'business_visible_keys': ordered,
        'schedule_state': schedule_state,
        'rows': result_rows,
    })
