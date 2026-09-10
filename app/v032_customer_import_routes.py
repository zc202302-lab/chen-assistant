from __future__ import annotations

import json
import re
import secrets
import zipfile
from collections import defaultdict
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import xlsxwriter
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .config import DATA_DIR
from .db import db, now_iso
from .importer import XlsmReader, col_num, excel_date
from .legacy_main import ctx, current_period, templates
from .security import require_csrf

router = APIRouter()

STAGING_DIR = DATA_DIR / 'customer_import_staging_v032'
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 60 * 1024 * 1024
MAX_GROUPS = 500
MAX_SERVICES = 10000
MAX_CONTACTS = 5000
MAX_PROMOTIONS = 10000
TOKEN_RE = re.compile(r'^[A-Za-z0-9_-]{20,80}$')
CELL_RE = re.compile(r'^([A-Z]+)(\d+)$')

GROUP_HEADERS = ['导入编号', '集团名称', '集团编码', '税号', '客情概述', '启用缴费']
SERVICE_HEADERS = [
    '业务编号', '集团导入编号', '业务类型', '成员/户名', '号码', '账号', '缴费金额', '金额模式',
    '缴费周期', '下次缴费月份', '付款方式', '发票类型', '套餐类型', '上次缴费日期', '备注'
]
CONTACT_HEADERS = ['集团导入编号', '类型', '姓名', '职务/关系', '电话']
PROMO_HEADERS = ['业务编号', '优惠名称', '开始日期', '到期日期', '提前提醒天数', '备注']


def _cleanup_staging() -> None:
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now().timestamp() - 24 * 3600
    for path in STAGING_DIR.glob('*.json'):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except OSError:
            pass


def _normalize_identifier(value) -> str:
    text = '' if value is None else str(value).strip()
    if re.fullmatch(r'\d+\.0', text):
        text = text[:-2]
    return text


def _normalize_name(value) -> str:
    return '' if value is None else re.sub(r'\s+', ' ', str(value).strip())


def _norm_key(value) -> str:
    return _normalize_name(value).casefold()


def _parse_money(value) -> float | None:
    text = '' if value is None else str(value).strip()
    if text == '':
        return None
    text = text.replace(',', '').replace('￥', '').replace('¥', '').replace('元', '').strip()
    try:
        number = float(text)
    except Exception:
        return None
    if number < 0 or number > 100000000:
        return None
    return round(number, 2)


def _parse_yes_no(value, default: bool = True) -> bool | None:
    text = _normalize_name(value).casefold()
    if not text:
        return default
    if text in {'是', '启用', '1', 'true', 'yes', 'y'}:
        return True
    if text in {'否', '停用', '0', 'false', 'no', 'n'}:
        return False
    return None


def _parse_mode(value) -> str | None:
    text = _normalize_name(value).casefold()
    if text in {'固定', 'fixed', '固定金额'}:
        return 'fixed'
    if text in {'变动', 'variable', '非固定', '变动金额'}:
        return 'variable'
    return None


def _parse_cycle(value) -> tuple[str, int] | None:
    text = _normalize_name(value)
    if not text:
        return '每月', 1
    mapping = {
        '月': ('每月', 1), '每月': ('每月', 1), '1个月': ('每月', 1),
        '季度': ('3个月', 3), '季': ('3个月', 3), '3个月': ('3个月', 3),
        '半年': ('6个月', 6), '6个月': ('6个月', 6),
        '年': ('12个月', 12), '每年': ('12个月', 12), '12个月': ('12个月', 12),
    }
    if text in mapping:
        return mapping[text]
    match = re.fullmatch(r'(\d{1,3})\s*个月', text)
    if match:
        months = int(match.group(1))
        if 1 <= months <= 120:
            return f'{months}个月', months
    return None


def _period_add(period: str, months: int) -> str:
    year, month = [int(x) for x in period[:7].split('-')]
    index = year * 12 + month - 1 + months
    return f'{index // 12:04d}-{index % 12 + 1:02d}'


def _normalize_period(value) -> str | None:
    text = _normalize_name(value)
    if not text:
        return ''
    if re.fullmatch(r'\d+(\.\d+)?', text):
        text = excel_date(text)[:7]
    text = text.replace('/', '-').replace('.', '-')
    match = re.fullmatch(r'(\d{4})-(\d{1,2})(?:-\d{1,2})?', text)
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not (2000 <= year <= 2100 and 1 <= month <= 12):
        return None
    return f'{year:04d}-{month:02d}'


def _normalize_date(value) -> str | None:
    text = _normalize_name(value)
    if not text:
        return ''
    if re.fullmatch(r'\d+(\.\d+)?', text):
        text = excel_date(text)
    text = text.replace('/', '-').replace('.', '-')
    try:
        return datetime.strptime(text[:10], '%Y-%m-%d').date().isoformat()
    except Exception:
        return None


def _zip_is_safe(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > 800:
                return False
            if sum(max(0, item.file_size) for item in infos) > MAX_UNCOMPRESSED_BYTES:
                return False
            return 'xl/workbook.xml' in archive.namelist()
    except Exception:
        return False


def _sheet_records(reader: XlsmReader, sheet_name: str, expected_headers: list[str], required: bool):
    paths = {name: path for name, path in reader.sheets}
    if sheet_name not in paths:
        if required:
            return [], [{'sheet': sheet_name, 'row': 0, 'message': f'缺少“{sheet_name}”Sheet'}]
        return [], []
    cells = reader.cells(paths[sheet_name])
    rows: dict[int, dict[int, str]] = defaultdict(dict)
    for ref, value in cells.items():
        match = CELL_RE.fullmatch(ref)
        if match:
            rows[int(match.group(2))][col_num(match.group(1))] = value
    if not rows:
        if required:
            return [], [{'sheet': sheet_name, 'row': 1, 'message': 'Sheet为空'}]
        return [], []
    header_row = min(rows)
    header_lookup = {_normalize_name(value): col for col, value in rows[header_row].items() if _normalize_name(value)}
    missing = [header for header in expected_headers if header not in header_lookup]
    if missing:
        return [], [{'sheet': sheet_name, 'row': header_row, 'message': '缺少列：' + '、'.join(missing)}]
    records = []
    for row_no in sorted(row for row in rows if row > header_row):
        values = rows[row_no]
        item = {header: values.get(header_lookup[header], '') for header in expected_headers}
        if not any(_normalize_name(value) for value in item.values()):
            continue
        item['_row'] = row_no
        records.append(item)
    return records, []


def _existing_customer_conflict(conn, *, name: str, group_code: str, tax_id: str):
    if group_code:
        row = conn.execute(
            "SELECT id,name FROM customers WHERE lower(trim(group_code))=lower(trim(?)) LIMIT 1", (group_code,)
        ).fetchone()
        if row:
            return row, '集团编码'
    if tax_id:
        row = conn.execute(
            "SELECT id,name FROM customers WHERE lower(trim(tax_id))=lower(trim(?)) LIMIT 1", (tax_id,)
        ).fetchone()
        if row:
            return row, '税号'
    row = conn.execute("SELECT id,name FROM customers WHERE trim(name)=trim(?) LIMIT 1", (name,)).fetchone()
    if row:
        return row, '集团名称'
    return None, ''


def _validate_workbook(path: Path, filename: str) -> dict:
    errors: list[dict] = []
    warnings: list[dict] = []
    try:
        reader = XlsmReader(path)
        groups_raw, issue = _sheet_records(reader, '集团', GROUP_HEADERS, True); errors.extend(issue)
        services_raw, issue = _sheet_records(reader, '业务', SERVICE_HEADERS, True); errors.extend(issue)
        contacts_raw, issue = _sheet_records(reader, '联系人', CONTACT_HEADERS, False); errors.extend(issue)
        promos_raw, issue = _sheet_records(reader, '优惠', PROMO_HEADERS, False); errors.extend(issue)
    except Exception as exc:
        return {
            'filename': filename, 'groups': [], 'services': [], 'contacts': [], 'promotions': [],
            'group_preview': [], 'errors': [{'sheet': '文件', 'row': 0, 'message': f'无法读取Excel：{exc}'}],
            'warnings': [], 'summary': {'groups': 0, 'services': 0, 'contacts': 0, 'promotions': 0},
        }

    limits = [
        (len(groups_raw), MAX_GROUPS, '集团', '集团'),
        (len(services_raw), MAX_SERVICES, '业务', '业务'),
        (len(contacts_raw), MAX_CONTACTS, '联系人', '联系人'),
        (len(promos_raw), MAX_PROMOTIONS, '优惠', '优惠'),
    ]
    for count, limit, sheet, label in limits:
        if count > limit:
            errors.append({'sheet': sheet, 'row': 0, 'message': f'{label}数量超过上限 {limit}'})

    groups = []
    group_ids: dict[str, dict] = {}
    seen_names, seen_codes, seen_tax = {}, {}, {}
    for raw in groups_raw:
        row = raw['_row']
        import_id = _normalize_identifier(raw['导入编号'])
        name = _normalize_name(raw['集团名称'])
        group_code = _normalize_identifier(raw['集团编码'])
        tax_id = _normalize_identifier(raw['税号'])
        enabled = _parse_yes_no(raw['启用缴费'], True)
        if not import_id:
            errors.append({'sheet': '集团', 'row': row, 'message': '导入编号不能为空'})
        elif import_id in group_ids:
            errors.append({'sheet': '集团', 'row': row, 'message': f'导入编号 {import_id} 重复'})
        if not name:
            errors.append({'sheet': '集团', 'row': row, 'message': '集团名称不能为空'})
        if enabled is None:
            errors.append({'sheet': '集团', 'row': row, 'message': '启用缴费只能填写“是”或“否”'})
            enabled = True
        for value, seen, field in (
            (name, seen_names, '集团名称'), (group_code, seen_codes, '集团编码'), (tax_id, seen_tax, '税号')
        ):
            key = _norm_key(value)
            if not key:
                continue
            if key in seen:
                errors.append({'sheet': '集团', 'row': row, 'message': f'{field}与第 {seen[key]} 行重复'})
            else:
                seen[key] = row
        item = {
            'import_id': import_id, 'name': name, 'group_code': group_code, 'tax_id': tax_id,
            'relation_summary': _normalize_name(raw['客情概述']), 'payment_enabled': bool(enabled), 'source_row': row,
        }
        groups.append(item)
        if import_id and import_id not in group_ids:
            group_ids[import_id] = item

    services = []
    service_ids: dict[str, dict] = {}
    seen_number: dict[str, int] = {}
    seen_account: dict[str, int] = {}
    for raw in services_raw:
        row = raw['_row']
        business_id = _normalize_identifier(raw['业务编号'])
        group_import_id = _normalize_identifier(raw['集团导入编号'])
        service_type = _normalize_name(raw['业务类型'])
        number = _normalize_identifier(raw['号码'])
        account = _normalize_identifier(raw['账号'])
        amount = _parse_money(raw['缴费金额'])
        mode = _parse_mode(raw['金额模式'])
        cycle = _parse_cycle(raw['缴费周期'])
        next_period = _normalize_period(raw['下次缴费月份'])
        last_payment_date = _normalize_date(raw['上次缴费日期'])
        if not business_id:
            errors.append({'sheet': '业务', 'row': row, 'message': '业务编号不能为空'})
        elif business_id in service_ids:
            errors.append({'sheet': '业务', 'row': row, 'message': f'业务编号 {business_id} 重复'})
        if not group_import_id:
            errors.append({'sheet': '业务', 'row': row, 'message': '集团导入编号不能为空'})
        elif group_import_id not in group_ids:
            errors.append({'sheet': '业务', 'row': row, 'message': f'找不到集团导入编号 {group_import_id}'})
        if not service_type:
            errors.append({'sheet': '业务', 'row': row, 'message': '业务类型不能为空'})
        if amount is None:
            errors.append({'sheet': '业务', 'row': row, 'message': '缴费金额必须是0或正数'})
            amount = 0.0
        if mode is None:
            errors.append({'sheet': '业务', 'row': row, 'message': '金额模式只能填写“固定”或“变动”'})
            mode = 'variable'
        if cycle is None:
            errors.append({'sheet': '业务', 'row': row, 'message': '缴费周期格式错误，例如“每月”“3个月”“6个月”“12个月”'})
            cycle = ('每月', 1)
        if next_period is None:
            errors.append({'sheet': '业务', 'row': row, 'message': '下次缴费月份格式应为 YYYY-MM'})
            next_period = ''
        if last_payment_date is None:
            errors.append({'sheet': '业务', 'row': row, 'message': '上次缴费日期格式应为 YYYY-MM-DD'})
            last_payment_date = ''
        if not number and not account:
            warnings.append({'sheet': '业务', 'row': row, 'message': '号码和账号都为空，后续检索可能不方便'})
        for value, seen, field in ((number, seen_number, '号码'), (account, seen_account, '账号')):
            key = _norm_key(value)
            if not key:
                continue
            if key in seen:
                warnings.append({'sheet': '业务', 'row': row, 'message': f'{field}与第 {seen[key]} 行重复'})
            else:
                seen[key] = row
        cycle_text, interval = cycle
        if interval > 1 and not next_period:
            warnings.append({'sheet': '业务', 'row': row, 'message': f'{cycle_text}业务未填写下次缴费月份，将按上次缴费日期推算；无上次日期则默认本月'})
        item = {
            'business_id': business_id, 'group_import_id': group_import_id, 'service_type': service_type,
            'holder_name': _normalize_name(raw['成员/户名']), 'number': number, 'account': account,
            'monthly_fee': float(amount), 'mode': mode, 'payment_cycle': cycle_text,
            'payment_interval_months': interval, 'next_payment_period': next_period or '',
            'payment_method': _normalize_name(raw['付款方式']), 'invoice_type': _normalize_name(raw['发票类型']),
            'package_type': _normalize_name(raw['套餐类型']), 'last_payment_date': last_payment_date or '',
            'notes': _normalize_name(raw['备注']), 'source_row': row,
        }
        services.append(item)
        if business_id and business_id not in service_ids:
            service_ids[business_id] = item

    contacts = []
    for raw in contacts_raw:
        row = raw['_row']
        group_import_id = _normalize_identifier(raw['集团导入编号'])
        name = _normalize_name(raw['姓名'])
        if not group_import_id:
            errors.append({'sheet': '联系人', 'row': row, 'message': '集团导入编号不能为空'})
        elif group_import_id not in group_ids:
            errors.append({'sheet': '联系人', 'row': row, 'message': f'找不到集团导入编号 {group_import_id}'})
        if not name:
            errors.append({'sheet': '联系人', 'row': row, 'message': '姓名不能为空'})
        contacts.append({
            'group_import_id': group_import_id, 'kind': _normalize_name(raw['类型']), 'name': name,
            'relationship': _normalize_name(raw['职务/关系']), 'phone': _normalize_identifier(raw['电话']),
            'source_row': row,
        })

    promotions = []
    for raw in promos_raw:
        row = raw['_row']
        business_id = _normalize_identifier(raw['业务编号'])
        name = _normalize_name(raw['优惠名称'])
        start_date = _normalize_date(raw['开始日期'])
        expiry_date = _normalize_date(raw['到期日期'])
        remind_text = _normalize_name(raw['提前提醒天数'])
        remind_days = 60
        if not business_id:
            errors.append({'sheet': '优惠', 'row': row, 'message': '业务编号不能为空'})
        elif business_id not in service_ids:
            errors.append({'sheet': '优惠', 'row': row, 'message': f'找不到业务编号 {business_id}'})
        if not name:
            errors.append({'sheet': '优惠', 'row': row, 'message': '优惠名称不能为空'})
        if start_date is None:
            errors.append({'sheet': '优惠', 'row': row, 'message': '开始日期格式应为 YYYY-MM-DD'})
            start_date = ''
        if expiry_date is None:
            errors.append({'sheet': '优惠', 'row': row, 'message': '到期日期格式应为 YYYY-MM-DD'})
            expiry_date = ''
        if remind_text:
            try:
                remind_days = int(float(remind_text))
                if not 0 <= remind_days <= 3650:
                    raise ValueError
            except Exception:
                errors.append({'sheet': '优惠', 'row': row, 'message': '提前提醒天数必须是0-3650之间的整数'})
                remind_days = 60
        if not expiry_date:
            warnings.append({'sheet': '优惠', 'row': row, 'message': '未填写到期日期，将无法产生到期提醒'})
        promotions.append({
            'business_id': business_id, 'name': name, 'start_date': start_date or '',
            'expiry_date': expiry_date or '', 'remind_days': remind_days,
            'notes': _normalize_name(raw['备注']), 'source_row': row,
        })

    with db() as conn:
        for group in groups:
            if not group['name']:
                continue
            existing, field = _existing_customer_conflict(
                conn, name=group['name'], group_code=group['group_code'], tax_id=group['tax_id']
            )
            if existing:
                errors.append({
                    'sheet': '集团', 'row': group['source_row'],
                    'message': f'{field}已存在：{existing["name"]}（现有客户ID {existing["id"]}）',
                })
        existing_numbers = {
            _norm_key(row['number']) for row in conn.execute(
                "SELECT number FROM services WHERE trim(COALESCE(number,''))<>''"
            ).fetchall()
        }
        existing_accounts = {
            _norm_key(row['account']) for row in conn.execute(
                "SELECT account FROM services WHERE trim(COALESCE(account,''))<>''"
            ).fetchall()
        }
        for service in services:
            if service['number'] and _norm_key(service['number']) in existing_numbers:
                warnings.append({'sheet': '业务', 'row': service['source_row'], 'message': f'号码 {service["number"]} 在现有客户中已出现，请确认是否重复'})
            if service['account'] and _norm_key(service['account']) in existing_accounts:
                warnings.append({'sheet': '业务', 'row': service['source_row'], 'message': f'账号 {service["account"]} 在现有客户中已出现，请确认是否重复'})

    service_counts, contact_counts, promo_counts = defaultdict(int), defaultdict(int), defaultdict(int)
    service_to_group = {item['business_id']: item['group_import_id'] for item in services if item['business_id']}
    for item in services:
        service_counts[item['group_import_id']] += 1
    for item in contacts:
        contact_counts[item['group_import_id']] += 1
    for item in promotions:
        group_id = service_to_group.get(item['business_id'], '')
        if group_id:
            promo_counts[group_id] += 1
    group_preview = [
        {**group, 'service_count': service_counts[group['import_id']], 'contact_count': contact_counts[group['import_id']], 'promotion_count': promo_counts[group['import_id']]}
        for group in groups
    ]
    return {
        'version': '0.3.2', 'filename': filename, 'groups': groups, 'services': services,
        'contacts': contacts, 'promotions': promotions, 'group_preview': group_preview,
        'errors': errors, 'warnings': warnings,
        'summary': {'groups': len(groups), 'services': len(services), 'contacts': len(contacts), 'promotions': len(promotions)},
    }


def _stage_payload(payload: dict) -> str:
    _cleanup_staging()
    token = secrets.token_urlsafe(24)
    (STAGING_DIR / f'{token}.json').write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return token


def _load_stage(token: str) -> dict:
    _cleanup_staging()
    if not TOKEN_RE.fullmatch(token or ''):
        raise HTTPException(400, '导入确认令牌无效，请重新上传Excel')
    path = STAGING_DIR / f'{token}.json'
    if not path.exists():
        raise HTTPException(410, '导入预览已过期，请重新上传Excel')
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        raise HTTPException(400, '导入预览数据损坏，请重新上传Excel')


def _delete_stage(token: str) -> None:
    if TOKEN_RE.fullmatch(token or ''):
        (STAGING_DIR / f'{token}.json').unlink(missing_ok=True)


def _final_duplicate_errors(conn, payload: dict) -> list[dict]:
    errors = []
    for group in payload['groups']:
        existing, field = _existing_customer_conflict(
            conn, name=group['name'], group_code=group['group_code'], tax_id=group['tax_id']
        )
        if existing:
            errors.append({
                'sheet': '集团', 'row': group.get('source_row', 0),
                'message': f'确认导入时发现{field}已存在：{existing["name"]}，请重新上传检查',
            })
    return errors


def _commit_payload(payload: dict) -> dict:
    period = current_period()
    now = now_iso()
    created_ids = []
    with db() as conn:
        duplicate_errors = _final_duplicate_errors(conn, payload)
        if duplicate_errors:
            raise ValueError(json.dumps(duplicate_errors, ensure_ascii=False))
        customer_map: dict[str, int] = {}
        for group in payload['groups']:
            cur = conn.execute(
                '''INSERT INTO customers
                   (name,group_code,tax_id,relation_summary,payment_enabled,payment_period,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)''',
                (group['name'], group['group_code'], group['tax_id'], group['relation_summary'], 1 if group['payment_enabled'] else 0, period, now, now),
            )
            customer_id = int(cur.lastrowid)
            customer_map[group['import_id']] = customer_id
            created_ids.append(customer_id)
        service_map: dict[str, int] = {}
        sort_counters = defaultdict(int)
        for service in payload['services']:
            customer_id = customer_map[service['group_import_id']]
            sort_counters[customer_id] += 10
            interval = int(service['payment_interval_months'])
            next_period = service['next_payment_period']
            if interval > 1 and not next_period:
                last = service['last_payment_date']
                next_period = _period_add(last[:7], interval) if len(last) >= 7 else period
            cur = conn.execute(
                '''INSERT INTO services
                   (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,payment_cycle,
                    payment_interval_months,next_payment_period,payment_method,invoice_type,package_type,last_payment_date,
                    source_row,sort_order,notes)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (customer_id, service['service_type'], service['holder_name'], service['number'], service['account'], float(service['monthly_fee']), 1 if service['mode'] == 'fixed' else 0, service['payment_cycle'], interval, next_period, service['payment_method'], service['invoice_type'], service['package_type'], service['last_payment_date'], int(service.get('source_row') or 0), sort_counters[customer_id], service['notes']),
            )
            service_id = int(cur.lastrowid)
            service_map[service['business_id']] = service_id
            conn.execute(
                '''INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at)
                   VALUES(?,?,?,?,?)''',
                (service_id, '1900-01', service['mode'], float(service['monthly_fee']) if service['mode'] == 'fixed' else 0, now),
            )
            conn.execute(
                '''INSERT INTO payment_entries
                   (service_id,period,amount,reference_amount,source,confirmed,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)''',
                (service_id, period, float(service['monthly_fee']), float(service['monthly_fee']), 'fixed' if service['mode'] == 'fixed' else 'imported', 1 if service['mode'] == 'fixed' else 0, now, now),
            )
        for contact in payload['contacts']:
            conn.execute(
                'INSERT INTO contacts(customer_id,kind,name,relationship,phone) VALUES(?,?,?,?,?)',
                (customer_map[contact['group_import_id']], contact['kind'], contact['name'], contact['relationship'], contact['phone']),
            )
        for promo in payload['promotions']:
            conn.execute(
                '''INSERT INTO promotions
                   (service_id,name,start_date,expiry_date,remind_days,status,notes,created_at)
                   VALUES(?,?,?,?,?,'active',?,?)''',
                (service_map[promo['business_id']], promo['name'], promo['start_date'], promo['expiry_date'], int(promo['remind_days']), promo['notes'], now),
            )
    return {'customers': len(payload['groups']), 'services': len(payload['services']), 'contacts': len(payload['contacts']), 'promotions': len(payload['promotions']), 'customer_ids': created_ids}


def _build_template() -> bytes:
    output = BytesIO()
    with db() as conn:
        service_types = [
            row['service_type'] for row in conn.execute(
                "SELECT service_type,COUNT(*) n FROM services WHERE trim(COALESCE(service_type,''))<>'' GROUP BY service_type ORDER BY n DESC,service_type LIMIT 100"
            ).fetchall()
        ]
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    workbook.set_properties({'title': '晨的助手 v0.3.2 客户批量导入模板', 'subject': '客户、业务、联系人、优惠批量导入', 'author': '晨的助手', 'comments': '请先上传预览，确认无误后再导入。'})
    header_fmt = workbook.add_format({'bold': True, 'font_color': '#FFFFFF', 'bg_color': '#111827', 'border': 1, 'border_color': '#D1D5DB', 'align': 'center', 'valign': 'vcenter'})
    title_fmt = workbook.add_format({'bold': True, 'font_size': 18, 'font_color': '#111827'})
    section_fmt = workbook.add_format({'bold': True, 'font_size': 12, 'font_color': '#111827', 'bg_color': '#EEF2F7'})
    body_fmt = workbook.add_format({'font_color': '#374151', 'valign': 'top', 'text_wrap': True})
    text_fmt = workbook.add_format({'num_format': '@'})
    money_fmt = workbook.add_format({'num_format': '0.00'})
    date_fmt = workbook.add_format({'num_format': 'yyyy-mm-dd'})
    period_fmt = workbook.add_format({'num_format': '@'})

    guide = workbook.add_worksheet('填写说明')
    guide.hide_gridlines(2)
    guide.set_column('A:A', 22)
    guide.set_column('B:B', 78)
    guide.merge_range('A1:B1', '晨的助手 v0.3.2 客户批量导入模板', title_fmt)
    guide.write('A3', '使用方式', section_fmt)
    guide.write('B3', '先填写“集团”“业务”，联系人和优惠可留空；上传后系统只做检查和预览，点击“确认导入”才写入数据库。', body_fmt)
    rules = [
        ('导入编号', '集团使用 G001、G002…；业务使用 S001、S002…。它们只用于本Excel关联，不会显示在晨的助手中。'),
        ('集团与业务', '“集团”一行一个集团；“业务”一行一条号码/账号。业务通过“集团导入编号”关联集团。'),
        ('文本字段', '集团编码、税号、号码、账号、电话均已按文本格式设置，避免前导0丢失或长数字被Excel改写。'),
        ('金额模式', '只能填写“固定”或“变动”。固定金额导入后自动处于已确认状态；变动金额需要后续人工核对。'),
        ('缴费周期', '可填“每月”“3个月”“6个月”“12个月”或其他 N个月；留空默认每月。'),
        ('日期格式', '日期用 YYYY-MM-DD；下次缴费月份用 YYYY-MM。'),
        ('重复客户', '批量新建不会覆盖现有客户。集团编码、税号或集团名称与现有客户重复时，整批导入会被阻止。'),
        ('安全规则', 'Excel上传后必须先通过检查；确认导入采用整批事务，任何数据库错误都会整批回滚，不会导入一半。'),
        ('Sheet规则', '不要修改“集团/业务/联系人/优惠”的Sheet名称和第一行列名；“填写说明”和隐藏字典不参与导入。'),
        ('本版模式', 'v0.3.2 正式模板采用多表模式，不采用“一集团一Sheet”。后续可以增加兼容导入，但不会影响本模板。'),
    ]
    for index, (name, text) in enumerate(rules, start=5):
        guide.write(index - 1, 0, name, section_fmt)
        guide.write(index - 1, 1, text, body_fmt)
        guide.set_row(index - 1, 34)

    dictionary = workbook.add_worksheet('_字典')
    dictionary.write_column('A1', ['金额模式', '固定', '变动'])
    dictionary.write_column('B1', ['缴费周期', '每月', '3个月', '6个月', '12个月'])
    dictionary.write_column('C1', ['是否', '是', '否'])
    dictionary.write_column('D1', ['现有业务类型'] + service_types)
    workbook.define_name('ModeList', "='_字典'!$A$2:$A$3")
    workbook.define_name('CycleList', "='_字典'!$B$2:$B$5")
    workbook.define_name('YesNoList', "='_字典'!$C$2:$C$3")
    dictionary.hide()

    def setup_sheet(name: str, headers: list[str], widths: list[int]):
        worksheet = workbook.add_worksheet(name)
        worksheet.hide_gridlines(2)
        worksheet.freeze_panes(1, 0)
        worksheet.set_row(0, 28)
        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_fmt)
            worksheet.set_column(col, col, widths[col])
        worksheet.autofilter(0, 0, 1000, len(headers) - 1)
        return worksheet

    group = setup_sheet('集团', GROUP_HEADERS, [13, 28, 18, 24, 36, 12])
    group.set_column('A:A', 13, text_fmt)
    group.set_column('C:D', 24, text_fmt)
    group.data_validation('F2:F1001', {'validate': 'list', 'source': '=YesNoList', 'input_title': '启用缴费', 'input_message': '请选择“是”或“否”；留空默认“是”'})
    group.write_comment('A1', '必填。建议 G001、G002…，只用于本Excel内部关联。')
    group.write_comment('B1', '必填。与现有集团同名会被判定为重复客户。')

    service = setup_sheet('业务', SERVICE_HEADERS, [13, 15, 16, 16, 20, 22, 13, 12, 13, 16, 15, 15, 16, 16, 30])
    service.set_column('A:B', 15, text_fmt)
    service.set_column('E:F', 22, text_fmt)
    service.set_column('G:G', 13, money_fmt)
    service.set_column('J:J', 16, period_fmt)
    service.set_column('N:N', 16, date_fmt)
    service.data_validation('H2:H10001', {'validate': 'list', 'source': '=ModeList', 'input_title': '金额模式', 'input_message': '固定：金额自动确认；变动：后续需要核对'})
    service.data_validation('I2:I10001', {'validate': 'list', 'source': '=CycleList', 'input_title': '缴费周期', 'input_message': '常用周期可直接选择，也支持手工填写 N个月'})
    service.write_comment('A1', '必填。建议 S001、S002…，优惠Sheet通过它关联业务。')
    service.write_comment('B1', '必填。填写“集团”Sheet中的导入编号，例如 G001。')
    service.write_comment('C1', '必填。可使用现有业务类型，也允许输入新的业务类型。')
    service.write_comment('G1', '必填，可填写0。')
    service.write_comment('H1', '必填：固定 / 变动。')

    contact = setup_sheet('联系人', CONTACT_HEADERS, [15, 16, 16, 22, 20])
    contact.set_column('A:A', 15, text_fmt)
    contact.set_column('E:E', 20, text_fmt)
    contact.write_comment('A1', '填写“集团”Sheet中的导入编号，例如 G001。')

    promo = setup_sheet('优惠', PROMO_HEADERS, [15, 28, 16, 16, 16, 32])
    promo.set_column('A:A', 15, text_fmt)
    promo.set_column('C:D', 16, date_fmt)
    promo.write_comment('A1', '填写“业务”Sheet中的业务编号，例如 S001。')
    promo.write_comment('E1', '留空默认60天。')

    workbook.close()
    return output.getvalue()


def _render_new(request: Request, *, mode: str = 'single', error: str = '', duplicate=None, preview=None, token: str = '', success=None):
    return templates.TemplateResponse(
        'customer_form.html',
        ctx(request, customer=None, mode=mode, error=error, duplicate=duplicate, preview=preview, import_token=token, success=success),
    )


@router.get('/customers/new', response_class=HTMLResponse)
def customer_new_v032(request: Request, mode: str = 'single', imported: int = 0, services: int = 0, contacts: int = 0, promotions: int = 0):
    mode = 'batch' if mode == 'batch' else 'single'
    success = None
    if imported:
        success = {'customers': imported, 'services': services, 'contacts': contacts, 'promotions': promotions}
    return _render_new(request, mode=mode, success=success)


@router.post('/customers/new', response_class=HTMLResponse)
def customer_new_post_v032(request: Request, csrf: str = Form(...), name: str = Form(...), group_code: str = Form(''), tax_id: str = Form(''), relation_summary: str = Form('')):
    try:
        require_csrf(request.state.session, csrf)
    except ValueError:
        raise HTTPException(403)
    name = _normalize_name(name)
    group_code = _normalize_identifier(group_code)
    tax_id = _normalize_identifier(tax_id)
    relation_summary = _normalize_name(relation_summary)
    if not name:
        return _render_new(request, mode='single', error='集团名称不能为空')
    with db() as conn:
        duplicate, field = _existing_customer_conflict(conn, name=name, group_code=group_code, tax_id=tax_id)
        if duplicate:
            return _render_new(request, mode='single', error=f'{field}已存在，已阻止重复新建。', duplicate={'id': int(duplicate['id']), 'name': duplicate['name'], 'field': field})
        now = now_iso()
        cur = conn.execute(
            '''INSERT INTO customers(name,group_code,tax_id,relation_summary,payment_period,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?)''',
            (name, group_code, tax_id, relation_summary, current_period(), now, now),
        )
        customer_id = int(cur.lastrowid)
    return RedirectResponse(f'/customers/{customer_id}', 303)


@router.get('/customers/import-template-v032.xlsx')
def customer_import_template_v032():
    content = _build_template()
    filename = '晨的助手_客户批量导入模板_v0.3.2.xlsx'
    headers = {
        'Content-Disposition': f"attachment; filename=chen-assistant-customer-import-v032.xlsx; filename*=UTF-8''{quote(filename)}",
        'Cache-Control': 'no-store',
    }
    return Response(content=content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers=headers)


@router.post('/customers/import-v032/preview', response_class=HTMLResponse)
async def customer_import_preview_v032(request: Request, csrf: str = Form(...), excel_file: UploadFile = File(...)):
    try:
        require_csrf(request.state.session, csrf)
    except ValueError:
        raise HTTPException(403)
    filename = (excel_file.filename or '').strip()
    if not filename.lower().endswith('.xlsx'):
        return _render_new(request, mode='batch', error='目前批量导入仅接受 .xlsx 文件，请使用系统提供的模板。')
    data = await excel_file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        return _render_new(request, mode='batch', error='上传的Excel文件为空。')
    if len(data) > MAX_UPLOAD_BYTES:
        return _render_new(request, mode='batch', error='Excel文件超过10MB，请拆分后再导入。')
    _cleanup_staging()
    temp_path = STAGING_DIR / f'upload-{secrets.token_urlsafe(16)}.xlsx'
    temp_path.write_bytes(data)
    try:
        if not _zip_is_safe(temp_path):
            return _render_new(request, mode='batch', error='Excel文件结构异常或内容过大，请重新下载模板填写。')
        preview = _validate_workbook(temp_path, filename)
    finally:
        temp_path.unlink(missing_ok=True)
    token = ''
    if not preview['errors'] and preview['summary'].get('groups', 0) > 0:
        token = _stage_payload(preview)
    elif not preview['errors']:
        preview['errors'].append({'sheet': '集团', 'row': 0, 'message': '没有发现可导入的集团数据'})
    return _render_new(request, mode='batch', preview=preview, token=token)


@router.post('/customers/import-v032/confirm', response_class=HTMLResponse)
def customer_import_confirm_v032(request: Request, csrf: str = Form(...), import_token: str = Form(...)):
    try:
        require_csrf(request.state.session, csrf)
    except ValueError:
        raise HTTPException(403)
    payload = _load_stage(import_token)
    if payload.get('errors'):
        _delete_stage(import_token)
        return _render_new(request, mode='batch', error='该预览包含错误，不能导入，请重新上传。', preview=payload)
    try:
        result = _commit_payload(payload)
    except ValueError as exc:
        try:
            duplicate_errors = json.loads(str(exc))
        except Exception:
            duplicate_errors = [{'sheet': '系统', 'row': 0, 'message': str(exc)}]
        payload = dict(payload)
        payload['errors'] = duplicate_errors
        _delete_stage(import_token)
        return _render_new(request, mode='batch', error='正式导入前发现数据已发生变化，请重新上传检查。', preview=payload)
    finally:
        _delete_stage(import_token)
    return RedirectResponse(
        '/customers/new?mode=batch'
        f'&imported={result["customers"]}&services={result["services"]}'
        f'&contacts={result["contacts"]}&promotions={result["promotions"]}',
        303,
    )
