"""Promotion positions, free-text dates and the shared table/export projection."""
from collections import defaultdict
from datetime import date
from io import BytesIO
import re

from fastapi import HTTPException
import xlsxwriter

from .db import db

HEADERS = ['号码'] + [label for slot in range(1, 6) for label in (f'优惠{slot}', '到期时间')]


def ensure_promotion_schema(conn=None):
    if conn is None:
        with db() as owned:
            ensure_promotion_schema(owned)
        return
    columns = {r['name'] for r in conn.execute('PRAGMA table_info(promotions)')}
    if 'slot_number' not in columns:
        conn.execute('ALTER TABLE promotions ADD COLUMN slot_number INTEGER')
    # Existing records keep stable IDs and names. Missing positions get the next
    # free position, never renumbering positions explicitly assigned by a user.
    rows = conn.execute("SELECT id,service_id,slot_number,status FROM promotions ORDER BY id").fetchall()
    used = defaultdict(set)
    for row in rows:
        if row['slot_number'] and (row['status'] or 'active') == 'active':
            used[row['service_id']].add(row['slot_number'])
    for row in rows:
        if row['slot_number'] is not None:
            continue
        slot = next(n for n in range(1, len(rows) + 2) if n not in used[row['service_id']])
        conn.execute('UPDATE promotions SET slot_number=? WHERE id=?', (slot, row['id']))
        if (row['status'] or 'active') == 'active':
            used[row['service_id']].add(slot)


def expiry_text(value):
    return value or ''


def expiry_day(value):
    """Recognize complete numeric dates for reminders without rewriting input."""
    match = re.fullmatch(r'\s*(\d{4})[/-](\d{1,2})[/-](\d{1,2})\s*', value or '')
    if match:
        try:
            return date(*map(int, match.groups()))
        except ValueError:
            pass
    return None


def available_slot(conn, service_id, requested='', promotion_id=None):
    ensure_promotion_schema(conn)
    rows = conn.execute("SELECT id,slot_number FROM promotions WHERE service_id=? AND COALESCE(status,'active')='active'", (service_id,)).fetchall()
    used = {r['slot_number'] for r in rows if r['id'] != promotion_id}
    if requested == '' or requested is None:
        existing = next((r['slot_number'] for r in rows if r['id'] == promotion_id), None)
        if existing:
            return existing
        slot = next((n for n in range(1, 6) if n not in used), None)
        if slot is None:
            raise HTTPException(400, '该业务的优惠1～5已全部占用')
        return slot
    try:
        slot = int(requested)
    except (ValueError, TypeError):
        raise HTTPException(400, '优惠编号须为1～5')
    if not 1 <= slot <= 5:
        raise HTTPException(400, '优惠编号须为1～5')
    if slot in used:
        raise HTTPException(400, f'优惠{slot}已存在，请选择空闲编号')
    return slot


def table_payload(conn, customer_id):
    ensure_promotion_schema(conn)
    services = conn.execute('''SELECT id,number FROM services WHERE customer_id=?
        ORDER BY CASE WHEN COALESCE(sort_order,0)>0 THEN sort_order ELSE 100000000+id END,id''', (customer_id,)).fetchall()
    promotions = conn.execute('''SELECT p.* FROM promotions p JOIN services s ON s.id=p.service_id
        WHERE s.customer_id=? AND COALESCE(p.status,'active')='active' ORDER BY p.slot_number,p.id''', (customer_id,)).fetchall()
    grouped = defaultdict(list)
    for promo in promotions:
        grouped[promo['service_id']].append(promo)
    rows = []
    service_ids = []
    for service in services:
        if not grouped[service['id']]:
            continue
        cells = [service['number'] or ''] + [''] * 10
        for promo in grouped[service['id']]:
            # Legacy records beyond five must remain visible, rather than be
            # silently dropped. Keep their text on separate lines in column 5.
            slot = min(max(promo['slot_number'] or 1, 1), 5)
            index = slot * 2 - 1
            for offset, value in enumerate((promo['name'] or '', expiry_text(promo['expiry_date']))):
                target = index + offset
                cells[target] = cells[target] + '\n' + value if cells[target] else value
        rows.append(cells)
        service_ids.append(service['id'])
    return {'headers': HEADERS, 'rows': rows, 'service_ids': service_ids}


def export_table(payload):
    stream = BytesIO()
    workbook = xlsxwriter.Workbook(stream, {'in_memory': True, 'strings_to_formulas': False, 'strings_to_urls': False})
    sheet = workbook.add_worksheet('全量优惠')
    header = workbook.add_format({'bold': True, 'bg_color': '#EDF2F8', 'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 11})
    text = workbook.add_format({'num_format': '@', 'align': 'center', 'valign': 'vcenter', 'font_size': 11})
    for row_index, row in enumerate([payload['headers'], *payload['rows']]):
        for col_index, value in enumerate(row):
            sheet.write_string(row_index, col_index, value, header if row_index == 0 else text)
        sheet.set_row(row_index, 22)
    sheet.set_column(0, 10, 18)
    sheet.freeze_panes(1, 1)
    workbook.close()
    return stream.getvalue()
