from __future__ import annotations

import json
import re
import secrets
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
from .importer import XlsmReader, col_num
from .legacy_main import current_period
from .security import require_csrf
from .v028_routes import CORE_ATTRS, _custom_map, _raw_attr, _template
from .v03_mail_draft_routes import _ensure_mail_templates, _get_template, _save_template
from .v031_payment_workflow_routes import ensure_v031
from . import v0212_routes as runtime
from .v032_customer_import_routes import (
    MAX_UPLOAD_BYTES,
    TOKEN_RE,
    _cleanup_staging,
    _existing_customer_conflict,
    _normalize_date,
    _normalize_identifier,
    _normalize_name,
    _normalize_period,
    _parse_money,
    _parse_yes_no,
    _render_new,
    _zip_is_safe,
)

router = APIRouter()
STAGING_DIR = DATA_DIR / 'customer_exchange_staging_v032'
FORMAT_MARKER = '晨的助手客户档案 v0.3.2'
SECTION_RE = re.compile(r'^【(.+)】$')
CELL_RE = re.compile(r'^([A-Z]+)(\d+)$')
MAX_CUSTOMERS = 500
MAX_ROWS_PER_SECTION = 20000

CUSTOMER_FIELDS = [
    ('客户名称', 'name'), ('集团编码', 'group_code'), ('税号', 'tax_id'), ('客情概述', 'relation_summary'),
    ('启用缴费', 'payment_enabled'), ('缴费显示属性1', 'payment_display_attr_1'), ('缴费显示属性2', 'payment_display_attr_2'),
    ('邮件主题', 'mail_subject'), ('邮件正文', 'mail_body'), ('TXT附件名称', 'attachment_filename'),
    ('员工自有', 'employee_own'), ('员工共享', 'employee_share'), ('租赁自有', 'leased_own'),
    ('租赁其他', 'leased_other'), ('其他状态', 'other_status'),
]

ENTITY_HEADERS = ['名称', '集团编码', '税号']
INVOICE_HEADERS = ['开票组名称', '备注']
CONTACT_HEADERS = ['类型', '姓名', '职务/关系', '电话']
PROMO_HEADERS = ['业务编号', '优惠名称', '开始日期', '到期日期', '提前提醒天数', '状态', '备注']
TASK_HEADERS = ['待办事项', '提醒日期', '备注', '已完成']
VISIT_HEADERS = ['日期', '类型', '结果', '下一步计划']
RULE_HEADERS = ['业务编号', '生效月份', '金额模式', '固定金额']
PAYMENT_HEADERS = ['业务编号', '月份', '金额', '参考金额', '来源', '已确认']
RUN_HEADERS = ['月份', '金额核对时间', '通知客户时间', '邮件记录时间', '发起缴费时间', '完成缴费时间']
BUSINESS_SYSTEM_FIELDS = [
    ('业务编号', 'business_id'),
    ('缴费金额', 'payment_amount'),
    ('金额模式', 'payment_mode'),
    ('下次缴费月份', 'next_payment_period'),
    ('业务状态', 'runtime_status'),
    ('延期至月份', 'deferred_until_period'),
    ('启用月份', 'active_from_period'),
    ('停用月份', 'inactive_from_period'),
    ('排序', 'sort_order'),
]


def _stage_dir() -> Path:
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now().timestamp() - 24 * 3600
    for path in STAGING_DIR.glob('*.json'):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except OSError:
            pass
    return STAGING_DIR


def _stage(payload: dict) -> str:
    token = secrets.token_urlsafe(24)
    (_stage_dir() / f'{token}.json').write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return token


def _load_stage(token: str) -> dict:
    if not TOKEN_RE.fullmatch(token or ''):
        raise HTTPException(400, '导入确认令牌无效，请重新上传Excel')
    path = _stage_dir() / f'{token}.json'
    if not path.exists():
        raise HTTPException(410, '导入预览已过期，请重新上传Excel')
    return json.loads(path.read_text(encoding='utf-8'))


def _delete_stage(token: str) -> None:
    if TOKEN_RE.fullmatch(token or ''):
        (_stage_dir() / f'{token}.json').unlink(missing_ok=True)


def _rows_from_cells(cells: dict[str, str]) -> dict[int, dict[int, str]]:
    rows: dict[int, dict[int, str]] = defaultdict(dict)
    for ref, value in cells.items():
        m = CELL_RE.fullmatch(ref)
        if m:
            rows[int(m.group(2))][col_num(m.group(1))] = value
    return rows


def _section_map(rows: dict[int, dict[int, str]]) -> dict[str, tuple[int, int]]:
    markers = []
    for row_no in sorted(rows):
        text = _normalize_name(rows[row_no].get(1, ''))
        match = SECTION_RE.fullmatch(text)
        if match:
            markers.append((row_no, match.group(1)))
    result = {}
    for index, (start, name) in enumerate(markers):
        end = markers[index + 1][0] - 1 if index + 1 < len(markers) else (max(rows) if rows else start)
        result[name] = (start, end)
    return result


def _attr_signature(conn):
    template = _template(conn)
    return template, [(str(item['key']), str(item['label']), str(item.get('kind', 'text'))) for item in template]


def _business_columns(template):
    cols = [('业务编号', 'business_id')]
    cols.extend((str(item['label']), f"attr:{item['key']}") for item in template)
    cols.extend(BUSINESS_SYSTEM_FIELDS[1:])
    return cols


def _attr_label_map(template):
    return {str(item['key']): str(item['label']) for item in template}


def _display_attr_label(template, key: str) -> str:
    labels = _attr_label_map(template)
    return labels.get(key, key or '')


def _display_attr_key(template, value: str) -> str:
    value = _normalize_name(value)
    if not value:
        return ''
    labels = {str(item['label']): str(item['key']) for item in template}
    keys = {str(item['key']) for item in template}
    return labels.get(value, value if value in keys else '')


def _sheet_name(value: str, used: set[str]) -> str:
    base = re.sub(r'[\\/*?:\[\]]', '_', _normalize_name(value)).strip(" '") or '客户'
    base = base[:31]
    candidate = base
    n = 2
    while candidate.casefold() in used:
        suffix = f'_{n}'
        candidate = base[:31-len(suffix)] + suffix
        n += 1
    used.add(candidate.casefold())
    return candidate


def _formats(workbook):
    return {
        'title': workbook.add_format({'bold': True, 'font_size': 18, 'font_color': '#111827'}),
        'hint': workbook.add_format({'font_color': '#6B7280', 'italic': True, 'text_wrap': True}),
        'section': workbook.add_format({'bold': True, 'font_size': 12, 'font_color': '#FFFFFF', 'bg_color': '#111827', 'align': 'left'}),
        'label': workbook.add_format({'bold': True, 'font_color': '#374151', 'bg_color': '#F3F4F6', 'border': 1, 'border_color': '#E5E7EB'}),
        'value': workbook.add_format({'font_color': '#111827', 'border': 1, 'border_color': '#E5E7EB', 'text_wrap': True}),
        'header': workbook.add_format({'bold': True, 'font_color': '#FFFFFF', 'bg_color': '#4B5563', 'border': 1, 'border_color': '#D1D5DB', 'align': 'center', 'valign': 'vcenter', 'text_wrap': True}),
        'cell': workbook.add_format({'border': 1, 'border_color': '#E5E7EB', 'text_wrap': True, 'valign': 'top'}),
        'text': workbook.add_format({'num_format': '@', 'border': 1, 'border_color': '#E5E7EB', 'text_wrap': True}),
        'money': workbook.add_format({'num_format': '0.00', 'border': 1, 'border_color': '#E5E7EB'}),
        'readonly': workbook.add_format({'font_color': '#6B7280', 'bg_color': '#F9FAFB', 'border': 1, 'border_color': '#E5E7EB'}),
        'technical': workbook.add_format({'font_color': '#FFFFFF', 'bg_color': '#FFFFFF', 'font_size': 1}),
    }


def _write_section(ws, row: int, title: str, fmt, width: int = 8) -> int:
    ws.merge_range(row, 0, row, max(1, width - 1), f'【{title}】', fmt['section'])
    ws.set_row(row, 24)
    return row + 1


def _write_table(ws, row: int, headers: list[str], values: list[list], fmt, technical_keys: list[str] | None = None, blank_rows: int = 0) -> int:
    for col, header in enumerate(headers):
        ws.write(row, col, header, fmt['header'])
    ws.set_row(row, 26)
    row += 1
    if technical_keys is not None:
        for col, key in enumerate(technical_keys):
            ws.write(row, col, key, fmt['technical'])
        ws.set_row(row, 2, fmt['technical'], {'hidden': True})
        row += 1
    data = values or ([[''] * len(headers)] * max(1, blank_rows))
    for item in data:
        for col, value in enumerate(item):
            cell_fmt = fmt['text'] if headers[col] in {'集团编码', '税号', '号码', '账号', '电话', '业务编号'} else fmt['cell']
            if headers[col] in {'缴费金额', '固定金额', '金额', '参考金额'}:
                cell_fmt = fmt['money']
            ws.write(row, col, value, cell_fmt)
        row += 1
    return row + 1


def _prepare_conn(conn):
    runtime._ensure_runtime(conn)
    _ensure_mail_templates(conn)
    ensure_v031(conn)


def _customer_payload(conn, customer, template):
    customer_id = int(customer['id'])
    _prepare_conn(conn)
    custom = _custom_map(conn, [r['id'] for r in conn.execute('SELECT id FROM services WHERE customer_id=?', (customer_id,)).fetchall()])
    mail = _get_template(conn, customer_id)
    info = {
        'name': customer['name'] or '', 'group_code': customer['group_code'] or '', 'tax_id': customer['tax_id'] or '',
        'relation_summary': customer['relation_summary'] or '', 'payment_enabled': '是' if customer['payment_enabled'] else '否',
        'payment_display_attr_1': _display_attr_label(template, customer['payment_display_attr_1'] or ''),
        'payment_display_attr_2': _display_attr_label(template, customer['payment_display_attr_2'] or ''),
        'mail_subject': mail['subject'], 'mail_body': mail['body'], 'attachment_filename': mail['attachment_filename'],
        'employee_own': customer['employee_own'] or '', 'employee_share': customer['employee_share'] or '',
        'leased_own': customer['leased_own'] or '', 'leased_other': customer['leased_other'] or '', 'other_status': customer['other_status'] or '',
    }
    entities = [list(r) for r in conn.execute('SELECT name,group_code,tax_id FROM customer_entities WHERE customer_id=? ORDER BY id', (customer_id,)).fetchall()]
    invoices = [list(r) for r in conn.execute('SELECT name,note FROM invoice_groups WHERE customer_id=? ORDER BY id', (customer_id,)).fetchall()]
    invoice_names = {r['id']: r['name'] for r in conn.execute('SELECT id,name FROM invoice_groups WHERE customer_id=?', (customer_id,)).fetchall()}
    services = conn.execute('SELECT * FROM services WHERE customer_id=? ORDER BY CASE WHEN COALESCE(sort_order,0)>0 THEN sort_order ELSE 100000000+id END,id', (customer_id,)).fetchall()
    runtimes = runtime._runtime_map(conn, [s['id'] for s in services])
    business_rows = []
    business_ids = {}
    for index, service in enumerate(services, 1):
        bid = f'S{index:03d}'
        business_ids[int(service['id'])] = bid
        row = [bid]
        for item in template:
            key = str(item['key'])
            if key == 'invoice_group':
                row.append(invoice_names.get(service['invoice_group_id'], ''))
            else:
                row.append(_raw_attr(service, key, custom[int(service['id'])]))
        rule = conn.execute('SELECT mode,fixed_amount FROM service_payment_rules WHERE service_id=? ORDER BY effective_period DESC,id DESC LIMIT 1', (service['id'],)).fetchone()
        rt = runtimes[int(service['id'])]
        row.extend([
            float(service['monthly_fee'] or 0),
            '固定' if (rule and rule['mode'] == 'fixed') or service['fixed_fee'] else '变动',
            service['next_payment_period'] or '', '停用' if rt['status'] != 'active' else '启用', rt['deferred_until_period'] or '',
            service['active_from_period'] or '', service['inactive_from_period'] or '', int(service['sort_order'] or 0),
        ])
        business_rows.append(row)
    contacts = [list(r) for r in conn.execute('SELECT kind,name,relationship,phone FROM contacts WHERE customer_id=? ORDER BY id', (customer_id,)).fetchall()]
    promotions = []
    for r in conn.execute('''SELECT p.*,s.id service_id FROM promotions p JOIN services s ON s.id=p.service_id WHERE s.customer_id=? ORDER BY p.id''', (customer_id,)).fetchall():
        promotions.append([business_ids.get(int(r['service_id']), ''), r['name'] or '', r['start_date'] or '', r['expiry_date'] or '', int(r['remind_days'] or 60), r['status'] or 'active', r['notes'] or ''])
    tasks = [[r['title'] or '', r['remind_date'] or '', r['note'] or '', '是' if r['done'] else '否'] for r in conn.execute('SELECT * FROM tasks WHERE customer_id=? ORDER BY id', (customer_id,)).fetchall()]
    visits = [[r['visit_date'] or '', r['kind'] or '', r['result'] or '', r['plan'] or ''] for r in conn.execute('SELECT * FROM visits WHERE customer_id=? ORDER BY id', (customer_id,)).fetchall()]
    rules = []
    for r in conn.execute('''SELECT r.*,s.id service_id FROM service_payment_rules r JOIN services s ON s.id=r.service_id WHERE s.customer_id=? ORDER BY r.service_id,r.effective_period,r.id''', (customer_id,)).fetchall():
        rules.append([business_ids.get(int(r['service_id']), ''), r['effective_period'] or '', '固定' if r['mode'] == 'fixed' else '变动', float(r['fixed_amount'] or 0)])
    payments = []
    for r in conn.execute('''SELECT p.*,s.id service_id FROM payment_entries p JOIN services s ON s.id=p.service_id WHERE s.customer_id=? ORDER BY p.period,p.service_id,p.id''', (customer_id,)).fetchall():
        payments.append([business_ids.get(int(r['service_id']), ''), r['period'] or '', float(r['amount'] or 0), '' if r['reference_amount'] is None else float(r['reference_amount']), r['source'] or '', '是' if r['confirmed'] else '否'])
    run_cols = {r['name'] for r in conn.execute('PRAGMA table_info(customer_payment_runs)').fetchall()}
    runs = []
    for r in conn.execute('SELECT * FROM customer_payment_runs WHERE customer_id=? ORDER BY period,id', (customer_id,)).fetchall():
        runs.append([r['period'] or '', r['reviewed_at'] if 'reviewed_at' in run_cols else '', r['notified_at'] or '', r['emailed_at'] if 'emailed_at' in run_cols else '', r['initiated_at'] if 'initiated_at' in run_cols else '', r['paid_at'] or ''])
    return {'info': info, 'entities': entities, 'invoices': invoices, 'businesses': business_rows, 'contacts': contacts, 'promotions': promotions, 'tasks': tasks, 'visits': visits, 'rules': rules, 'payments': payments, 'runs': runs}


def _write_customer_sheet(workbook, ws, template, payload=None, blank=False):
    fmt = _formats(workbook)
    ws.hide_gridlines(2)
    ws.freeze_panes(3, 0)
    ws.set_column('A:A', 20)
    ws.set_column('B:B', 26)
    ws.set_column('C:Z', 18)
    ws.write('A1', FORMAT_MARKER, fmt['title'])
    ws.write('A2', '每个Sheet代表一个客户；复制本Sheet即可一次导入多个客户。业务属性会随网页当前属性模板动态生成。', fmt['hint'])
    row = 3
    row = _write_section(ws, row, '客户资料', fmt)
    info = (payload or {}).get('info', {})
    for label, key in CUSTOMER_FIELDS:
        ws.write(row, 0, label, fmt['label'])
        ws.write(row, 1, info.get(key, ''), fmt['text'] if key in {'group_code', 'tax_id'} else fmt['value'])
        row += 1
    row += 1
    row = _write_section(ws, row, '关联集团', fmt)
    row = _write_table(ws, row, ENTITY_HEADERS, (payload or {}).get('entities', []), fmt, blank_rows=2 if blank else 0)
    row = _write_section(ws, row, '开票组', fmt)
    row = _write_table(ws, row, INVOICE_HEADERS, (payload or {}).get('invoices', []), fmt, blank_rows=2 if blank else 0)
    row = _write_section(ws, row, '业务/产品', fmt, width=max(8, len(_business_columns(template))))
    business_cols = _business_columns(template)
    row = _write_table(ws, row, [x[0] for x in business_cols], (payload or {}).get('businesses', []), fmt, technical_keys=[x[1] for x in business_cols], blank_rows=12 if blank else 0)
    row = _write_section(ws, row, '联系人', fmt)
    row = _write_table(ws, row, CONTACT_HEADERS, (payload or {}).get('contacts', []), fmt, blank_rows=4 if blank else 0)
    row = _write_section(ws, row, '优惠', fmt)
    row = _write_table(ws, row, PROMO_HEADERS, (payload or {}).get('promotions', []), fmt, blank_rows=6 if blank else 0)
    row = _write_section(ws, row, '待办', fmt)
    row = _write_table(ws, row, TASK_HEADERS, (payload or {}).get('tasks', []), fmt, blank_rows=4 if blank else 0)
    row = _write_section(ws, row, '跟进/拜访', fmt)
    row = _write_table(ws, row, VISIT_HEADERS, (payload or {}).get('visits', []), fmt, blank_rows=4 if blank else 0)
    row = _write_section(ws, row, '缴费规则历史', fmt)
    row = _write_table(ws, row, RULE_HEADERS, (payload or {}).get('rules', []), fmt, blank_rows=0)
    row = _write_section(ws, row, '缴费记录', fmt)
    row = _write_table(ws, row, PAYMENT_HEADERS, (payload or {}).get('payments', []), fmt, blank_rows=0)
    row = _write_section(ws, row, '缴费流程记录', fmt)
    _write_table(ws, row, RUN_HEADERS, (payload or {}).get('runs', []), fmt, blank_rows=0)
    ws.data_validation('B8', {'validate': 'list', 'source': ['是', '否']})


def _build_blank_template() -> bytes:
    output = BytesIO()
    with db() as conn:
        template, _ = _attr_signature(conn)
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    workbook.set_properties({'title': '晨的助手 v0.3.2 一客户一Sheet导入模板', 'author': '晨的助手'})
    ws = workbook.add_worksheet('客户1')
    _write_customer_sheet(workbook, ws, template, blank=True)
    workbook.close()
    return output.getvalue()


def _build_export() -> bytes:
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    workbook.set_properties({'title': '晨的助手全部客户导出', 'author': '晨的助手'})
    used = set()
    with db() as conn:
        template, _ = _attr_signature(conn)
        customers = conn.execute('SELECT * FROM customers ORDER BY name,id').fetchall()
        if not customers:
            ws = workbook.add_worksheet('暂无客户')
            ws.write('A1', '当前没有客户数据')
        for customer in customers:
            ws = workbook.add_worksheet(_sheet_name(customer['name'], used))
            _write_customer_sheet(workbook, ws, template, _customer_payload(conn, customer, template), blank=False)
    workbook.close()
    return output.getvalue()


def _table_section(rows, start: int, end: int, technical=False):
    header_row = start + 1
    key_row = start + 2 if technical else None
    data_start = start + 3 if technical else start + 2
    headers = rows.get(header_row, {})
    keys = rows.get(key_row, {}) if key_row else {}
    cols = sorted(headers)
    records = []
    for row_no in range(data_start, end + 1):
        row = rows.get(row_no, {})
        if not any(_normalize_name(row.get(c, '')) for c in cols):
            continue
        item = {'_row': row_no}
        for col in cols:
            key = _normalize_name(keys.get(col, '')) if technical else _normalize_name(headers.get(col, ''))
            if key:
                item[key] = row.get(col, '')
        records.append(item)
    return headers, keys, records


def _parse_sheet(conn, sheet_name: str, cells: dict[str, str], template) -> tuple[dict | None, list, list]:
    errors, warnings = [], []
    rows = _rows_from_cells(cells)
    if _normalize_name(cells.get('A1', '')) != FORMAT_MARKER:
        return None, [{'sheet': sheet_name, 'row': 1, 'message': '不是晨的助手 v0.3.2 一客户一Sheet模板'}], []
    sections = _section_map(rows)
    if '客户资料' not in sections or '业务/产品' not in sections:
        return None, [{'sheet': sheet_name, 'row': 0, 'message': '缺少“客户资料”或“业务/产品”区域'}], []
    info = {}
    start, end = sections['客户资料']
    field_map = {label: key for label, key in CUSTOMER_FIELDS}
    for row_no in range(start + 1, end + 1):
        label = _normalize_name(rows.get(row_no, {}).get(1, ''))
        if label in field_map:
            info[field_map[label]] = rows.get(row_no, {}).get(2, '')
    name = _normalize_name(info.get('name', ''))
    if not name:
        errors.append({'sheet': sheet_name, 'row': start + 1, 'message': '客户名称不能为空'})
    enabled = _parse_yes_no(info.get('payment_enabled', ''), True)
    if enabled is None:
        errors.append({'sheet': sheet_name, 'row': 0, 'message': '启用缴费只能填写“是”或“否”'})
        enabled = True
    group_code = _normalize_identifier(info.get('group_code', ''))
    tax_id = _normalize_identifier(info.get('tax_id', ''))
    if name:
        existing, field = _existing_customer_conflict(conn, name=name, group_code=group_code, tax_id=tax_id)
        if existing:
            errors.append({'sheet': sheet_name, 'row': 0, 'message': f'{field}已存在：{existing["name"]}（现有客户ID {existing["id"]}）'})
    display1 = _display_attr_key(template, info.get('payment_display_attr_1', ''))
    display2 = _display_attr_key(template, info.get('payment_display_attr_2', ''))
    valid_keys = {str(x['key']) for x in template}
    if not display1:
        display1 = next(iter(valid_keys), '')
    if not display2 or display2 == display1:
        display2 = next((k for k in valid_keys if k != display1), display1)
    customer = {
        'sheet': sheet_name, 'name': name, 'group_code': group_code, 'tax_id': tax_id,
        'relation_summary': _normalize_name(info.get('relation_summary', '')), 'payment_enabled': bool(enabled),
        'payment_display_attr_1': display1, 'payment_display_attr_2': display2,
        'mail_subject': str(info.get('mail_subject', '') or '').strip(), 'mail_body': str(info.get('mail_body', '') or ''),
        'attachment_filename': str(info.get('attachment_filename', '') or '').strip(),
        'employee_own': _normalize_name(info.get('employee_own', '')), 'employee_share': _normalize_name(info.get('employee_share', '')),
        'leased_own': _normalize_name(info.get('leased_own', '')), 'leased_other': _normalize_name(info.get('leased_other', '')),
        'other_status': _normalize_name(info.get('other_status', '')),
    }
    business_start, business_end = sections['业务/产品']
    headers, keys, business_raw = _table_section(rows, business_start, business_end, technical=True)
    actual_keys = [_normalize_name(keys[c]) for c in sorted(keys) if _normalize_name(keys[c])]
    expected_keys = [x[1] for x in _business_columns(template)]
    if actual_keys != expected_keys:
        errors.append({'sheet': sheet_name, 'row': business_start + 2, 'message': '业务属性结构与当前网页不一致，请重新下载最新模板后填写'})
    businesses, business_ids = [], set()
    invoice_names = set()
    if '开票组' in sections:
        _, _, raw = _table_section(rows, *sections['开票组'])
        for item in raw:
            nm = _normalize_name(item.get('开票组名称', ''))
            if nm:
                invoice_names.add(nm)
    for index, raw in enumerate(business_raw, 1):
        bid = _normalize_identifier(raw.get('business_id', '')) or f'S{index:03d}'
        if bid in business_ids:
            errors.append({'sheet': sheet_name, 'row': raw['_row'], 'message': f'业务编号 {bid} 重复'})
        business_ids.add(bid)
        attrs = {}
        for item in template:
            key = str(item['key'])
            val = raw.get(f'attr:{key}', '')
            if key in {'number', 'account'}:
                val = _normalize_identifier(val)
            elif key == 'payment_interval_months':
                text = _normalize_name(val)
                if text and not re.fullmatch(r'\d{1,3}', text):
                    errors.append({'sheet': sheet_name, 'row': raw['_row'], 'message': f'{item["label"]}必须是0-120之间的整数'})
                attrs[key] = int(float(text or 0)) if re.fullmatch(r'\d+(?:\.0+)?', text or '0') else 0
                continue
            elif key == 'last_payment_date':
                norm = _normalize_date(val)
                if norm is None:
                    errors.append({'sheet': sheet_name, 'row': raw['_row'], 'message': f'{item["label"]}格式应为 YYYY-MM-DD'})
                    norm = ''
                attrs[key] = norm
                continue
            attrs[key] = _normalize_name(val)
        amount = _parse_money(raw.get('payment_amount', ''))
        if amount is None:
            errors.append({'sheet': sheet_name, 'row': raw['_row'], 'message': '缴费金额必须是0或正数'})
            amount = 0.0
        mode_text = _normalize_name(raw.get('payment_mode', ''))
        mode = 'fixed' if mode_text in {'固定', 'fixed', '固定金额'} else ('variable' if mode_text in {'变动', 'variable', '变动金额', '非固定'} else None)
        if mode is None:
            errors.append({'sheet': sheet_name, 'row': raw['_row'], 'message': '金额模式只能填写“固定”或“变动”'})
            mode = 'variable'
        next_period = _normalize_period(raw.get('next_payment_period', ''))
        if next_period is None:
            errors.append({'sheet': sheet_name, 'row': raw['_row'], 'message': '下次缴费月份格式应为 YYYY-MM'})
            next_period = ''
        status_text = _normalize_name(raw.get('runtime_status', '')) or '启用'
        status = 'inactive' if status_text in {'停用', 'inactive'} else 'active'
        deferred = _normalize_period(raw.get('deferred_until_period', ''))
        if deferred is None:
            errors.append({'sheet': sheet_name, 'row': raw['_row'], 'message': '延期至月份格式应为 YYYY-MM'})
            deferred = ''
        active_from = _normalize_period(raw.get('active_from_period', ''))
        inactive_from = _normalize_period(raw.get('inactive_from_period', ''))
        if active_from is None or inactive_from is None:
            errors.append({'sheet': sheet_name, 'row': raw['_row'], 'message': '启用/停用月份格式应为 YYYY-MM'})
            active_from, inactive_from = active_from or '', inactive_from or ''
        invoice_name = attrs.get('invoice_group', '')
        if invoice_name:
            invoice_names.add(invoice_name)
        businesses.append({'business_id': bid, 'attrs': attrs, 'amount': float(amount), 'mode': mode, 'next_payment_period': next_period or '', 'runtime_status': status, 'deferred_until_period': deferred or '', 'active_from_period': active_from or '', 'inactive_from_period': inactive_from or '', 'sort_order': int(float(_normalize_name(raw.get('sort_order', '')) or index * 10)), 'source_row': raw['_row']})
    def parse_named(section, headers):
        if section not in sections:
            return []
        _, _, values = _table_section(rows, *sections[section])
        return values[:MAX_ROWS_PER_SECTION]
    entities = [{'name': _normalize_name(x.get('名称', '')), 'group_code': _normalize_identifier(x.get('集团编码', '')), 'tax_id': _normalize_identifier(x.get('税号', ''))} for x in parse_named('关联集团', ENTITY_HEADERS) if _normalize_name(x.get('名称', ''))]
    invoices = [{'name': _normalize_name(x.get('开票组名称', '')), 'note': _normalize_name(x.get('备注', ''))} for x in parse_named('开票组', INVOICE_HEADERS) if _normalize_name(x.get('开票组名称', ''))]
    contacts = [{'kind': _normalize_name(x.get('类型', '')), 'name': _normalize_name(x.get('姓名', '')), 'relationship': _normalize_name(x.get('职务/关系', '')), 'phone': _normalize_identifier(x.get('电话', ''))} for x in parse_named('联系人', CONTACT_HEADERS) if _normalize_name(x.get('姓名', '')) or _normalize_identifier(x.get('电话', ''))]
    promotions = []
    for x in parse_named('优惠', PROMO_HEADERS):
        bid = _normalize_identifier(x.get('业务编号', ''))
        nm = _normalize_name(x.get('优惠名称', ''))
        if not bid and not nm:
            continue
        if bid not in business_ids:
            errors.append({'sheet': sheet_name, 'row': x['_row'], 'message': f'优惠找不到业务编号 {bid}'})
        start_date, expiry_date = _normalize_date(x.get('开始日期', '')), _normalize_date(x.get('到期日期', ''))
        if start_date is None or expiry_date is None:
            errors.append({'sheet': sheet_name, 'row': x['_row'], 'message': '优惠日期格式应为 YYYY-MM-DD'})
        remind = _normalize_name(x.get('提前提醒天数', ''))
        try:
            remind_days = int(float(remind or 60))
        except Exception:
            remind_days = 60; errors.append({'sheet': sheet_name, 'row': x['_row'], 'message': '提前提醒天数必须是整数'})
        promotions.append({'business_id': bid, 'name': nm, 'start_date': start_date or '', 'expiry_date': expiry_date or '', 'remind_days': remind_days, 'status': _normalize_name(x.get('状态', '')) or 'active', 'notes': _normalize_name(x.get('备注', ''))})
    tasks = []
    for x in parse_named('待办', TASK_HEADERS):
        title = _normalize_name(x.get('待办事项', ''))
        if not title: continue
        done = _parse_yes_no(x.get('已完成', ''), False)
        remind = _normalize_date(x.get('提醒日期', ''))
        if remind is None: errors.append({'sheet': sheet_name, 'row': x['_row'], 'message': '待办提醒日期格式应为 YYYY-MM-DD'}); remind = ''
        tasks.append({'title': title, 'remind_date': remind or '', 'note': _normalize_name(x.get('备注', '')), 'done': bool(done)})
    visits = []
    for x in parse_named('跟进/拜访', VISIT_HEADERS):
        if not any(_normalize_name(x.get(h, '')) for h in VISIT_HEADERS): continue
        d = _normalize_date(x.get('日期', ''))
        if d is None: errors.append({'sheet': sheet_name, 'row': x['_row'], 'message': '跟进日期格式应为 YYYY-MM-DD'}); d = ''
        visits.append({'visit_date': d or '', 'kind': _normalize_name(x.get('类型', '')) or '拜访', 'result': _normalize_name(x.get('结果', '')), 'plan': _normalize_name(x.get('下一步计划', ''))})
    return {'customer': customer, 'entities': entities, 'invoices': invoices, 'businesses': businesses, 'contacts': contacts, 'promotions': promotions, 'tasks': tasks, 'visits': visits}, errors, warnings


def _validate_workbook(path: Path, filename: str) -> dict:
    errors, warnings, customers = [], [], []
    try:
        reader = XlsmReader(path)
    except Exception as exc:
        return {'version': '0.3.2-one-sheet', 'filename': filename, 'customers': [], 'errors': [{'sheet': '文件', 'row': 0, 'message': f'无法读取Excel：{exc}'}], 'warnings': [], 'summary': {'groups': 0, 'services': 0, 'contacts': 0, 'promotions': 0}, 'group_preview': []}
    with db() as conn:
        template, _ = _attr_signature(conn)
        if len(reader.sheets) > MAX_CUSTOMERS:
            errors.append({'sheet': '文件', 'row': 0, 'message': f'一个文件最多导入 {MAX_CUSTOMERS} 个客户'})
        seen_names, seen_codes, seen_tax = set(), set(), set()
        for sheet_name, sheet_path in reader.sheets[:MAX_CUSTOMERS]:
            parsed, sheet_errors, sheet_warnings = _parse_sheet(conn, sheet_name, reader.cells(sheet_path), template)
            errors.extend(sheet_errors); warnings.extend(sheet_warnings)
            if not parsed: continue
            c = parsed['customer']
            for value, seen, label in ((c['name'], seen_names, '客户名称'), (c['group_code'], seen_codes, '集团编码'), (c['tax_id'], seen_tax, '税号')):
                key = _normalize_name(value).casefold()
                if key and key in seen: errors.append({'sheet': sheet_name, 'row': 0, 'message': f'{label}在本Excel中重复：{value}'})
                elif key: seen.add(key)
            customers.append(parsed)
    groups = len(customers); services = sum(len(x['businesses']) for x in customers); contacts = sum(len(x['contacts']) for x in customers); promotions = sum(len(x['promotions']) for x in customers)
    preview = [{'import_id': x['customer']['sheet'], 'name': x['customer']['name'], 'group_code': x['customer']['group_code'], 'service_count': len(x['businesses']), 'contact_count': len(x['contacts']), 'promotion_count': len(x['promotions'])} for x in customers]
    return {'version': '0.3.2-one-sheet', 'filename': filename, 'customers': customers, 'errors': errors, 'warnings': warnings, 'summary': {'groups': groups, 'services': services, 'contacts': contacts, 'promotions': promotions}, 'group_preview': preview}


def _commit(payload: dict) -> dict:
    now, period = now_iso(), current_period()
    created_ids = []
    with db() as conn:
        _prepare_conn(conn)
        template, _ = _attr_signature(conn)
        valid_custom = {str(x['key']) for x in template if str(x['key']).startswith('custom_')}
        for unit in payload['customers']:
            c = unit['customer']
            existing, field = _existing_customer_conflict(conn, name=c['name'], group_code=c['group_code'], tax_id=c['tax_id'])
            if existing: raise ValueError(f'{field}已存在：{existing["name"]}')
        for unit in payload['customers']:
            c = unit['customer']
            cur = conn.execute('''INSERT INTO customers(name,group_code,tax_id,relation_summary,payment_enabled,payment_period,employee_own,employee_share,leased_own,leased_other,other_status,payment_display_attr_1,payment_display_attr_2,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (c['name'], c['group_code'], c['tax_id'], c['relation_summary'], 1 if c['payment_enabled'] else 0, period, c['employee_own'], c['employee_share'], c['leased_own'], c['leased_other'], c['other_status'], c['payment_display_attr_1'], c['payment_display_attr_2'], now, now))
            customer_id = int(cur.lastrowid); created_ids.append(customer_id)
            _save_template(conn, customer_id, c['mail_subject'], c['mail_body'], c['attachment_filename'])
            for x in unit['entities']: conn.execute('INSERT INTO customer_entities(customer_id,name,group_code,tax_id) VALUES(?,?,?,?)', (customer_id, x['name'], x['group_code'], x['tax_id']))
            invoice_map = {}
            for x in unit['invoices']:
                icur = conn.execute('INSERT INTO invoice_groups(customer_id,name,note,created_at) VALUES(?,?,?,?)', (customer_id, x['name'], x['note'], now)); invoice_map[x['name']] = int(icur.lastrowid)
            service_map = {}
            for index, x in enumerate(unit['businesses'], 1):
                attrs = x['attrs']
                invoice_name = attrs.get('invoice_group', '')
                invoice_id = invoice_map.get(invoice_name)
                interval = int(attrs.get('payment_interval_months') or 0)
                cycle = f'{interval}个月' if interval and interval != 1 else ('每月' if interval == 1 else '')
                values = {
                    'service_type': attrs.get('service_type', ''), 'holder_name': attrs.get('holder_name', ''), 'number': attrs.get('number', ''), 'account': attrs.get('account', ''),
                    'payment_method': attrs.get('payment_method', ''), 'invoice_type': attrs.get('invoice_type', ''), 'package_type': attrs.get('package_type', ''), 'last_payment_date': attrs.get('last_payment_date', ''), 'notes': attrs.get('notes', ''),
                }
                scur = conn.execute('''INSERT INTO services(customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,payment_cycle,payment_interval_months,next_payment_period,payment_method,invoice_type,package_type,last_payment_date,invoice_group_id,active_from_period,inactive_from_period,source_row,sort_order,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (customer_id, values['service_type'], values['holder_name'], values['number'], values['account'], x['amount'], 1 if x['mode']=='fixed' else 0, cycle, interval, x['next_payment_period'], values['payment_method'], values['invoice_type'], values['package_type'], values['last_payment_date'], invoice_id, x['active_from_period'], x['inactive_from_period'], x['source_row'], x['sort_order'] or index*10, values['notes']))
                sid = int(scur.lastrowid); service_map[x['business_id']] = sid
                for key, value in attrs.items():
                    if key in valid_custom:
                        conn.execute('INSERT OR REPLACE INTO service_custom_attributes(service_id,attr_key,value) VALUES(?,?,?)', (sid, key, str(value or '')))
                conn.execute('INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at) VALUES(?,?,?,?,?)', (sid, '1900-01', x['mode'], x['amount'] if x['mode']=='fixed' else 0, now))
                conn.execute('INSERT INTO payment_entries(service_id,period,amount,reference_amount,source,confirmed,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)', (sid, period, x['amount'], x['amount'], 'fixed' if x['mode']=='fixed' else 'imported', 1 if x['mode']=='fixed' else 0, now, now))
                runtime._save_runtime(conn, sid, status=x['runtime_status'], deferred_until_period=x['deferred_until_period'])
            for x in unit['contacts']: conn.execute('INSERT INTO contacts(customer_id,kind,name,relationship,phone) VALUES(?,?,?,?,?)', (customer_id, x['kind'], x['name'], x['relationship'], x['phone']))
            for x in unit['promotions']:
                if x['business_id'] in service_map: conn.execute('INSERT INTO promotions(service_id,name,start_date,expiry_date,remind_days,status,notes,created_at) VALUES(?,?,?,?,?,?,?,?)', (service_map[x['business_id']], x['name'], x['start_date'], x['expiry_date'], x['remind_days'], x['status'], x['notes'], now))
            for x in unit['tasks']: conn.execute('INSERT INTO tasks(customer_id,title,remind_date,note,done,created_at) VALUES(?,?,?,?,?,?)', (customer_id, x['title'], x['remind_date'], x['note'], 1 if x['done'] else 0, now))
            for x in unit['visits']: conn.execute('INSERT INTO visits(customer_id,visit_date,kind,result,plan,created_at) VALUES(?,?,?,?,?,?)', (customer_id, x['visit_date'], x['kind'], x['result'], x['plan'], now))
    return {'customers': len(created_ids), 'services': sum(len(x['businesses']) for x in payload['customers']), 'contacts': sum(len(x['contacts']) for x in payload['customers']), 'promotions': sum(len(x['promotions']) for x in payload['customers']), 'customer_ids': created_ids}


@router.get('/customers/import-template-v032-one-sheet.xlsx')
def download_one_sheet_template_v032():
    content = _build_blank_template()
    filename = '晨的助手_一客户一Sheet批量导入模板_v0.3.2.xlsx'
    return Response(content=content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': f"attachment; filename=chen-assistant-one-sheet-v032.xlsx; filename*=UTF-8''{quote(filename)}", 'Cache-Control': 'no-store'})


@router.get('/customers/export-v032.xlsx')
def export_all_customers_v032():
    content = _build_export()
    filename = f'晨的助手_全部客户_{datetime.now().strftime("%Y%m%d-%H%M")}.xlsx'
    return Response(content=content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': f"attachment; filename=chen-assistant-all-customers-v032.xlsx; filename*=UTF-8''{quote(filename)}", 'Cache-Control': 'no-store'})


@router.post('/customers/import-v032-one-sheet/preview', response_class=HTMLResponse)
async def preview_one_sheet_v032(request: Request, csrf: str = Form(...), excel_file: UploadFile = File(...)):
    try: require_csrf(request.state.session, csrf)
    except ValueError: raise HTTPException(403)
    filename = (excel_file.filename or '').strip()
    if not filename.lower().endswith('.xlsx'): return _render_new(request, mode='batch', error='目前只接受 .xlsx，请使用系统最新“一客户一Sheet”模板。')
    data = await excel_file.read(MAX_UPLOAD_BYTES + 1)
    if not data or len(data) > MAX_UPLOAD_BYTES: return _render_new(request, mode='batch', error='Excel文件为空或超过10MB，请拆分后再导入。')
    _cleanup_staging(); temp = _stage_dir() / f'upload-{secrets.token_urlsafe(12)}.xlsx'; temp.write_bytes(data)
    try:
        if not _zip_is_safe(temp): return _render_new(request, mode='batch', error='Excel文件结构异常或解压后过大。')
        preview = _validate_workbook(temp, filename)
    finally: temp.unlink(missing_ok=True)
    token = _stage(preview) if not preview['errors'] else ''
    return _render_new(request, mode='batch', preview=preview, token=token)


@router.post('/customers/import-v032-one-sheet/confirm', response_class=HTMLResponse)
def confirm_one_sheet_v032(request: Request, csrf: str = Form(...), import_token: str = Form(...)):
    try: require_csrf(request.state.session, csrf)
    except ValueError: raise HTTPException(403)
    payload = _load_stage(import_token)
    if payload.get('errors'): return _render_new(request, mode='batch', error='这份预览存在错误，不能确认导入。', preview=payload)
    try: result = _commit(payload)
    except ValueError as exc: return _render_new(request, mode='batch', error=f'导入前再次检查失败：{exc}', preview=payload)
    _delete_stage(import_token)
    return RedirectResponse(f"/customers/new?mode=batch&imported={result['customers']}&services={result['services']}&contacts={result['contacts']}&promotions={result['promotions']}", 303)
