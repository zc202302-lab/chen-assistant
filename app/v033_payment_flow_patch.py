from __future__ import annotations

import base64
import hashlib
import math
from io import BytesIO
from urllib.parse import quote

import unicodedata

import xlsxwriter

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from .db import db, now_iso
from .payment_v02 import current_period, format_fee
from .v025_routes import customer_or_404
from .v026_routes import check_csrf
from . import v0212_routes as core
from . import v0211_routes as payment_workspace
from . import v028_routes as workspace
from . import v031_payment_workflow_routes as workflow
from .v03_mail_draft_routes import _build_eml, _clean_attachment_filename, _clean_header, _safe_filename

router = APIRouter()


def _ensure_customer_payment_template(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS customer_mail_templates_v03 (
               customer_id INTEGER PRIMARY KEY REFERENCES customers(id) ON DELETE CASCADE,
               recipient TEXT NOT NULL DEFAULT '',
               subject TEXT NOT NULL DEFAULT '',
               body TEXT NOT NULL DEFAULT '',
               attachment_filename TEXT NOT NULL DEFAULT '',
               excel_attachment_filename TEXT NOT NULL DEFAULT '',
               updated_at TEXT NOT NULL DEFAULT ''
           )"""
    )
    columns = {row['name'] for row in conn.execute('PRAGMA table_info(customer_mail_templates_v03)').fetchall()}
    if 'recipient' not in columns:
        conn.execute("ALTER TABLE customer_mail_templates_v03 ADD COLUMN recipient TEXT NOT NULL DEFAULT ''")
    if 'attachment_filename' not in columns:
        conn.execute("ALTER TABLE customer_mail_templates_v03 ADD COLUMN attachment_filename TEXT NOT NULL DEFAULT ''")
    if 'excel_attachment_filename' not in columns:
        conn.execute("ALTER TABLE customer_mail_templates_v03 ADD COLUMN excel_attachment_filename TEXT NOT NULL DEFAULT ''")


def _clean_recipient(value: str) -> str:
    value = _clean_header(value)
    if len(value) > 320:
        raise HTTPException(400, '收件人地址过长')
    if value:
        if '@' not in value or value.startswith('@') or value.endswith('@'):
            raise HTTPException(400, '收件人邮箱格式不正确')
    return value


def _get_customer_template(conn, customer_id: int) -> dict:
    _ensure_customer_payment_template(conn)
    row = conn.execute(
        """SELECT recipient,subject,body,attachment_filename,excel_attachment_filename,updated_at
           FROM customer_mail_templates_v03 WHERE customer_id=?""",
        (customer_id,),
    ).fetchone()
    if not row:
        return {'recipient': '', 'subject': '', 'body': '', 'attachment_filename': '', 'excel_attachment_filename': '', 'updated_at': ''}
    return {
        'recipient': row['recipient'] or '',
        'subject': row['subject'] or '',
        'body': row['body'] or '',
        'attachment_filename': row['attachment_filename'] or '',
        'excel_attachment_filename': row['excel_attachment_filename'] or '',
        'updated_at': row['updated_at'] or '',
    }


def _clean_excel_attachment_filename(value: str) -> str:
    name = (value or '').replace('\r', ' ').replace('\n', ' ').strip()
    if not name:
        return ''
    if len(name) > 160:
        raise HTTPException(400, 'EXCEL附件文件名不能超过160个字符')
    if any(ch in '/\\:*?"<>|' for ch in name):
        raise HTTPException(400, 'EXCEL附件文件名不能包含 / \\ : * ? " < > |')
    if name in {'.', '..'} or name.endswith('.'):
        raise HTTPException(400, 'EXCEL附件文件名无效')
    if not name.lower().endswith('.xlsx'):
        name += '.xlsx'
    return name


def _save_customer_template(conn, customer_id: int, recipient: str, subject: str, body: str, attachment_filename: str, excel_attachment_filename: str = '') -> dict:
    recipient = _clean_recipient(recipient)
    subject = _clean_header(subject)
    attachment_filename = _clean_attachment_filename(attachment_filename)
    excel_attachment_filename = _clean_excel_attachment_filename(excel_attachment_filename)
    if len(subject) > 300:
        raise HTTPException(400, '邮件主题不能超过300个字符')
    if len(body or '') > 10000:
        raise HTTPException(400, '邮件正文不能超过10000个字符')
    now = now_iso()
    _ensure_customer_payment_template(conn)
    conn.execute(
        """INSERT INTO customer_mail_templates_v03
           (customer_id,recipient,subject,body,attachment_filename,excel_attachment_filename,updated_at)
           VALUES(?,?,?,?,?,?,?)
           ON CONFLICT(customer_id) DO UPDATE SET
             recipient=excluded.recipient,
             subject=excluded.subject,
             body=excluded.body,
             attachment_filename=excluded.attachment_filename,
             excel_attachment_filename=excluded.excel_attachment_filename,
             updated_at=excluded.updated_at""",
        (customer_id, recipient, subject, body or '', attachment_filename, excel_attachment_filename, now),
    )
    return {
        'recipient': recipient,
        'subject': subject,
        'body': body or '',
        'attachment_filename': attachment_filename,
        'excel_attachment_filename': excel_attachment_filename,
        'updated_at': now,
    }


def _require_attachment_filename(template: dict) -> str:
    filename = _clean_attachment_filename(template.get('attachment_filename') or '')
    if not filename:
        raise HTTPException(400, '当前客户缴费模板未填写：TXT附件文件名。请先填写并保存缴费模板。')
    return filename


def _require_excel_attachment_filename(template: dict) -> str:
    filename = _clean_excel_attachment_filename(template.get('excel_attachment_filename') or '')
    if not filename:
        raise HTTPException(400, '当前客户缴费模板未填写：EXCEL附件文件名。请先填写并保存缴费模板。')
    return filename


def _require_template(template: dict) -> dict:
    missing = []
    if not (template.get('recipient') or '').strip(): missing.append('收件人')
    if not (template.get('subject') or '').strip(): missing.append('邮件主题')
    if not (template.get('attachment_filename') or '').strip(): missing.append('TXT附件文件名')
    if missing:
        raise HTTPException(400, '当前客户缴费模板未填写：' + '、'.join(missing))
    result = dict(template)
    result['attachment_filename'] = _require_attachment_filename(result)
    return result


def _current_payment_txt_content(conn, customer_id: int, period: str):
    """Build the formal payment TXT from the same reviewed rows used by the workbench.

    Every output line is derived from one payment snapshot item, keeping number and
    amount paired. Formal TXT generation rejects any positive row that is unreviewed,
    malformed or missing a number; it never silently drops a payable row.
    """
    customer = customer_or_404(conn, customer_id)
    items, stats = core.payment_snapshot_v0212(conn, customer_id, period)
    positive_items = []
    for item in items:
        amount = float(item['payment']['amount'] or 0)
        if not math.isfinite(amount) or amount < 0:
            raise HTTPException(409, '存在非法缴费金额，不能生成正式缴费TXT')
        if amount <= 0:
            continue
        positive_items.append(item)

    unconfirmed = [item for item in positive_items if not bool(item['payment']['confirmed'])]
    if stats['pending'] or unconfirmed:
        pending = max(int(stats.get('pending', 0)), len(unconfirmed))
        raise HTTPException(409, f"还有{pending}项金额未核对，不能生成正式缴费TXT")

    lines = []
    for item in positive_items:
        number = (item['row']['number'] or '').strip()
        if not number:
            raise HTTPException(409, '存在非0元缴费业务未填写号码，请先补充号码')
        if any(ch in number for ch in ('\r', '\n', '|')):
            raise HTTPException(409, f'缴费号码格式异常：{number!r}')
        amount = float(item['payment']['amount'] or 0)
        lines.append(f'{number}|{format_fee(amount)}')

    if not lines:
        raise HTTPException(409, '当前客户没有可生成TXT的非0元缴费数据')
    if len(lines) != len(positive_items):
        raise HTTPException(500, '缴费TXT生成完整性校验失败')

    body = '\r\n'.join(lines)
    # Parse back the final bytes before release. This locks the external contract to
    # exactly two fields per line and ensures row order/count survived formatting.
    parsed = [line.split('|') for line in body.split('\r\n')]
    if len(parsed) != len(positive_items) or any(len(parts) != 2 for parts in parsed):
        raise HTTPException(500, '缴费TXT格式校验失败')
    for parts, item in zip(parsed, positive_items):
        expected_number = (item['row']['number'] or '').strip()
        expected_amount = format_fee(float(item['payment']['amount'] or 0))
        if parts != [expected_number, expected_amount]:
            raise HTTPException(500, '缴费TXT号码与金额对应关系校验失败')
    return customer, body, stats


def _attachment_payload(conn, customer_id: int, period: str):
    customer, txt_content, stats = _current_payment_txt_content(conn, customer_id, period)
    template = _require_template(_get_customer_template(conn, customer_id))
    return customer, txt_content, stats, template


@router.get('/customers/{customer_id}/mail-template-v03')
def get_customer_payment_template_v033(customer_id: int):
    with db() as conn:
        customer_or_404(conn, customer_id)
        template = _get_customer_template(conn, customer_id)
    return JSONResponse({'ok': True, 'template': template, 'recipient': template['recipient'], 'recipient_configured': bool(template['recipient']), 'customer_scoped': True})


@router.post('/customers/{customer_id}/mail-template-v03')
def save_customer_payment_template_v033(request: Request, customer_id: int, csrf: str = Form(...), subject: str = Form(''), body: str = Form(''), recipient: str = Form(''), attachment_filename: str = Form(''), excel_attachment_filename: str = Form('')):
    check_csrf(request, csrf)
    with db() as conn:
        customer_or_404(conn, customer_id)
        template = _save_customer_template(conn, customer_id, recipient, subject, body, attachment_filename, excel_attachment_filename)
    return JSONResponse({'ok': True, 'template': template, 'recipient': template['recipient'], 'recipient_configured': bool(template['recipient']), 'customer_scoped': True})


@router.get('/customers/{customer_id}/payment.txt')
def payment_txt_current_workflow_v033(customer_id: int):
    period = current_period()
    with db() as conn:
        _, body, _ = _current_payment_txt_content(conn, customer_id, period)
        filename = _require_attachment_filename(_get_customer_template(conn, customer_id))
    headers = {
        'Content-Disposition': f"attachment; filename=\"payment.txt\"; filename*=UTF-8''{quote(filename)}",
        'Cache-Control': 'no-store, max-age=0',
    }
    return PlainTextResponse(body, media_type='text/plain; charset=utf-8', headers=headers)


def _current_payment_display_table(conn, customer_id: int, period: str):
    customer_or_404(conn, customer_id)
    items, stats = core.payment_snapshot_v0212(conn, customer_id, period)
    if stats['pending']:
        raise HTTPException(409, f"还有{stats['pending']}项金额未核对，不能生成正式缴费EXCEL")

    # Excel 必须严格复用“缴费工作区”当前实际显示列，而不是旧版的
    # payment_display_attr_1 / payment_display_attr_2 两属性设置。
    template = workspace._template(conn)
    columns = payment_workspace._payment_columns(conn, customer_id, template)
    headers = [column['label'] for column in columns]

    service_ids = [int(item['row']['id']) for item in items]
    custom = workspace._custom_map(conn, service_ids)
    services = conn.execute(
        '''SELECT s.*,g.name invoice_group_name FROM services s
           LEFT JOIN invoice_groups g ON g.id=s.invoice_group_id
           WHERE s.customer_id=?''',
        (customer_id,),
    ).fetchall()
    full_by_id = {int(row['id']): row for row in services}

    rows = []
    for item in items:
        amount = float(item['payment']['amount'] or 0)
        if amount <= 0:
            continue
        service = full_by_id.get(int(item['row']['id']), item['row'])
        cells = payment_workspace._payment_cells(
            service,
            custom[int(service['id'])],
            template,
            columns,
            item['payment'],
            item.get('delta'),
        )
        row = []
        for cell in cells:
            if cell['key'] == payment_workspace.PAYMENT_AMOUNT_KEY:
                row.append(amount)
            else:
                # 与网页一致：空值在页面显示为“—”，Excel 也保持相同可见内容。
                row.append(cell.get('value') or '—')
        rows.append(row)

    if not rows:
        raise HTTPException(409, '当前客户没有可生成EXCEL的非0元缴费数据')
    return headers, rows


def _excel_display_width(value) -> int:
    text = '' if value is None else str(value)
    width = 0
    for char in text:
        width += 2 if unicodedata.east_asian_width(char) in {'W', 'F'} else 1
    return width


def _payment_xlsx_bytes(headers: list[str], rows: list[list]) -> bytes:
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    worksheet = workbook.add_worksheet('缴费')

    # 用户要求导出保持“纯数据”：不套表格样式、不冻结窗格、不加颜色或边框。
    # 只根据实际内容调整列宽，并给数据行一个舒适的默认行高。
    all_rows = [headers, *rows]
    worksheet.set_default_row(20)
    for col, header in enumerate(headers):
        values = [row[col] for row in all_rows if col < len(row)]
        width = min(max(10, max((_excel_display_width(value) for value in values), default=0) + 2), 36)
        worksheet.set_column(col, col, width)
        worksheet.write_string(0, col, str(header))
    for row_index, row in enumerate(rows, start=1):
        for col, value in enumerate(row):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                worksheet.write_number(row_index, col, float(value))
            else:
                worksheet.write_string(row_index, col, '' if value is None else str(value))

    workbook.close()
    return output.getvalue()


@router.get('/customers/{customer_id}/payment.xlsx')
def payment_xlsx_current_workflow_v158(customer_id: int):
    period = current_period()
    with db() as conn:
        headers, rows = _current_payment_display_table(conn, customer_id, period)
        filename = _require_excel_attachment_filename(_get_customer_template(conn, customer_id))
    response_headers = {
        'Content-Disposition': f"attachment; filename=\"payment.xlsx\"; filename*=UTF-8''{quote(filename)}",
        'Cache-Control': 'no-store, max-age=0',
    }
    return Response(
        content=_payment_xlsx_bytes(headers, rows),
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers=response_headers,
    )

@router.get('/customers/{customer_id}/payment-mail-compose-v031')
def payment_mail_compose_customer_scoped_v033(customer_id: int):
    period = current_period()
    with db() as conn:
        run, _ = workflow._run_v031(conn, customer_id, period)
        if not run['notified']:
            raise HTTPException(400, '请先完成“通知客户”，再调用邮箱')
        _, txt_content, _, template = _attachment_payload(conn, customer_id, period)
    attachment_bytes = txt_content.encode('utf-8')
    attachment_sha256 = hashlib.sha256(attachment_bytes).hexdigest()
    return JSONResponse({
        'ok': True,
        'recipient_b64': base64.b64encode(template['recipient'].encode('utf-8')).decode('ascii'),
        'subject_b64': base64.b64encode(template['subject'].encode('utf-8')).decode('ascii'),
        'body_b64': base64.b64encode(template['body'].encode('utf-8')).decode('ascii'),
        'attachment_filename_b64': base64.b64encode(template['attachment_filename'].encode('utf-8')).decode('ascii'),
        'attachment_content_base64': base64.b64encode(attachment_bytes).decode('ascii'),
        'attachment_sha256': attachment_sha256,
        'attachment_line_count': len(txt_content.split('\r\n')),
        'period': period, 'customer_scoped': True, 'attachment_required': True,
    })


@router.get('/customers/{customer_id}/payment-mail-draft-v03')
def payment_mail_draft_customer_scoped_v033(customer_id: int):
    period = current_period()
    with db() as conn:
        run, _ = workflow._run_v031(conn, customer_id, period)
        if not run['notified']:
            raise HTTPException(400, '请先完成“通知客户”，再调用邮箱')
        customer, txt_content, _, template = _attachment_payload(conn, customer_id, period)
    eml = _build_eml(
        customer_name=customer['name'] or '客户', period=period,
        subject=template['subject'], body=template['body'], txt_content=txt_content,
        recipient=template['recipient'], txt_filename=template['attachment_filename'],
    )
    filename = f"{_safe_filename(customer['name'] or '客户')}_{period}_缴费邮件.eml"
    headers = {
        'Content-Disposition': f"attachment; filename=payment.eml; filename*=UTF-8''{quote(filename)}",
        'Cache-Control': 'no-store, max-age=0',
    }
    return Response(content=eml, media_type='message/rfc822', headers=headers)
