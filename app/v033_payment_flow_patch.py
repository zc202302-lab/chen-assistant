from __future__ import annotations

import base64
from io import BytesIO
from urllib.parse import quote

import xlsxwriter

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from .db import db, now_iso
from .payment_v02 import current_period, format_fee
from .v025_routes import customer_or_404
from .v026_routes import check_csrf
from . import v0212_routes as core
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
               updated_at TEXT NOT NULL DEFAULT ''
           )"""
    )
    columns = {row['name'] for row in conn.execute('PRAGMA table_info(customer_mail_templates_v03)').fetchall()}
    if 'recipient' not in columns:
        conn.execute("ALTER TABLE customer_mail_templates_v03 ADD COLUMN recipient TEXT NOT NULL DEFAULT ''")
    if 'attachment_filename' not in columns:
        conn.execute("ALTER TABLE customer_mail_templates_v03 ADD COLUMN attachment_filename TEXT NOT NULL DEFAULT ''")


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
        """SELECT recipient,subject,body,attachment_filename,updated_at
           FROM customer_mail_templates_v03 WHERE customer_id=?""",
        (customer_id,),
    ).fetchone()
    if not row:
        return {'recipient': '', 'subject': '', 'body': '', 'attachment_filename': '', 'updated_at': ''}
    return {
        'recipient': row['recipient'] or '',
        'subject': row['subject'] or '',
        'body': row['body'] or '',
        'attachment_filename': row['attachment_filename'] or '',
        'updated_at': row['updated_at'] or '',
    }


def _save_customer_template(conn, customer_id: int, recipient: str, subject: str, body: str, attachment_filename: str) -> dict:
    recipient = _clean_recipient(recipient)
    subject = _clean_header(subject)
    attachment_filename = _clean_attachment_filename(attachment_filename)
    if len(subject) > 300:
        raise HTTPException(400, '邮件主题不能超过300个字符')
    if len(body or '') > 10000:
        raise HTTPException(400, '邮件正文不能超过10000个字符')
    now = now_iso()
    _ensure_customer_payment_template(conn)
    conn.execute(
        """INSERT INTO customer_mail_templates_v03
           (customer_id,recipient,subject,body,attachment_filename,updated_at)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(customer_id) DO UPDATE SET
             recipient=excluded.recipient,
             subject=excluded.subject,
             body=excluded.body,
             attachment_filename=excluded.attachment_filename,
             updated_at=excluded.updated_at""",
        (customer_id, recipient, subject, body or '', attachment_filename, now),
    )
    return {'recipient': recipient, 'subject': subject, 'body': body or '', 'attachment_filename': attachment_filename, 'updated_at': now}


def _require_attachment_filename(template: dict) -> str:
    filename = _clean_attachment_filename(template.get('attachment_filename') or '')
    if not filename:
        raise HTTPException(400, '当前客户缴费模板未填写：TXT附件文件名。请先填写并保存缴费模板。')
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
    customer = customer_or_404(conn, customer_id)
    items, stats = core.payment_snapshot_v0212(conn, customer_id, period)
    if stats['pending']:
        raise HTTPException(409, f"还有{stats['pending']}项金额未核对，不能生成正式缴费TXT")
    missing_number = [item for item in items if float(item['payment']['amount'] or 0) > 0 and not (item['row']['number'] or '').strip()]
    if missing_number:
        raise HTTPException(409, '存在非0元缴费业务未填写号码，请先补充号码')
    lines = []
    for item in items:
        amount = float(item['payment']['amount'] or 0)
        number = (item['row']['number'] or '').strip()
        if amount > 0 and number:
            lines.append(f'{number}|{format_fee(amount)}')
    if not lines:
        raise HTTPException(409, '当前客户没有可生成TXT的非0元缴费数据')
    return customer, '\r\n'.join(lines), stats


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
def save_customer_payment_template_v033(request: Request, customer_id: int, csrf: str = Form(...), subject: str = Form(''), body: str = Form(''), recipient: str = Form(''), attachment_filename: str = Form('')):
    check_csrf(request, csrf)
    with db() as conn:
        customer_or_404(conn, customer_id)
        template = _save_customer_template(conn, customer_id, recipient, subject, body, attachment_filename)
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


def _payment_xlsx_filename(txt_filename: str) -> str:
    base = txt_filename[:-4] if txt_filename.lower().endswith('.txt') else txt_filename
    return f'{base}.xlsx'


def _current_payment_display_table(conn, customer_id: int, period: str):
    customer_or_404(conn, customer_id)
    items, stats = core.payment_snapshot_v0212(conn, customer_id, period)
    if stats['pending']:
        raise HTTPException(409, f"还有{stats['pending']}项金额未核对，不能生成正式缴费EXCEL")

    template = workspace._template(conn)
    payment_columns = core._payment_columns(conn, customer_id, template)
    service_ids = [int(item['row']['id']) for item in items]
    custom = workspace._custom_map(conn, service_ids)
    services = conn.execute(
        '''SELECT s.*,g.name invoice_group_name FROM services s
           LEFT JOIN invoice_groups g ON g.id=s.invoice_group_id
           WHERE s.customer_id=?''',
        (customer_id,),
    ).fetchall()
    full_by_id = {int(row['id']): row for row in services}

    headers = [column['label'] for column in payment_columns]
    rows = []
    for item in items:
        amount = float(item['payment']['amount'] or 0)
        if amount <= 0:
            continue
        service = full_by_id.get(int(item['row']['id']), item['row'])
        cells = core._payment_cells(
            service,
            custom[int(service['id'])],
            template,
            payment_columns,
            item['payment'],
            item.get('delta'),
        )
        rows.append([
            amount if cell['key'] == 'payment_amount' else cell['value']
            for cell in cells
        ])
    if not rows:
        raise HTTPException(409, '当前客户没有可生成EXCEL的非0元缴费数据')
    return headers, rows


def _payment_xlsx_bytes(headers: list[str], rows: list[list]) -> bytes:
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    worksheet = workbook.add_worksheet('缴费')
    worksheet.write_row(0, 0, headers)
    for row_index, row in enumerate(rows, 1):
        worksheet.write_row(row_index, 0, row)

    # Keep the export deliberately plain. Only size populated rows and columns
    # so identifiers and values remain readable without adding table styling.
    worksheet.set_default_row(20)
    worksheet.set_row(0, 22)
    for column_index, header in enumerate(headers):
        values = [header, *(row[column_index] for row in rows)]
        width = max(len(str(value or '')) for value in values) + 2
        worksheet.set_column(column_index, column_index, max(10, min(width, 36)))
    workbook.close()
    return output.getvalue()


@router.get('/customers/{customer_id}/payment.xlsx')
def payment_xlsx_current_workflow_v156(customer_id: int):
    period = current_period()
    with db() as conn:
        headers, rows = _current_payment_display_table(conn, customer_id, period)
        filename = _payment_xlsx_filename(
            _require_attachment_filename(_get_customer_template(conn, customer_id))
        )
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
    return JSONResponse({
        'ok': True,
        'recipient_b64': base64.b64encode(template['recipient'].encode('utf-8')).decode('ascii'),
        'subject_b64': base64.b64encode(template['subject'].encode('utf-8')).decode('ascii'),
        'body_b64': base64.b64encode(template['body'].encode('utf-8')).decode('ascii'),
        'attachment_filename_b64': base64.b64encode(template['attachment_filename'].encode('utf-8')).decode('ascii'),
        'attachment_content_base64': base64.b64encode(txt_content.encode('utf-8')).decode('ascii'),
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
