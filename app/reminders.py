"""Single-account reminder bus and durable Web Push outbox.

Modules call publish_reminder inside their own db transaction. The worker never
needs a browser session and only sends to previously consented subscriptions.
"""
import asyncio
import base64
import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from . import config
from .db import db
from .legacy_main import templates, ctx
from .security import require_csrf, encrypt_secret, decrypt_secret

router = APIRouter()
log = logging.getLogger(__name__)
TYPES = {'customer': '客户管理', 'number_inbox': '未加号码', 'work_list': '清单',
         'task': '待办', 'windows': 'Windows Assistant', 'system': '系统提醒'}
SCHEMA = '''
CREATE TABLE IF NOT EXISTS reminder_preferences (
 kind TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS push_devices (
 id TEXT PRIMARY KEY, endpoint TEXT UNIQUE NOT NULL, subscription TEXT NOT NULL,
 name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
 created_at REAL NOT NULL, updated_at REAL NOT NULL, last_sent REAL,
 error TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS reminders (
 id INTEGER PRIMARY KEY AUTOINCREMENT, event_key TEXT UNIQUE NOT NULL,
 kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, url TEXT NOT NULL,
 created_at REAL NOT NULL, read_at REAL, resolved_at REAL);
CREATE TABLE IF NOT EXISTS push_outbox (
 reminder_id INTEGER REFERENCES reminders(id) ON DELETE CASCADE,
 device_id TEXT REFERENCES push_devices(id) ON DELETE CASCADE,
 state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
 next_at REAL NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0,
 error TEXT NOT NULL DEFAULT '', PRIMARY KEY(reminder_id,device_id));
CREATE INDEX IF NOT EXISTS idx_push_outbox_due ON push_outbox(state,next_at);
'''


def safe_url(value):
    if not isinstance(value, str) or not value.startswith('/') or value.startswith('//'):
        raise ValueError('提醒页面必须是站内路径')
    if any(c in value for c in ('\\', '\r', '\n', '\x00')) or len(value) > 500:
        raise ValueError('提醒页面路径无效')
    return value


def b64(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def ensure_reminder_schema():
    with db() as conn:
        conn.executescript(SCHEMA)
        conn.execute('BEGIN IMMEDIATE')
        for kind in ['all', *TYPES]:
            conn.execute('INSERT OR IGNORE INTO reminder_preferences(kind) VALUES(?)', (kind,))
        # Encrypted in the existing backed-up database, so deploys/restarts keep
        # the same application-server key. No private key is committed to Git.
        if not conn.execute("SELECT 1 FROM app_meta WHERE key='push_vapid_private'").fetchone():
            key = ec.generate_private_key(ec.SECP256R1())
            private = b64(key.private_numbers().private_value.to_bytes(32, 'big'))
            public = b64(key.public_key().public_bytes(serialization.Encoding.X962,
                          serialization.PublicFormat.UncompressedPoint))
            conn.executemany('INSERT INTO app_meta(key,value) VALUES(?,?)', [
                ('push_vapid_private', encrypt_secret(private)), ('push_vapid_public', public)])
        # Do not surprise users with historical number-submission notifications.
        if not conn.execute("SELECT 1 FROM app_meta WHERE key='push_number_baseline'").fetchone():
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='number_inbox'").fetchone()
            high = conn.execute('SELECT COALESCE(MAX(id),0) FROM number_inbox').fetchone()[0] if exists else 0
            conn.execute("INSERT INTO app_meta(key,value) VALUES('push_number_baseline',?)", (str(high),))


def preferences(conn):
    return {r['kind']: bool(r['enabled']) for r in conn.execute('SELECT * FROM reminder_preferences')}


def publish_reminder(conn, *, kind, title, body='', url='/', event_key):
    """Transactional, idempotent API shared by current and future modules."""
    if kind not in TYPES or not event_key or len(event_key) > 300:
        raise ValueError('提醒类型或事件标识无效')
    url = safe_url(url)
    if not title or len(title) > 100 or len(body) > 500:
        raise ValueError('提醒内容过长或标题为空')
    created = conn.execute('''INSERT OR IGNORE INTO reminders
        (event_key,kind,title,body,url,created_at) VALUES(?,?,?,?,?,?)''',
        (event_key,kind,title,body,url,time.time())).rowcount
    rid = conn.execute('SELECT id FROM reminders WHERE event_key=?', (event_key,)).fetchone()[0]
    if created:
        prefs = preferences(conn)
        if prefs.get('all', True) and prefs.get(kind, True):
            conn.execute('''INSERT OR IGNORE INTO push_outbox(reminder_id,device_id)
                SELECT ?,id FROM push_devices WHERE enabled=1''', (rid,))
    return rid


def due_timestamp(value):
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(value)
        if len(value) == 10:
            stamp = stamp.replace(hour=9)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
        return stamp.timestamp()
    except ValueError:
        return None


def collect_due(now=None):
    now = time.time() if now is None else now
    with db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        for row in conn.execute("SELECT * FROM tasks WHERE done=0 AND COALESCE(NULLIF(remind_at,''),remind_date,'')<>''").fetchall():
            value = row['remind_at'] or row['remind_date']
            due = due_timestamp(value)
            if due is not None and due <= now:
                publish_reminder(conn, kind='task', title='待办到期提醒', body=row['title'][:500],
                    url=f"/customers/{row['customer_id']}/tasks", event_key=f"task:{row['id']}:{value}")
        # Completion and changed reminder times invalidate stale queued pushes.
        for row in conn.execute("SELECT id,event_key FROM reminders WHERE kind='task' AND event_key LIKE 'task:%' AND resolved_at IS NULL").fetchall():
            parts = row['event_key'].split(':', 2)
            if len(parts) != 3 or not parts[1].isdigit():
                continue
            _, tid, value = parts
            task = conn.execute('SELECT * FROM tasks WHERE id=?', (tid,)).fetchone()
            if not task or task['done'] or (task['remind_at'] or task['remind_date']) != value:
                conn.execute('UPDATE reminders SET resolved_at=? WHERE id=?', (now,row['id']))
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='number_inbox'").fetchone():
            high = int(conn.execute("SELECT value FROM app_meta WHERE key='push_number_baseline'").fetchone()[0])
            rows = conn.execute('SELECT * FROM number_inbox WHERE id>? ORDER BY id', (high,)).fetchall()
            batches = {}
            for row in rows:
                if row['status'] == 'pending':
                    key = row['submit_batch'] or str(row['id'])
                    batches[key] = batches.get(key, 0) + 1
            for key, count in batches.items():
                publish_reminder(conn, kind='number_inbox', title='有新的未加号码',
                    body=f'本次新增 {count} 个号码，点击查看。', url='/work/number-inbox',
                    event_key=f'number-batch:{key}')
            if rows:
                conn.execute("UPDATE app_meta SET value=? WHERE key='push_number_baseline'", (str(rows[-1]['id']),))
            if not conn.execute("SELECT 1 FROM number_inbox WHERE status='pending'").fetchone():
                conn.execute("UPDATE reminders SET resolved_at=? WHERE kind='number_inbox' AND resolved_at IS NULL", (now,))


def validate_subscription(subscription):
    if not isinstance(subscription, dict):
        raise ValueError('订阅格式无效')
    endpoint = subscription.get('endpoint', '')
    if not isinstance(endpoint, str) or len(endpoint) > 2048:
        raise ValueError('推送地址无效')
    parsed = urlsplit(endpoint)
    host = parsed.hostname or ''
    allowed = host in {'fcm.googleapis.com', 'updates.push.services.mozilla.com',
                       'updates-autopush.stage.mozaws.net', 'web.push.apple.com'} or host.endswith('.push.apple.com')
    if parsed.scheme != 'https' or not allowed or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError('不支持此推送服务地址')
    keys = subscription.get('keys', {})
    for name, size in [('p256dh',65), ('auth',16)]:
        value = keys.get(name, '') if isinstance(keys, dict) else ''
        if not isinstance(value,str) or len(value)>200:
            raise ValueError('订阅密钥无效')
        try:
            raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
            if len(raw) != size:
                raise ValueError()
            if name == 'p256dh':
                ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
        except Exception as exc:
            raise ValueError('订阅密钥无效') from exc
    return {'endpoint': endpoint, 'keys': {k:keys[k] for k in ('p256dh','auth')}}


def unread_count(conn):
    return conn.execute('SELECT COUNT(*) FROM reminders WHERE read_at IS NULL AND resolved_at IS NULL').fetchone()[0]


def deliver_one(now=None, sender=None):
    from pywebpush import webpush, WebPushException
    now = time.time() if now is None else now
    sender = sender or webpush
    token = now + 120
    with db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('''SELECT o.*,r.kind,r.title,r.body,r.url,r.read_at,r.resolved_at,
            d.subscription,d.enabled FROM push_outbox o JOIN reminders r ON r.id=o.reminder_id
            JOIN push_devices d ON d.id=o.device_id
            WHERE o.state='pending' AND o.next_at<=? AND o.lease_until<=?
            ORDER BY o.reminder_id LIMIT 1''', (now,now)).fetchone()
        if not row:
            return False
        prefs = preferences(conn)
        if not row['enabled'] or not prefs.get('all',True) or not prefs.get(row['kind'],True) or row['read_at'] or row['resolved_at']:
            conn.execute("UPDATE push_outbox SET state='skipped' WHERE reminder_id=? AND device_id=?", (row['reminder_id'],row['device_id']))
            return True
        conn.execute('UPDATE push_outbox SET lease_until=?,attempts=attempts+1 WHERE reminder_id=? AND device_id=?',
                     (token,row['reminder_id'],row['device_id']))
        private = decrypt_secret(conn.execute("SELECT value FROM app_meta WHERE key='push_vapid_private'").fetchone()[0])
        payload = json.dumps({'title':row['title'], 'body':row['body'], 'url':row['url'],
                              'id':row['reminder_id'], 'unread_count':unread_count(conn)}, ensure_ascii=False)
    state, error, retry, expire = 'sent', '', 0, False
    try:
        # HTTPS subject works without requiring the user to configure an email.
        subject = os.getenv('WEB_PUSH_SUBJECT') or config.APP_BASE_URL or 'https://assistant.ziboxiaozhushou.cn'
        sender(subscription_info=json.loads(decrypt_secret(row['subscription'])), data=payload,
               vapid_private_key=private, vapid_claims={'sub':subject}, ttl=86400, timeout=10)
    except WebPushException as exc:
        status = getattr(exc.response, 'status_code', None)
        expire = status in (404,410)
        state = 'expired' if expire else ('failed' if row['attempts'] >= 7 else 'pending')
        error = f'推送服务响应 {status or "连接失败"}'
        retry = now + min(3600, 30 * 2 ** row['attempts'])
    except Exception:
        state = 'failed' if row['attempts'] >= 7 else 'pending'
        error = '推送连接失败，等待重试'
        retry = now + min(3600, 30 * 2 ** row['attempts'])
        log.warning('Web Push delivery failed for reminder %s', row['reminder_id'])
    with db() as conn:
        conn.execute('''UPDATE push_outbox SET state=?,error=?,next_at=?,lease_until=0
            WHERE reminder_id=? AND device_id=? AND lease_until=?''',
            (state,error,retry,row['reminder_id'],row['device_id'],token))
        conn.execute('UPDATE push_devices SET error=?,last_sent=CASE WHEN ?=\'sent\' THEN ? ELSE last_sent END, enabled=CASE WHEN ? THEN 0 ELSE enabled END WHERE id=?',
                     (error,state,now,int(expire),row['device_id']))
    return True


async def worker(stop):
    while not stop.is_set():
        try:
            await asyncio.to_thread(collect_due)
            for _ in range(20):
                if stop.is_set() or not await asyncio.to_thread(deliver_one):
                    break
        except Exception:
            log.exception('Reminder worker tick failed')
        try:
            await asyncio.wait_for(stop.wait(), timeout=15)
        except asyncio.TimeoutError:
            pass


@router.get('/reminders')
def reminder_page(request: Request):
    return templates.TemplateResponse('reminders.html', ctx(request))


@router.get('/api/reminders')
def reminder_state():
    with db() as conn:
        return {'types':TYPES, 'preferences':preferences(conn), 'unread_count':unread_count(conn),
            'public_key':conn.execute("SELECT value FROM app_meta WHERE key='push_vapid_public'").fetchone()[0],
            'devices':[dict(r) for r in conn.execute('SELECT id,name,enabled,created_at,updated_at,last_sent,error FROM push_devices ORDER BY created_at DESC')],
            'items':[dict(r) for r in conn.execute('SELECT * FROM reminders ORDER BY id DESC LIMIT 100')],
            'delivery':{r['state']:r['n'] for r in conn.execute('SELECT state,COUNT(*) n FROM push_outbox GROUP BY state')}}


async def check_csrf(request):
    if int(request.headers.get('content-length','0')) > 12000:
        raise HTTPException(413,'请求过大')
    try:
        payload = await request.json()
        require_csrf(request.state.session, request.headers.get('X-CSRF-Token',''))
        if not isinstance(payload,dict):
            raise ValueError()
    except Exception as exc:
        raise HTTPException(400,'请求或 CSRF 校验失败') from exc
    return payload


@router.post('/api/reminders/preferences')
async def save_preferences(request: Request):
    payload = await check_csrf(request)
    if not payload or any(k not in ['all',*TYPES] or type(v) is not bool for k,v in payload.items()):
        raise HTTPException(400,'提醒类型无效')
    with db() as conn:
        for k,v in payload.items():
            conn.execute('UPDATE reminder_preferences SET enabled=? WHERE kind=?',(int(v),k))
        # Turning off is immediate; turning back on does not flood old reminders.
        conn.execute('''UPDATE push_outbox SET state='skipped' WHERE state='pending' AND
            (0=(SELECT enabled FROM reminder_preferences WHERE kind='all') OR
             reminder_id IN (SELECT id FROM reminders WHERE kind IN
                (SELECT kind FROM reminder_preferences WHERE enabled=0)))''')
    return {'ok':True}


@router.post('/api/reminders/subscriptions')
async def subscribe(request: Request):
    payload = await check_csrf(request)
    try:
        subscription = validate_subscription(payload.get('subscription'))
    except (ValueError,TypeError) as exc:
        raise HTTPException(400,str(exc)) from exc
    name = str(payload.get('name','手机设备')).strip()[:60] or '手机设备'
    with db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        old = conn.execute('SELECT id FROM push_devices WHERE endpoint=?', (subscription['endpoint'],)).fetchone()
        did = old['id'] if old else secrets.token_urlsafe(18)
        if not old and conn.execute('SELECT COUNT(*) FROM push_devices').fetchone()[0] >= 30:
            raise HTTPException(400,'设备数量已达上限，请先移除旧设备')
        conn.execute('''INSERT INTO push_devices(id,endpoint,subscription,name,created_at,updated_at)
            VALUES(?,?,?,?,?,?) ON CONFLICT(endpoint) DO UPDATE SET subscription=excluded.subscription,
            name=excluded.name,enabled=1,updated_at=excluded.updated_at,error='' ''',
            (did,subscription['endpoint'],encrypt_secret(json.dumps(subscription)),name,time.time(),time.time()))
    return {'ok':True,'device_id':did}


@router.post('/api/reminders/devices/{device_id}')
async def change_device(request: Request,device_id: str):
    payload = await check_csrf(request)
    with db() as conn:
        if payload.get('delete') is True:
            conn.execute('DELETE FROM push_devices WHERE id=?',(device_id,))
        elif type(payload.get('enabled')) is bool:
            conn.execute('UPDATE push_devices SET enabled=? WHERE id=?',(int(payload['enabled']),device_id))
            if not payload['enabled']:
                conn.execute("UPDATE push_outbox SET state='skipped' WHERE device_id=? AND state='pending'",(device_id,))
        else:
            raise HTTPException(400,'设备操作无效')
    return {'ok':True}


@router.post('/api/reminders/test')
async def test_push(request: Request):
    payload = await check_csrf(request)
    did = payload.get('device_id')
    with db() as conn:
        if not preferences(conn).get('all') or not preferences(conn).get('system'):
            raise HTTPException(400,'请先开启通知总开关和系统提醒')
        if not conn.execute('SELECT 1 FROM push_devices WHERE id=? AND enabled=1',(did,)).fetchone():
            raise HTTPException(400,'请先在此设备开启手机提醒')
        if conn.execute("SELECT 1 FROM reminders WHERE event_key LIKE 'test:%' AND created_at>?",(time.time()-10,)).fetchone():
            raise HTTPException(429,'请稍后再发送测试提醒')
        rid = publish_reminder(conn,kind='system',title='手机提醒已连接',body='关闭网页后，也可以接收提醒。',url='/reminders',event_key='test:'+secrets.token_urlsafe(12))
        conn.execute('DELETE FROM push_outbox WHERE reminder_id=? AND device_id<>?',(rid,did))
    return {'ok':True,'reminder_id':rid,'message':'已加入推送队列，请留意手机通知'}


@router.post('/api/reminders/{reminder_id}/read')
async def mark_read(request: Request,reminder_id: int):
    await check_csrf(request)
    with db() as conn:
        conn.execute('UPDATE reminders SET read_at=? WHERE id=?',(time.time(),reminder_id))
    return {'ok':True}


@router.post('/api/reminders/events')
async def create_event(request: Request):
    payload = await check_csrf(request)
    try:
        with db() as conn:
            rid=publish_reminder(conn,kind=payload['kind'],title=payload['title'],body=payload.get('body',''),
                url=payload.get('url','/'),event_key=payload['event_key'])
    except (KeyError,ValueError,TypeError) as exc:
        raise HTTPException(400,'提醒格式无效') from exc
    return {'ok':True,'reminder_id':rid}


@router.post('/api/reminders/subscription-state')
async def subscription_state(request: Request):
    payload = await check_csrf(request)
    with db() as conn:
        row=conn.execute('SELECT id,enabled FROM push_devices WHERE endpoint=?',(str(payload.get('endpoint','')),)).fetchone()
    return {'device_id':row['id'] if row else None,'enabled':bool(row['enabled']) if row else False}


@router.get('/reminders/open/{reminder_id}')
def open_reminder(reminder_id: int):
    with db() as conn:
        row=conn.execute('SELECT url FROM reminders WHERE id=?',(reminder_id,)).fetchone()
        if not row:
            raise HTTPException(404,'提醒不存在')
        conn.execute('UPDATE reminders SET read_at=? WHERE id=?',(time.time(),reminder_id))
        target=safe_url(row['url'])
    return RedirectResponse(target,status_code=303)
