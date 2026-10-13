from __future__ import annotations

from collections import defaultdict
from datetime import date
import json
import re
import uuid

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from .templating import Jinja2Templates

from . import config
from .db import db, now_iso
from .payment_schedule import explicit_payment_date, readable_date
from .payment_v02 import current_period, service_active_in_period, service_is_due, effective_payment_rule, payment_snapshot, valid_invoice_group
from .v025_routes import customer_or_404, service_or_404, promotion_or_404, _payment_run
from .v026_routes import check_csrf, parse_date_text, date_text, month_text, promotion_bucket, derive_schedule
from .v027_routes import _column_widths, _promo_order, _meta_get, _meta_set

from .promotions import expiry_text, available_slot

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')
APP_VERSION = '0.2.8'

CORE_ATTRS = {
    'service_type': {'label': '类型', 'kind': 'text'},
    'holder_name': {'label': '姓名/属性', 'kind': 'text'},
    'number': {'label': '号码', 'kind': 'text'},
    'account': {'label': '账号', 'kind': 'text'},
    'payment_interval_months': {'label': '缴费周期（月）', 'kind': 'integer'},
    'payment_method': {'label': '付款方式', 'kind': 'text'},
    'invoice_type': {'label': '发票类型', 'kind': 'text'},
    'invoice_group': {'label': '发票组', 'kind': 'invoice_group'},
    'package_type': {'label': '套餐类型', 'kind': 'text'},
    'last_payment_date': {'label': '上次缴费日期', 'kind': 'date'},
    'next_payment_date': {'label': '下次缴费时间', 'kind': 'date'},
    'notes': {'label': '备注', 'kind': 'textarea'},
}
DEFAULT_TEMPLATE = [
    {'key': key, 'label': meta['label'], 'kind': meta['kind'], 'core': True}
    for key, meta in CORE_ATTRS.items()
]
TEMPLATE_META_KEY = 'service_attribute_template_v028'
CUSTOM_KEY_RE = re.compile(r'^custom_[a-f0-9]{12}$')


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


def _ensure_attr_store(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS service_custom_attributes (
        service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
        attr_key TEXT NOT NULL,
        value TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(service_id, attr_key)
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_service_custom_attrs_key ON service_custom_attributes(attr_key,service_id)')


def _template(conn):
    _ensure_attr_store(conn)
    raw = _meta_get(conn, TEMPLATE_META_KEY, '')
    if raw:
        try:
            items = json.loads(raw)
            if isinstance(items, list) and items:
                if not any(item.get('key') == 'next_payment_date' for item in items):
                    items.append({'key': 'next_payment_date', **CORE_ATTRS['next_payment_date'], 'core': True})
                    _meta_set(conn, TEMPLATE_META_KEY, json.dumps(items, ensure_ascii=False))
                return items
        except Exception:
            pass
    items = [dict(x) for x in DEFAULT_TEMPLATE]
    _meta_set(conn, TEMPLATE_META_KEY, json.dumps(items, ensure_ascii=False))
    return items


def _custom_map(conn, service_ids):
    result = defaultdict(dict)
    ids = [int(x) for x in service_ids]
    if not ids:
        return result
    placeholders = ','.join('?' for _ in ids)
    for row in conn.execute(
        f'SELECT service_id,attr_key,value FROM service_custom_attributes WHERE service_id IN ({placeholders})',
        ids,
    ).fetchall():
        result[row['service_id']][row['attr_key']] = row['value'] or ''
    return result


def _raw_attr(service, key: str, custom_values: dict) -> str:
    if key.startswith('custom_'):
        return custom_values.get(key, '')
    if key == 'invoice_group':
        return str(service['invoice_group_id'] or '')
    if key == 'payment_interval_months':
        return str(int(service['payment_interval_months'] or 0))
    if key == 'last_payment_date':
        return str(service['last_payment_date'] or '')
    if key == 'next_payment_date':
        return explicit_payment_date(service)
    if key in CORE_ATTRS:
        return str(service[key] or '')
    return ''


def _display_attr(service, key: str, custom_values: dict) -> str:
    if key == 'invoice_group':
        return service['invoice_group_name'] or '未分组'
    value = _raw_attr(service, key, custom_values)
    return value if value else '—'


def _service_attrs(service, template, custom_values):
    return [
        {
            'key': item['key'],
            'label': item['label'],
            'kind': item.get('kind', 'text'),
            'value': _display_attr(service, item['key'], custom_values),
            'raw': _raw_attr(service, item['key'], custom_values),
        }
        for item in template
    ]


def _display_pair(conn, customer, template):
    keys = [x['key'] for x in template]
    if not keys:
        return '', ''
    k1 = (customer['payment_display_attr_1'] or '').strip()
    k2 = (customer['payment_display_attr_2'] or '').strip()
    if k1 not in keys:
        k1 = keys[0]
    if k2 not in keys or k2 == k1:
        k2 = next((k for k in keys if k != k1), k1)
    if k1 != customer['payment_display_attr_1'] or k2 != customer['payment_display_attr_2']:
        conn.execute(
            'UPDATE customers SET payment_display_attr_1=?,payment_display_attr_2=?,updated_at=? WHERE id=?',
            (k1, k2, now_iso(), customer['id']),
        )
    return k1, k2


def _promo_columns(conn, customer_id: int, promo_rows):
    columns = {'expired': [], 'soon': []}
    for bucket in ('expired', 'soon'):
        groups = {}
        for p in promo_rows:
            if promotion_bucket(p['expiry_date'], p['status']) != bucket:
                continue
            base_key = (p['number'] or '').strip() or (p['account'] or '').strip() or f"service-{p['service_id']}"
            key = f'{bucket}:{base_key}'
            group = groups.setdefault(key, {
                'key': key,
                'number': (p['number'] or '').strip(),
                'account': (p['account'] or '').strip(),
                'service_type': p['service_type'] or '',
                'holder_name': p['holder_name'] or '',
                'items': [],
            })
            group['items'].append({
                'row': p,
                'bucket': bucket,
                'expiry_display': expiry_text(p['expiry_date']),
            })
        for group in groups.values():
            order = _promo_order(conn, customer_id, group['key'])
            rank = {pid: i for i, pid in enumerate(order)}
            group['items'].sort(key=lambda x: (rank.get(x['row']['id'], 10**9), x['row']['expiry_date'] or '9999-12-31', x['row']['id']))
        columns[bucket] = sorted(groups.values(), key=lambda g: (g['number'] or g['account'], g['service_type']))
    return columns


def _business_payload(conn, customer_id: int, template, services, promo_rows):
    custom = _custom_map(conn, [s['id'] for s in services])
    promo_by_service = defaultdict(list)
    for p in promo_rows:
        promo_by_service[p['service_id']].append(p)
    rows = []
    for s in services:
        if not service_active_in_period(s, current_period()):
            continue
        promos = promo_by_service.get(s['id'], [])
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
        rule = effective_payment_rule(conn, s['id'], current_period(), s)
        rows.append({
            'row': s,
            'attributes': _service_attrs(s, template, custom[s['id']]),
            'rule': rule,
            'due': service_is_due(s),
            'promo_filter': promo_filter,
            'promo_label': promo_label,
            'promo_nearest': expiry_text(nearest['expiry_date']) if nearest else '',
        })
    return rows, custom


def _attribute_options(template):
    return [(x['key'], x['label']) for x in template]


@router.get('/health')
def health_v028():
    return {'ok': True, 'version': APP_VERSION}


@router.get('/customers/{customer_id}', response_class=HTMLResponse)
def customer_workspace_v028(request: Request, customer_id: int, tab: str = 'payment'):
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
            # payment_snapshot rows do not include invoice_group_name, so find the enriched service row.
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
        'customer_workspace_v028.html',
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


@router.get('/services/{service_id}/attributes-v028')
def service_attributes_v028(service_id: int):
    with db() as conn:
        service = service_or_404(conn, service_id)
        template = _template(conn)
        full = conn.execute(
            '''SELECT s.*,g.name invoice_group_name FROM services s
               LEFT JOIN invoice_groups g ON g.id=s.invoice_group_id WHERE s.id=?''',
            (service_id,),
        ).fetchone()
        custom = _custom_map(conn, [service_id])[service_id]
        groups = conn.execute('SELECT id,name FROM invoice_groups WHERE customer_id=? ORDER BY id', (service['customer_id'],)).fetchall()
    return JSONResponse({
        'ok': True,
        'service_id': service_id,
        'template': template,
        'values': {x['key']: x['raw'] for x in _service_attrs(full, template, custom)},
        'invoice_groups': [{'id': x['id'], 'name': x['name']} for x in groups],
    })


@router.post('/services/{service_id}/attributes-v028')
def save_service_attributes_v028(
    request: Request,
    service_id: int,
    csrf: str = Form(...),
    template_json: str = Form(...),
    values_json: str = Form(...),
):
    check_csrf(request, csrf)
    try:
        requested = json.loads(template_json)
        values = json.loads(values_json)
    except Exception:
        raise HTTPException(400, '属性模板数据无效')
    if not isinstance(requested, list) or not isinstance(values, dict) or len(requested) > 40:
        raise HTTPException(400, '属性模板数据无效')

    with db() as conn:
        old_service = service_or_404(conn, service_id)
        old_template = _template(conn)
        old_custom_keys = {x['key'] for x in old_template if str(x.get('key', '')).startswith('custom_')}
        used = set()
        key_map = {}
        normalized = []
        core_by_label = {meta['label']: key for key, meta in CORE_ATTRS.items()}

        for raw in requested:
            if not isinstance(raw, dict):
                raise HTTPException(400, '属性模板数据无效')
            incoming_key = str(raw.get('key', '')).strip()
            label = str(raw.get('label', '')).strip()[:40]
            kind = str(raw.get('kind', 'text')).strip()
            if not label:
                raise HTTPException(400, '属性名称不能为空')
            if kind not in {'text', 'textarea', 'date', 'integer', 'invoice_group'}:
                kind = 'text'

            key = incoming_key
            if incoming_key.startswith('new_'):
                candidate_core = core_by_label.get(label)
                if candidate_core and candidate_core not in used:
                    key = candidate_core
                    kind = CORE_ATTRS[key]['kind']
                else:
                    key = 'custom_' + uuid.uuid4().hex[:12]
                    if kind in {'integer', 'invoice_group'}:
                        kind = 'text'
                key_map[incoming_key] = key
            elif key in CORE_ATTRS:
                kind = CORE_ATTRS[key]['kind']
            elif not CUSTOM_KEY_RE.fullmatch(key):
                raise HTTPException(400, '属性标识无效')

            if key in used:
                raise HTTPException(400, '同一属性不能重复')
            used.add(key)
            normalized.append({'key': key, 'label': label, 'kind': kind, 'core': key in CORE_ATTRS})

        if not normalized:
            raise HTTPException(400, '至少保留一个业务属性')

        mapped_values = {}
        for key, value in values.items():
            mapped_values[key_map.get(key, key)] = '' if value is None else str(value)

        new_custom_keys = {x['key'] for x in normalized if x['key'].startswith('custom_')}
        removed_custom = old_custom_keys - new_custom_keys
        for key in removed_custom:
            conn.execute('DELETE FROM service_custom_attributes WHERE attr_key=?', (key,))

        _meta_set(conn, TEMPLATE_META_KEY, json.dumps(normalized, ensure_ascii=False))

        current_keys = {x['key'] for x in normalized}
        interval = int(old_service['payment_interval_months'] or 0)
        last_iso = old_service['last_payment_date'] or ''
        updates = {}

        for key in current_keys:
            if key not in mapped_values:
                continue
            value = mapped_values[key].strip()
            if key.startswith('custom_'):
                conn.execute(
                    '''INSERT INTO service_custom_attributes(service_id,attr_key,value) VALUES(?,?,?)
                       ON CONFLICT(service_id,attr_key) DO UPDATE SET value=excluded.value''',
                    (service_id, key, value),
                )
            elif key == 'payment_interval_months':
                if not re.fullmatch(r'\d{1,3}', value or '0'):
                    raise HTTPException(400, '缴费周期必须手动输入0到120之间的整数月数')
                interval = int(value or 0)
                if interval < 0 or interval > 120:
                    raise HTTPException(400, '缴费周期必须是0到120之间的整数月数')
            elif key == 'last_payment_date':
                last_iso = value
            elif key == 'next_payment_date':
                updates['next_payment_date'] = value
            elif key == 'invoice_group':
                updates['invoice_group_id'] = valid_invoice_group(conn, old_service['customer_id'], value)
            elif key in {'service_type', 'holder_name', 'number', 'account', 'payment_method', 'invoice_type', 'package_type', 'notes'}:
                updates[key] = value

        if 'payment_interval_months' in current_keys or 'last_payment_date' in current_keys:
            parsed_last = readable_date(last_iso)
            cycle_text, next_period = derive_schedule(old_service, interval, parsed_last.isoformat() if parsed_last else '')
            updates['payment_interval_months'] = interval
            updates['payment_cycle'] = cycle_text
            updates['next_payment_period'] = next_period
            updates['last_payment_date'] = last_iso

        if updates:
            fields = ','.join(f'{key}=?' for key in updates)
            conn.execute(f'UPDATE services SET {fields} WHERE id=?', (*updates.values(), service_id))
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), old_service['customer_id']))

        customer = customer_or_404(conn, old_service['customer_id'])
        display1, display2 = _display_pair(conn, customer, normalized)
        services = conn.execute(
            '''SELECT s.*,g.name invoice_group_name FROM services s
               LEFT JOIN invoice_groups g ON g.id=s.invoice_group_id
               WHERE s.customer_id=?
               ORDER BY CASE WHEN COALESCE(s.sort_order,0)>0 THEN s.sort_order ELSE 100000000+s.id END,s.id''',
            (old_service['customer_id'],),
        ).fetchall()
        custom = _custom_map(conn, [s['id'] for s in services])
        rows = {
            str(s['id']): {
                'attributes': _service_attrs(s, normalized, custom[s['id']]),
                'display1': _display_attr(s, display1, custom[s['id']]),
                'display2': _display_attr(s, display2, custom[s['id']]),
                'number': s['number'] or '',
                'account': s['account'] or '',
            }
            for s in services
        }

    return JSONResponse({
        'ok': True,
        'template': normalized,
        'key_map': key_map,
        'display_attr_1': display1,
        'display_attr_2': display2,
        'rows': rows,
    })


@router.post('/customers/{customer_id}/display-attributes')
def display_attributes_v028(
    request: Request,
    customer_id: int,
    csrf: str = Form(...),
    display_attr_1: str = Form(...),
    display_attr_2: str = Form(...),
):
    check_csrf(request, csrf)
    with db() as conn:
        customer = customer_or_404(conn, customer_id)
        template = _template(conn)
        keys = {x['key'] for x in template}
        if display_attr_1 not in keys or display_attr_2 not in keys or display_attr_1 == display_attr_2:
            raise HTTPException(400, '默认显示属性无效或重复')
        conn.execute(
            'UPDATE customers SET payment_display_attr_1=?,payment_display_attr_2=?,updated_at=? WHERE id=?',
            (display_attr_1, display_attr_2, now_iso(), customer_id),
        )
        services = conn.execute(
            '''SELECT s.*,g.name invoice_group_name FROM services s
               LEFT JOIN invoice_groups g ON g.id=s.invoice_group_id WHERE s.customer_id=?''',
            (customer_id,),
        ).fetchall()
        custom = _custom_map(conn, [s['id'] for s in services])
        result = {
            str(s['id']): {
                'v1': _display_attr(s, display_attr_1, custom[s['id']]),
                'v2': _display_attr(s, display_attr_2, custom[s['id']]),
            }
            for s in services
        }
    return JSONResponse({'ok': True, 'values': result})


@router.post('/promotions/{promotion_id}/expiry-v028')
def update_promotion_expiry_v028(
    request: Request,
    promotion_id: int,
    csrf: str = Form(...),
    expiry_date: str = Form(''),
):
    check_csrf(request, csrf)
    expiry_iso = expiry_date
    with db() as conn:
        old = promotion_or_404(conn, promotion_id)
        conn.execute(
            "UPDATE promotions SET expiry_date=?,status='active',renewed_at=? WHERE id=?",
            (expiry_iso, now_iso(), promotion_id),
        )
        bucket = promotion_bucket(expiry_iso, 'active')
    return JSONResponse({
        'ok': True,
        'expiry_date': expiry_text(expiry_iso),
        'bucket': bucket,
        'visible': bucket in {'expired', 'soon'},
    })


@router.post('/customers/{customer_id}/promotions/reorder-v028')
def reorder_promotions_v028(
    request: Request,
    customer_id: int,
    csrf: str = Form(...),
    group_key: str = Form(...),
    promotion_ids: str = Form(...),
):
    check_csrf(request, csrf)
    try:
        ids = [int(x) for x in promotion_ids.split(',') if x.strip()]
    except ValueError:
        raise HTTPException(400, '优惠排序数据无效')
    if not ids:
        return JSONResponse({'ok': True})
    with db() as conn:
        customer_or_404(conn, customer_id)
        placeholders = ','.join('?' for _ in ids)
        rows = conn.execute(
            f'''SELECT p.id,s.customer_id FROM promotions p JOIN services s ON s.id=p.service_id
                WHERE p.id IN ({placeholders})''',
            ids,
        ).fetchall()
        if len(rows) != len(ids) or any(r['customer_id'] != customer_id for r in rows):
            raise HTTPException(400, '优惠排序数据不属于当前客户')
        _meta_set(conn, f'promo_order:{customer_id}:{group_key}', json.dumps(ids))
    return JSONResponse({'ok': True})

