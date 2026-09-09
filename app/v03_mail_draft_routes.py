from __future__ import annotations

import base64
import os
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import parseaddr
from urllib.parse import quote

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import JSONResponse, Response

from .db import db, now_iso
from .payment_v02 import current_period
from .v025_routes import customer_or_404, service_or_404
from .v026_routes import check_csrf
from .v027_routes import _meta_get, _meta_set
from .v028_routes import _template
from . import v0212_routes as core
from . import v0212_business_display_routes as business_display
from . import v03_routes as v03

router = APIRouter()
RECIPIENT_META_KEY = 'payment_mail_recipient_v03'


def _ensure_mail_templates(conn):
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS customer_mail_templates_v03 (
               customer_id INTEGER PRIMARY KEY REFERENCES customers(id) ON DELETE CASCADE,
               subject TEXT NOT NULL DEFAULT '',
               body TEXT NOT NULL DEFAULT '',
               updated_at TEXT NOT NULL DEFAULT ''
           )'''
    )


def _clean_header(value: str) -> str:
    return ' '.join((value or '').replace('\r', ' ').replace('\n', ' ').split()).strip()


def _recipient(conn) -> str:
    # Once the UI has saved this setting, even an intentionally blank value wins.
    stored = _meta_get(conn, RECIPIENT_META_KEY, None)
    if stored is not None:
        return _clean_header(stored)
    # Keep PAYMENT_EMAIL_TO only as a backwards-compatible first-run fallback.
    return _clean_header(os.getenv('PAYMENT_EMAIL_TO', ''))


def _save_recipient(conn, recipient: str) -> str:
    recipient = _clean_header(recipient)
    if len(recipient) > 320:
        raise HTTPException(400, '收件人地址过长')
    if recipient:
        _, address = parseaddr(recipient)
        if not address or '@' not in address or address.startswith('@') or address.endswith('@'):
            raise HTTPException(400, '收件人邮箱格式不正确')
    _meta_set(conn, RECIPIENT_META_KEY, recipient)
    return recipient


def _get_template(conn, customer_id: int):
    _ensure_mail_templates(conn)
    row = conn.execute(
        'SELECT subject,body,updated_at FROM customer_mail_templates_v03 WHERE customer_id=?',
        (customer_id,),
    ).fetchone()
    if not row:
        return {'subject': '', 'body': '', 'updated_at': ''}
    return {
        'subject': row['subject'] or '',
        'body': row['body'] or '',
        'updated_at': row['updated_at'] or '',
    }


def _save_template(conn, customer_id: int, subject: str, body: str):
    subject = _clean_header(subject)
    if len(subject) > 300:
        raise HTTPException(400, '邮件主题不能超过300个字符')
    if len(body or '') > 10000:
        raise HTTPException(400, '邮件正文不能超过10000个字符')
    now = now_iso()
    _ensure_mail_templates(conn)
    conn.execute(
        '''INSERT INTO customer_mail_templates_v03(customer_id,subject,body,updated_at)
           VALUES(?,?,?,?)
           ON CONFLICT(customer_id) DO UPDATE SET
             subject=excluded.subject,
             body=excluded.body,
             updated_at=excluded.updated_at''',
        (customer_id, subject, body or '', now),
    )
    return {'subject': subject, 'body': body or '', 'updated_at': now}


def _safe_filename(value: str) -> str:
    cleaned = ''.join(ch if ch not in '/\\:*?"<>|' else '_' for ch in (value or ''))
    cleaned = cleaned.strip().strip('.')
    return cleaned[:80] or '客户'


def _b64_text(value: str) -> str:
    return base64.b64encode((value or '').encode('utf-8')).decode('ascii')


def _build_eml(customer_name: str, period: str, subject: str, body: str, txt_content: str, recipient: str = '') -> bytes:
    msg = EmailMessage(policy=SMTP)
    # X-Unsent is recognized by many Windows mail clients as an editable draft.
    msg['X-Unsent'] = '1'
    if recipient:
        msg['To'] = recipient
    msg['Subject'] = _clean_header(subject)
    msg.set_content(body or '', subtype='plain', charset='utf-8')
    txt_name = f'{_safe_filename(customer_name)}_{period}_缴费.txt'
    msg.add_attachment(
        txt_content.encode('utf-8'),
        maintype='text',
        subtype='plain',
        filename=txt_name,
    )
    return msg.as_bytes()


@router.get('/customers/{customer_id}/mail-template-v03')
def get_customer_mail_template_v03(customer_id: int):
    with db() as conn:
        customer_or_404(conn, customer_id)
        template = _get_template(conn, customer_id)
        recipient = _recipient(conn)
    return JSONResponse({
        'ok': True,
        'template': template,
        'recipient': recipient,
        'recipient_configured': bool(recipient),
    })


@router.post('/customers/{customer_id}/mail-template-v03')
def save_customer_mail_template_v03(
    request: Request,
    customer_id: int,
    csrf: str = Form(...),
    subject: str = Form(''),
    body: str = Form(''),
    recipient: str = Form(''),
):
    check_csrf(request, csrf)
    with db() as conn:
        customer_or_404(conn, customer_id)
        template = _save_template(conn, customer_id, subject, body)
        saved_recipient = _save_recipient(conn, recipient)
    return JSONResponse({
        'ok': True,
        'template': template,
        'recipient': saved_recipient,
        'recipient_configured': bool(saved_recipient),
    })


@router.get('/customers/{customer_id}/payment-mail-compose-v03')
def payment_mail_compose_v03(customer_id: int):
    """Return an ASCII-safe payload for the local Windows helper.

    All human-readable strings are base64 encoded so the PowerShell 5.1 helper
    never has to parse non-ASCII request bytes through its tiny HTTP server.
    """
    period = current_period()
    with db() as conn:
        customer, txt_content, stats = v03._payment_txt_content(conn, customer_id, period)
        run = v03._payment_run_v03(conn, customer_id, period, stats)
        if not run['paid']:
            raise HTTPException(400, '请先完成本月缴费，再调用Foxmail')
        template = _get_template(conn, customer_id)
        recipient = _recipient(conn)

    subject = _clean_header(template['subject'])
    if not subject:
        raise HTTPException(400, '请先为这个客户保存邮件主题')

    customer_name = customer['name'] or '客户'
    txt_name = f'{_safe_filename(customer_name)}_{period}_缴费.txt'
    return JSONResponse({
        'ok': True,
        'recipient_b64': _b64_text(recipient),
        'subject_b64': _b64_text(subject),
        'body_b64': _b64_text(template['body']),
        'attachment_filename_b64': _b64_text(txt_name),
        'attachment_content_base64': base64.b64encode(txt_content.encode('utf-8')).decode('ascii'),
        'period': period,
    })


@router.get('/customers/{customer_id}/payment-mail-draft-v03')
def download_payment_mail_draft_v03(customer_id: int):
    period = current_period()
    with db() as conn:
        customer, txt_content, stats = v03._payment_txt_content(conn, customer_id, period)
        run = v03._payment_run_v03(conn, customer_id, period, stats)
        if not run['paid']:
            raise HTTPException(400, '请先完成本月缴费，再生成Foxmail邮件草稿')
        template = _get_template(conn, customer_id)
        recipient = _recipient(conn)

    subject = _clean_header(template['subject'])
    if not subject:
        raise HTTPException(400, '请先为这个客户保存邮件主题')

    customer_name = customer['name'] or '客户'
    eml = _build_eml(
        customer_name=customer_name,
        period=period,
        subject=subject,
        body=template['body'],
        txt_content=txt_content,
        recipient=recipient,
    )
    filename = f'{_safe_filename(customer_name)}_{period}_Foxmail.eml'
    headers = {
        'Content-Disposition': f"attachment; filename=payment.eml; filename*=UTF-8''{quote(filename)}",
        'Cache-Control': 'no-store, max-age=0',
    }
    return Response(content=eml, media_type='message/rfc822', headers=headers)


# These two endpoints shadow the older v0.3 implementations so that any business
# row refresh caused by status changes uses the CURRENT CUSTOMER'S display order.
@router.post('/services/{service_id}/status-v03')
def save_service_status_customer_display_v03(
    request: Request,
    service_id: int,
    csrf: str = Form(...),
    status: str = Form(...),
):
    check_csrf(request, csrf)
    if status not in {'active', 'inactive'}:
        raise HTTPException(400, '业务状态无效')

    with db() as conn:
        service = service_or_404(conn, service_id)
        customer_id = int(service['customer_id'])
        core._save_runtime(conn, service_id, status=status)
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), customer_id))
        template = _template(conn)
        ordered = business_display._ordered_keys(conn, template, customer_id)
        rows = business_display._customer_rows_payload(conn, customer_id, template, ordered)
        runtime = core._runtime_for(conn, service_id)
        state = core._schedule_state(service, runtime, current_period())

    return JSONResponse({'ok': True, 'status': status, 'schedule_state': state, 'rows': rows})


@router.post('/services/{service_id}/payment-status-v03')
def save_payment_status_customer_display_v03(
    request: Request,
    service_id: int,
    csrf: str = Form(...),
    mode: str = Form(...),
):
    check_csrf(request, csrf)
    if mode != 'normal':
        raise HTTPException(400, '当前业务页仅支持恢复正常缴费周期')

    period = current_period()
    with db() as conn:
        service = service_or_404(conn, service_id)
        customer_id = int(service['customer_id'])
        before = core._runtime_for(conn, service_id)
        core._save_runtime(conn, service_id, deferred_until_period='')
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), customer_id))

        refreshed_service = service_or_404(conn, service_id)
        runtime = core._runtime_for(conn, service_id)
        state = core._schedule_state(refreshed_service, runtime, period)
        due = core._service_due(refreshed_service, runtime, period)
        template = _template(conn)
        ordered = business_display._ordered_keys(conn, template, customer_id)
        rows = business_display._customer_rows_payload(conn, customer_id, template, ordered)

    return JSONResponse({
        'ok': True,
        'service_id': service_id,
        'mode': 'normal',
        'changed': bool((before.get('deferred_until_period') or '').strip()),
        'deferred_until_period': '',
        'schedule_state': state,
        'due': bool(due),
        'rows': rows,
    })
