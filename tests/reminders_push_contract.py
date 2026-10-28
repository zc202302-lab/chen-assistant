"""Isolated integration tests; no real push service or production data touched."""
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
tmp = tempfile.TemporaryDirectory()
os.environ.update(APP_DB_PATH=str(Path(tmp.name)/'app.db'),APP_USERNAME='push-test',
    APP_PASSWORD_SALT='dGVzdHNhbHQ=',APP_PASSWORD_HASH='x',APP_SESSION_SECRET='push-test',
    APP_ENCRYPTION_KEY=Fernet.generate_key().decode(),APP_SECURE_COOKIE='0')
from fastapi.testclient import TestClient
from app.main import app
from app.db import init_db, db, now_iso
from app.security import create_session, decrypt_secret, password_hash
from app.reminders import ensure_reminder_schema,publish_reminder,collect_due,deliver_one,due_timestamp,b64,vapid_subject,push_error
from app.v162_number_inbox import ensure_number_inbox_schema
from pywebpush import WebPushException


def main():
    init_db()
    with db() as conn: ensure_number_inbox_schema(conn)
    ensure_reminder_schema()
    client=TestClient(app)
    assert client.get('/api/reminders',follow_redirects=False).status_code==303
    token,csrf,_=create_session();client.cookies.set('session_token',token)
    headers={'X-CSRF-Token':csrf}
    assert client.post('/api/reminders/preferences',json={'all':False}).status_code==400
    assert client.get('/reminders').status_code==200
    assert client.get('/sw.js').headers['service-worker-allowed']=='/'
    manifest=client.get('/manifest.webmanifest').json()
    assert manifest['id']=='/' and manifest['scope']=='/' and manifest['display']=='standalone'
    public=client.get('/api/reminders').json()['public_key'];ensure_reminder_schema()
    assert client.get('/api/reminders').json()['public_key']==public
    key=ec.generate_private_key(ec.SECP256R1())
    subscription={'endpoint':'https://web.push.apple.com/test-endpoint', 'keys':{
        'auth':b64(os.urandom(16)), 'p256dh':b64(key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint))}}
    for endpoint in ['http://127.0.0.1/push','https://web.push.apple.com.evil.test/push','https://user@web.push.apple.com/push']:
        assert client.post('/api/reminders/subscriptions',headers=headers,json={'subscription':subscription|{'endpoint':endpoint}}).status_code==400
    response=client.post('/api/reminders/subscriptions',headers=headers,json={'subscription':subscription,'name':'测试 iPhone'})
    assert response.status_code==200,response.text
    device=response.json()['device_id']
    assert client.post('/api/reminders/subscriptions',headers=headers,json={'subscription':subscription}).json()['device_id']==device
    with db() as conn:
        stored=conn.execute('SELECT subscription FROM push_devices').fetchone()[0]
        assert subscription['keys']['auth'] not in stored
        assert json.loads(decrypt_secret(stored))==subscription
    def publish(_):
        with db() as conn:
            return publish_reminder(conn,kind='customer',title='测试提醒',url='/work',event_key='same-event')
    with ThreadPoolExecutor(max_workers=4) as pool: assert len(set(pool.map(publish,range(8))))==1
    with db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM reminders').fetchone()[0]==1
        assert conn.execute('SELECT COUNT(*) FROM push_outbox').fetchone()[0]==1
    # Use real library encryption and VAPID signing, replacing only HTTP transport.
    from requests import Response
    response=Response();response.status_code=201;response._content=b''
    with patch('requests.post',return_value=response) as transport:
        assert deliver_one()
        kwargs=transport.call_args.kwargs
        assert kwargs['headers']['content-encoding']=='aes128gcm'
        assert 'authorization' in {k.lower() for k in kwargs['headers']}
        assert kwargs['headers']['Urgency']=='high'
        assert isinstance(kwargs['data'],bytes) and '测试'.encode() not in kwargs['data']
    assert not deliver_one()
    with db() as conn:
        publish_reminder(conn,kind='system',title='重试',event_key='retry',url='/reminders')
    now=time.time()
    def fail(**kw): raise RuntimeError('no network')
    assert deliver_one(now=now,sender=fail)
    assert not deliver_one(now=now+1,sender=lambda **kw:None)
    # Schema setup models restart: the retry and key remain intact.
    ensure_reminder_schema()
    assert deliver_one(now=now+31,sender=lambda **kw:None)
    with db() as conn: publish_reminder(conn,kind='system',title='过期',event_key='expired')
    def expired(**kw):
        r=Response();r.status_code=410;raise WebPushException('gone',response=r)
    assert deliver_one(now=now+60,sender=expired)
    assert not client.get('/api/reminders').json()['devices'][0]['enabled']
    client.post('/api/reminders/devices/'+device,headers=headers,json={'enabled':True})
    assert client.post('/api/reminders/events',headers=headers,json={'kind':'task','title':'bad','event_key':'bad','url':'//evil.test'}).status_code==400
    with db() as conn:
        cid=conn.execute('INSERT INTO customers(name,created_at,updated_at) VALUES(?,?,?)',('回归客户',now_iso(),now_iso())).lastrowid
        tid=conn.execute('INSERT INTO tasks(customer_id,title,remind_at,created_at) VALUES(?,?,?,?)',(cid,'待办内容','2020-01-01T12:00',now_iso())).lastrowid
        conn.execute("INSERT INTO number_inbox(number,normalized_number,submitted_at,submit_batch) VALUES('13800138000','13800138000',?,'batch-test')",(now_iso(),))
        conn.execute("INSERT INTO number_inbox(number,normalized_number,submitted_at,submit_batch) VALUES('13800138001','13800138001',?,'batch-test')",(now_iso(),))
    collect_due();collect_due()
    state=client.get('/api/reminders').json()
    assert len([r for r in state['items'] if r['event_key'].startswith('task:')])==1
    assert len([r for r in state['items'] if r['kind']=='number_inbox'])==1
    assert '2 个号码' in next(r['body'] for r in state['items'] if r['kind']=='number_inbox')
    # Keep notifications active across batches until the entire inbox is done.
    with db() as conn:
        conn.execute("UPDATE number_inbox SET status='done',completed_at=? WHERE submit_batch='batch-test'",(now_iso(),))
        conn.execute("INSERT INTO number_inbox(number,normalized_number,submitted_at,submit_batch) VALUES('13800138002','13800138002',?,'batch-next')",(now_iso(),))
    collect_due()
    refreshed=client.get('/api/reminders').json()
    assert any(r['event_key']=='number-batch:batch-test' for r in refreshed['items'])
    assert any(r['event_key']=='number-batch:batch-next' for r in refreshed['items'])
    with db() as conn:
        conn.execute("UPDATE number_inbox SET status='done',completed_at=? WHERE submit_batch='batch-next'",(now_iso(),))
    collect_due()
    refreshed=client.get('/api/reminders').json()
    assert not any(r['kind']=='number_inbox' for r in refreshed['items'])
    with db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM reminders WHERE kind='number_inbox' AND resolved_at IS NULL").fetchone()[0] == 0
        assert conn.execute("""SELECT COUNT(*) FROM push_outbox o JOIN reminders r ON r.id=o.reminder_id
            WHERE r.kind='number_inbox' AND o.state='pending'""").fetchone()[0] == 0
    assert due_timestamp('2026-10-02')==due_timestamp('2026-10-02T09:00:00+08:00')
    with db() as conn: conn.execute('UPDATE tasks SET done=1 WHERE id=?',(tid,))
    collect_due()
    sent=[]
    while deliver_one(now=now+100,sender=lambda **kw:sent.append(json.loads(kw['data']))): pass
    assert not any(r['title']=='待办到期提醒' for r in sent)
    client.post('/api/reminders/preferences',headers=headers,json={'all':False})
    with db() as conn: publish_reminder(conn,kind='work_list',title='清单提醒',event_key='disabled')
    assert not deliver_one(now=now+200,sender=lambda **kw:None)
    assert client.post('/api/reminders/test',headers=headers,json={'device_id':device}).status_code==400
    client.post('/api/reminders/preferences',headers=headers,json={'all':True})
    assert client.post('/api/reminders/test',headers=headers,json={'device_id':device,'delay':True}).status_code==400
    assert client.post('/api/reminders/test',headers=headers,json={'device_id':device,'delay':20}).status_code==200
    assert client.post('/api/reminders/test',headers=headers,json={'device_id':device}).status_code==429
    scheduled=client.get('/api/reminders').json()['test_deliveries'][0]
    assert scheduled['state']=='pending' and scheduled['attempts']==0
    assert not deliver_one(now=time.time()+1,sender=lambda **kw:None)
    assert deliver_one(now=time.time()+21,sender=lambda **kw:None)
    assert client.get('/api/reminders').json()['test_deliveries'][0]['state']=='sent'
    # Provider errors are useful without leaking raw response content or tokens.
    rejected=Response();rejected.status_code=403;rejected._content=b'{"reason":"BadJwtToken","secret":"must-not-leak"}'
    error=push_error(WebPushException('private endpoint',response=rejected))
    assert '403' in error and 'VAPID' in error and 'must-not-leak' not in error
    from app import config
    with patch.object(config,'APP_BASE_URL','http://127.0.0.1:8010'), patch.dict(os.environ,{'WEB_PUSH_SUBJECT':''}):
        assert vapid_subject()=='https://assistant.ziboxiaozhushou.cn'
    rid=client.get('/api/reminders').json()['items'][0]['id']
    before=client.get('/api/reminders').json()['unread_count']
    client.post(f'/api/reminders/{rid}/read',headers=headers,json={})
    assert client.get('/api/reminders').json()['unread_count']==before-1
    client.post('/api/reminders/devices/'+device,headers=headers,json={'delete':True})
    assert not client.get('/api/reminders').json()['devices']
    opened=client.get(f'/reminders/open/{rid}',follow_redirects=False)
    assert opened.status_code==303 and opened.headers['location']=='/reminders'
    guest=TestClient(app)
    redirect=guest.get(f'/reminders/open/{rid}',follow_redirects=False)
    assert redirect.status_code==303 and guest.cookies.get('post_login_path').strip(chr(34))==f'/reminders/open/{rid}'
    with patch.object(config, 'APP_PASSWORD_HASH', password_hash('test', config.APP_PASSWORD_SALT)):
        logged=guest.post('/login',data={'username':'push-test','password':'test'},follow_redirects=False)
    assert logged.headers['location']==f'/reminders/open/{rid}'
    assert guest.cookies.get('post_login_path') is None
    guest.cookies.set('post_login_path','//evil.test')
    with patch.object(config, 'APP_PASSWORD_HASH', password_hash('test', config.APP_PASSWORD_SALT)):
        assert guest.post('/login',data={'username':'push-test','password':'test'},follow_redirects=False).headers['location']=='/'
    assert client.get('/customers/new').status_code==200
    assert client.get('/work').status_code==200
    assert client.get('/work/number-inbox').status_code==200
    assert client.get('/health').status_code==200
    # Verify the actual startup/shutdown hooks too, with transport isolated.
    with patch('requests.post',return_value=response):
        with TestClient(app) as live:
            live.cookies.set('session_token',token)
            assert live.get('/api/reminders').status_code==200
            assert hasattr(app.state,'reminder_worker')
        assert app.state.reminder_worker.done()
    # A broken optional push configuration must not take down existing pages.
    from app import config
    previous=config.APP_ENCRYPTION_KEY
    config.APP_ENCRYPTION_KEY='invalid-key'
    try:
        with TestClient(app) as degraded:
            assert degraded.get('/health').status_code==200
            degraded.cookies.set('session_token',token)
            assert degraded.get('/work').status_code==200
            assert degraded.get('/api/reminders').status_code==503
    finally:
        config.APP_ENCRYPTION_KEY=previous
    print('Web Push contracts passed: auth, CSRF, SSRF rejection, persistent keys, encrypted subscriptions, concurrency, actual VAPID/encryption, retry, expiration, source collection, settings, device deletion, route regression, worker lifecycle')

if __name__=='__main__': main()
