from __future__ import annotations

from datetime import date
from email.message import EmailMessage
import os
import smtplib
import ssl
from pathlib import Path

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import JSONResponse

from .db import db, now_iso
from .payment_v02 import current_period, add_periods, service_interval_months, format_fee
from .v025_routes import customer_or_404, service_or_404
from .v026_routes import check_csrf
from .v028_routes import _template
from . import v0212_routes as core
from . import v0212_business_display_routes as business_display

router = APIRouter()
APP_VERSION = '0.3'


def _has_column(conn, table: str, column: str) -> bool:
    return any(row['name'] == column for row in conn.execute(f'PRAGMA table_info({table})').fetchall())


def _ensure_v03(conn):
    if not _has_column(conn, 'customer_payment_runs', 'reviewed_at'):
        conn.execute("ALTER TABLE customer_payment_runs ADD COLUMN reviewed_at TEXT DEFAULT ''")
    if not _has_column(conn, 'customer_payment_runs', 'emailed_at'):
        conn.execute("ALTER TABLE customer_payment_runs ADD COLUMN emailed_at TEXT DEFAULT ''")
    if not _has_column(conn, 'customer_payment_runs', 'email_to'):
        conn.execute("ALTER TABLE customer_payment_runs ADD COLUMN email_to TEXT DEFAULT ''")
    if not _has_column(conn, 'customer_payment_runs', 'email_subject'):
        conn.execute("ALTER TABLE customer_payment_runs ADD COLUMN email_subject TEXT DEFAULT ''")

    # Existing v0.2 runs that already reached notification/payment are logically reviewed.
    conn.execute(
        """UPDATE customer_payment_runs
           SET reviewed_at=CASE
             WHEN COALESCE(reviewed_at,'')<>'' THEN reviewed_at
             WHEN COALESCE(notified_at,'')<>'' THEN notified_at
             WHEN COALESCE(paid_at,'')<>'' THEN paid_at
             ELSE '' END"""
    )

    conn.execute(
        '''CREATE TABLE IF NOT EXISTS payment_run_service_snapshots_v03 (
               run_id INTEGER NOT NULL REFERENCES customer_payment_runs(id) ON DELETE CASCADE,
               service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
               last_payment_date TEXT NOT NULL DEFAULT '',
               next_payment_period TEXT NOT NULL DEFAULT '',
               deferred_until_period TEXT NOT NULL DEFAULT '',
               PRIMARY KEY(run_id, service_id)
           )'''
    )
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS payment_email_logs_v03 (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
               period TEXT NOT NULL,
               recipient TEXT NOT NULL DEFAULT '',
               subject TEXT NOT NULL DEFAULT '',
               status TEXT NOT NULL DEFAULT '',
               error TEXT NOT NULL DEFAULT '',
               created_at TEXT NOT NULL
           )'''
    )
    conn.execute('CREATE INDEX IF NOT EXISTS idx_payment_email_logs_v03_customer ON payment_email_logs_v03(customer_id,period,id)')


def _payment_run_v03(conn, customer_id: int, period: str, stats):
    _ensure_v03(conn)
    row = conn.execute(
        'SELECT * FROM customer_payment_runs WHERE customer_id=? AND period=?',
        (customer_id, period),
    ).fetchone()
    if not row:
        now = now_iso()
        conn.execute(
            '''INSERT INTO customer_payment_runs
               (customer_id,period,reviewed_at,notified_at,paid_at,emailed_at,email_to,email_subject,created_at,updated_at)
               VALUES(?,?,\'\',\'\',\'\',\'\',\'\',\'\',?,?)''',
            (customer_id, period, now, now),
        )
        row = conn.execute(
            'SELECT * FROM customer_payment_runs WHERE customer_id=? AND period=?',
            (customer_id, period),
        ).fetchone()

    ready = int(stats.get('pending', 0)) == 0
    reviewed = bool((row['reviewed_at'] or '').strip())
    notified = bool((row['notified_at'] or '').strip())
    paid = bool((row['paid_at'] or '').strip())
    emailed = bool((row['emailed_at'] or '').strip())

    if paid:
        stage = 'paid'
        label = '已完成缴费'
    elif notified:
        stage = 'notified'
        label = '已通知客户，待完成缴费'
    elif reviewed:
        stage = 'reviewed'
        label = '金额已核对，待通知客户'
    elif ready:
        stage = 'ready'
        label = '金额可确认'
    else:
        stage = 'checking'
        label = '正在核对金额'

    return {
        'id': int(row['id']),
        'stage': stage,
        'label': label,
        'ready': ready,
        'reviewed': reviewed,
        'notified': notified,
        'paid': paid,
        'emailed': emailed,
        'reviewed_at': row['reviewed_at'],
        'notified_at': row['notified_at'],
        'paid_at': row['paid_at'],
        'emailed_at': row['emailed_at'],
        'email_to': row['email_to'],
        'email_subject': row['email_subject'],
    }


# The v0.2.12 workspace resolves this module-global name at request time.
core._payment_run = _payment_run_v03


def _mail_settings():
    host = os.getenv('SMTP_HOST', '').strip()
    username = os.getenv('SMTP_USERNAME', '').strip()
    password = os.getenv('SMTP_PASSWORD', '')
    sender = os.getenv('SMTP_FROM', '').strip() or username
    recipient = os.getenv('PAYMENT_EMAIL_TO', '').strip()
    subject_template = os.getenv('PAYMENT_EMAIL_SUBJECT_TEMPLATE', '缴费资料-{customer_name}-{period}').strip()
    try:
        port = int(os.getenv('SMTP_PORT', '465').strip() or '465')
    except ValueError:
        port = 465
    use_ssl = os.getenv('SMTP_USE_SSL', '1').strip() == '1'
    starttls = os.getenv('SMTP_STARTTLS', '0' if use_ssl else '1').strip() == '1'
    configured = bool(host and sender and recipient and (not username or password))
    return {
        'host': host,
        'port': port,
        'username': username,
        'password': password,
        'sender': sender,
        'recipient': recipient,
        'subject_template': subject_template,
        'use_ssl': use_ssl,
        'starttls': starttls,
        'configured': configured,
    }


def _subject_for(settings, customer_name: str, period: str) -> str:
    values = {
        'customer_name': customer_name,
        'period': period,
        'period_slash': period.replace('-', '/'),
    }
    try:
        return settings['subject_template'].format(**values)
    except (KeyError, ValueError):
        return f'缴费资料-{customer_name}-{period}'


def _payment_txt_content(conn, customer_id: int, period: str):
    customer = customer_or_404(conn, customer_id)
    items, stats = core.payment_snapshot_v0212(conn, customer_id, period)
    if stats['pending']:
        raise HTTPException(400, f"还有 {stats['pending']} 项金额未核对，暂不能生成缴费TXT")
    lines = []
    for item in items:
        amount = float(item['payment']['amount'] or 0)
        if abs(amount) < 0.005:
            continue
        number = (item['row']['number'] or '').strip()
        lines.append(f'{number}|{format_fee(amount)}')
    return customer, '\n'.join(lines), stats


def _mail_status(run):
    settings = _mail_settings()
    customer_name = run.get('customer_name', '')
    period = run.get('period', current_period())
    return {
        'configured': settings['configured'],
        'recipient': settings['recipient'],
        'subject_preview': _subject_for(settings, customer_name, period) if customer_name else '',
        'sent': bool(run.get('emailed')),
        'sent_at': run.get('emailed_at', ''),
    }


@router.get('/health')
def health_v03():
    return {'ok': True, 'version': APP_VERSION}


@router.get('/customers/{customer_id}/payment-run-v03')
def get_payment_run_v03(customer_id: int):
    period = current_period()
    with db() as conn:
        customer = customer_or_404(conn, customer_id)
        _, stats = core.payment_snapshot_v0212(conn, customer_id, period)
        run = _payment_run_v03(conn, customer_id, period, stats)
    settings = _mail_settings()
    mail = {
        'configured': settings['configured'],
        'recipient': settings['recipient'],
        'subject_preview': _subject_for(settings, customer['name'], period),
        'sent': run['emailed'],
        'sent_at': run['emailed_at'],
    }
    return JSONResponse({'ok': True, 'run': run, 'stats': stats, 'mail': mail})


@router.post('/customers/{customer_id}/payment-run')
def set_payment_run_v03(
    request: Request,
    customer_id: int,
    csrf: str = Form(...),
    action: str = Form(...),
):
    check_csrf(request, csrf)
    period = current_period()
    now = now_iso()

    with db() as conn:
        customer_or_404(conn, customer_id)
        items, stats = core.payment_snapshot_v0212(conn, customer_id, period)
        run = _payment_run_v03(conn, customer_id, period, stats)
        run_id = run['id']

        if action == 'review':
            if run['reviewed']:
                if run['notified'] or run['paid']:
                    return JSONResponse({'ok': False, 'error': '请先撤回后续步骤，再取消金额核对'}, status_code=409)
                conn.execute('UPDATE customer_payment_runs SET reviewed_at=\'\',updated_at=? WHERE id=?', (now, run_id))
            else:
                if stats['pending']:
                    return JSONResponse({'ok': False, 'error': f"还有 {stats['pending']} 项金额未核对"}, status_code=400)
                conn.execute('UPDATE customer_payment_runs SET reviewed_at=?,updated_at=? WHERE id=?', (now, now, run_id))

        elif action == 'notify':
            if run['notified']:
                if run['paid']:
                    return JSONResponse({'ok': False, 'error': '请先撤回“完成缴费”，再撤回通知客户'}, status_code=409)
                conn.execute('UPDATE customer_payment_runs SET notified_at=\'\',updated_at=? WHERE id=?', (now, run_id))
                conn.execute(
                    'UPDATE customers SET payment_period=?,notified=0,completed=0,updated_at=? WHERE id=?',
                    (period, now, customer_id),
                )
            else:
                if stats['pending']:
                    return JSONResponse({'ok': False, 'error': f"还有 {stats['pending']} 项金额未核对"}, status_code=400)
                if not run['reviewed']:
                    return JSONResponse({'ok': False, 'error': '请先完成“金额核对”'}, status_code=400)
                conn.execute('UPDATE customer_payment_runs SET notified_at=?,updated_at=? WHERE id=?', (now, now, run_id))
                conn.execute(
                    'UPDATE customers SET payment_period=?,notified=1,completed=0,updated_at=? WHERE id=?',
                    (period, now, customer_id),
                )

        elif action == 'paid':
            if run['paid']:
                snapshots = conn.execute(
                    '''SELECT * FROM payment_run_service_snapshots_v03
                       WHERE run_id=? ORDER BY service_id''',
                    (run_id,),
                ).fetchall()
                for snap in snapshots:
                    conn.execute(
                        'UPDATE services SET last_payment_date=?,next_payment_period=? WHERE id=?',
                        (snap['last_payment_date'], snap['next_payment_period'], snap['service_id']),
                    )
                    core._save_runtime(
                        conn,
                        int(snap['service_id']),
                        deferred_until_period=snap['deferred_until_period'],
                    )
                conn.execute('DELETE FROM payment_run_service_snapshots_v03 WHERE run_id=?', (run_id,))
                conn.execute(
                    '''UPDATE customer_payment_runs
                       SET paid_at='',emailed_at='',email_to='',email_subject='',updated_at=? WHERE id=?''',
                    (now, run_id),
                )
                conn.execute(
                    'UPDATE customers SET payment_period=?,notified=1,completed=0,updated_at=? WHERE id=?',
                    (period, now, customer_id),
                )
            else:
                if stats['pending']:
                    return JSONResponse({'ok': False, 'error': f"还有 {stats['pending']} 项金额未核对"}, status_code=400)
                if not run['reviewed'] or not run['notified']:
                    return JSONResponse({'ok': False, 'error': '请依次完成“金额核对”和“通知客户”'}, status_code=400)

                conn.execute('DELETE FROM payment_run_service_snapshots_v03 WHERE run_id=?', (run_id,))
                today_iso = date.today().isoformat()
                for item in items:
                    service = item['row']
                    runtime = core._runtime_for(conn, int(service['id']))
                    conn.execute(
                        '''INSERT INTO payment_run_service_snapshots_v03
                           (run_id,service_id,last_payment_date,next_payment_period,deferred_until_period)
                           VALUES(?,?,?,?,?)''',
                        (
                            run_id,
                            service['id'],
                            (service['last_payment_date'] or '').strip(),
                            (service['next_payment_period'] or '').strip(),
                            (runtime.get('deferred_until_period') or '').strip(),
                        ),
                    )
                    months = service_interval_months(service)
                    next_period = add_periods(period, months) if months and months > 1 else ''
                    conn.execute(
                        'UPDATE services SET last_payment_date=?,next_payment_period=? WHERE id=?',
                        (today_iso, next_period, service['id']),
                    )
                    core._save_runtime(conn, int(service['id']), deferred_until_period='')

                conn.execute('UPDATE customer_payment_runs SET paid_at=?,updated_at=? WHERE id=?', (now, now, run_id))
                conn.execute(
                    'UPDATE customers SET payment_period=?,notified=1,completed=1,updated_at=? WHERE id=?',
                    (period, now, customer_id),
                )
        else:
            raise HTTPException(400, '状态操作无效')

        _, stats2 = core.payment_snapshot_v0212(conn, customer_id, period)
        updated = _payment_run_v03(conn, customer_id, period, stats2)

    return JSONResponse({'ok': True, 'run': updated, 'stats': stats2})


@router.post('/services/{service_id}/status-v03')
def save_service_status_v03(
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
        ordered = business_display._ordered_keys(conn, template)
        rows = business_display._customer_rows_payload(conn, customer_id, template, ordered)
        runtime = core._runtime_for(conn, service_id)
        state = core._schedule_state(service, runtime, current_period())

    return JSONResponse({'ok': True, 'status': status, 'schedule_state': state, 'rows': rows})


@router.get('/api/v03/customers/search')
def customer_search_v03(q: str = ''):
    q = q.strip()
    with db() as conn:
        if not q:
            rows = conn.execute(
                'SELECT id,name,group_code,tax_id FROM customers ORDER BY updated_at DESC LIMIT 8'
            ).fetchall()
        else:
            like = f'%{q}%'
            rows = conn.execute(
                '''SELECT DISTINCT c.id,c.name,c.group_code,c.tax_id
                   FROM customers c
                   LEFT JOIN services s ON s.customer_id=c.id
                   LEFT JOIN contacts k ON k.customer_id=c.id
                   WHERE c.name LIKE ? OR c.group_code LIKE ? OR c.tax_id LIKE ?
                      OR s.number LIKE ? OR s.account LIKE ? OR s.holder_name LIKE ?
                      OR k.name LIKE ? OR k.phone LIKE ?
                   ORDER BY CASE WHEN c.name LIKE ? THEN 0 WHEN c.group_code LIKE ? THEN 1 ELSE 2 END,
                            c.updated_at DESC
                   LIMIT 15''',
                (like, like, like, like, like, like, like, like, like, like),
            ).fetchall()

        results = []
        for row in rows:
            hint = ''
            if q:
                like = f'%{q}%'
                service = conn.execute(
                    '''SELECT number,account,holder_name FROM services
                       WHERE customer_id=? AND (number LIKE ? OR account LIKE ? OR holder_name LIKE ?)
                       ORDER BY CASE WHEN number LIKE ? THEN 0 WHEN account LIKE ? THEN 1 ELSE 2 END,id LIMIT 1''',
                    (row['id'], like, like, like, like, like),
                ).fetchone()
                if service:
                    if q in (service['number'] or ''):
                        hint = f"号码 {service['number']}"
                    elif q in (service['account'] or ''):
                        hint = f"账号 {service['account']}"
                    elif service['holder_name']:
                        hint = f"姓名 {service['holder_name']}"
                if not hint:
                    contact = conn.execute(
                        'SELECT name,phone FROM contacts WHERE customer_id=? AND (name LIKE ? OR phone LIKE ?) LIMIT 1',
                        (row['id'], like, like),
                    ).fetchone()
                    if contact:
                        hint = ' · '.join(x for x in (contact['name'], contact['phone']) if x)
            if not hint:
                hint = (row['group_code'] or row['tax_id'] or '').strip()
            results.append({
                'id': int(row['id']),
                'name': row['name'],
                'group_code': row['group_code'] or '',
                'tax_id': row['tax_id'] or '',
                'hint': hint,
            })
    return JSONResponse({'ok': True, 'q': q, 'results': results})


@router.post('/customers/{customer_id}/payment-email-v03')
def send_payment_email_v03(
    request: Request,
    customer_id: int,
    csrf: str = Form(...),
):
    check_csrf(request, csrf)
    period = current_period()
    settings = _mail_settings()
    if not settings['configured']:
        return JSONResponse(
            {
                'ok': False,
                'error': '邮件尚未配置。请在服务器 .env 中设置 SMTP_HOST / SMTP_PORT / SMTP_USERNAME / SMTP_PASSWORD / SMTP_FROM / PAYMENT_EMAIL_TO。',
            },
            status_code=400,
        )

    with db() as conn:
        customer, content, stats = _payment_txt_content(conn, customer_id, period)
        run = _payment_run_v03(conn, customer_id, period, stats)
        if not run['paid']:
            return JSONResponse({'ok': False, 'error': '请先完成本月缴费，再发送邮件'}, status_code=400)
        customer_name = customer['name']
        run_id = run['id']

    subject = _subject_for(settings, customer_name, period)
    safe_name = ''.join(ch if ch not in '/\\:*?"<>|' else '_' for ch in customer_name).strip() or '客户'
    filename = f'{safe_name}_{period}_缴费.txt'

    msg = EmailMessage()
    msg['From'] = settings['sender']
    msg['To'] = settings['recipient']
    msg['Subject'] = subject
    msg.set_content(f'{customer_name} {period.replace("-", "/")} 缴费TXT见附件。')
    msg.add_attachment(content.encode('utf-8'), maintype='text', subtype='plain', filename=filename)

    error_text = ''
    try:
        if settings['use_ssl']:
            with smtplib.SMTP_SSL(settings['host'], settings['port'], timeout=20, context=ssl.create_default_context()) as smtp:
                if settings['username']:
                    smtp.login(settings['username'], settings['password'])
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(settings['host'], settings['port'], timeout=20) as smtp:
                smtp.ehlo()
                if settings['starttls']:
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                if settings['username']:
                    smtp.login(settings['username'], settings['password'])
                smtp.send_message(msg)
    except Exception as exc:
        error_text = f'{type(exc).__name__}: {str(exc)[:180]}'

    with db() as conn:
        _ensure_v03(conn)
        conn.execute(
            '''INSERT INTO payment_email_logs_v03(customer_id,period,recipient,subject,status,error,created_at)
               VALUES(?,?,?,?,?,?,?)''',
            (
                customer_id,
                period,
                settings['recipient'],
                subject,
                'failed' if error_text else 'sent',
                error_text,
                now_iso(),
            ),
        )
        if not error_text:
            now = now_iso()
            conn.execute(
                '''UPDATE customer_payment_runs
                   SET emailed_at=?,email_to=?,email_subject=?,updated_at=? WHERE id=?''',
                (now, settings['recipient'], subject, now, run_id),
            )

    if error_text:
        return JSONResponse({'ok': False, 'error': f'邮件发送失败：{error_text}'}, status_code=502)
    return JSONResponse({
        'ok': True,
        'recipient': settings['recipient'],
        'subject': subject,
        'filename': filename,
        'message': '缴费TXT已通过邮件发送',
    })
