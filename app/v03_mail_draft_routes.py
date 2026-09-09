from __future__ import annotations

import os
from email.message import EmailMessage
from email.policy import SMTP

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import JSONResponse, Response

from .db import db, now_iso
from .payment_v02 import current_period
from .v025_routes import customer_or_404
from .v026_routes import check_csrf
from . import v03_routes as v03

router = APIRouter()


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


def _recipient() -> str:
    return _clean_header(os.getenv('PAYMENT_EMAIL_TO', ''))


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


def _build_eml(customer_name: str, period: str, subject: str, body: str, txt_content: str, recipient: str = '') -> bytes:
    msg = EmailMessage(policy=SMTP)
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
    return JSONResponse({
        'ok': True,
        'template': template,
        'recipient': _recipient(),
        'recipient_configured': bool(_recipient()),
    })


@router.post('/customers/{customer_id}/mail-template-v03')
def save_customer_mail_template_v03(
    request: Request,
    customer_id: int,
    csrf: str = Form(...),
    subject: str = Form(''),
    body: str = Form(''),
):
    check_csrf(request, csrf)
    with db() as conn:
        customer_or_404(conn, customer_id)
        template = _save_template(conn, customer_id, subject, body)
    return JSONResponse({
        'ok': True,
        'template': template,
        'recipient': _recipient(),
        'recipient_configured': bool(_recipient()),
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
        recipient=_recipient(),
    )
    filename = f'{_safe_filename(customer_name)}_{period}_Foxmail.eml'
    headers = {
        'Content-Disposition': f'attachment; filename="{filename.encode("utf-8").decode("latin1", errors="ignore")}"; filename*=UTF-8\'\'{filename}',
        'Cache-Control': 'no-store, max-age=0',
    }
    return Response(content=eml, media_type='message/rfc822', headers=headers)
