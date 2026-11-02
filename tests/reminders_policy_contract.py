"""Unified modes/scopes/weekdays, live cancellation and desktop feed policy."""
from datetime import datetime
from zoneinfo import ZoneInfo
from reminders_push_contract import (app, init_db, db, now_iso, create_session, ensure_reminder_schema,
    ensure_number_inbox_schema, collect_due, collect_scheduled, deliver_one, b64)
from app.reminders import publish_reminder, reminder_current
from app.work_todos import ensure_work_todos_schema, desktop_token
from app.reminder_policy import desktop_policy
from app.v162_number_inbox import ensure_desktop_token
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient
import os


def main():
    init_db(); ensure_number_inbox_schema(); ensure_work_todos_schema(); ensure_reminder_schema()
    token, csrf, _ = create_session()
    client = TestClient(app)
    client.cookies.set('session_token', token)
    headers = {'X-CSRF-Token':csrf}
    def prefs(**values):
        response = client.post('/api/reminders/preferences', headers=headers, json=values)
        assert response.status_code == 200, response.text
    def schedule(slots, days):
        return client.post('/api/reminders/schedule', headers=headers, json={'slots':slots,'weekdays':days})
    key = ec.generate_private_key(ec.SECP256R1())
    sub = {'endpoint':'https://web.push.apple.com/policy-test','keys':{'auth':b64(os.urandom(16)),
        'p256dh':b64(key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint))}}
    assert client.post('/api/reminders/subscriptions',headers=headers,json={'subscription':sub,'name':'手机'}).status_code == 200
    with db() as conn:
        cid = conn.execute("INSERT INTO customers(name,created_at,updated_at) VALUES('测试客户',?,?)", (now_iso(),now_iso())).lastrowid
        tid = conn.execute("INSERT INTO tasks(customer_id,title,remind_at,created_at) VALUES(?,?,?,?)", (cid,'客户待办','2026-11-01T09:00',now_iso())).lastrowid
        gid = conn.execute("INSERT INTO work_todos(title,remind_at,created_at,updated_at) VALUES('全局待办','2026-11-01T09:00',?,?)", (now_iso(),now_iso())).lastrowid
        conn.execute("INSERT INTO number_inbox(number,normalized_number,submitted_at,submit_batch) VALUES('13800000000','13800000000',?,'policy')", (now_iso(),))
        task_token = desktop_token(conn); number_token = ensure_desktop_token(conn)
    monday = datetime(2026,11,2,9,0,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
    collect_due(now=monday); collect_due(now=monday)
    state = client.get('/api/reminders').json()
    assert {f'task:{tid}:2026-11-01T09:00', f'work-task:{gid}:2026-11-01T09:00'} <= {r['event_key'] for r in state['items']}
    assert len([r for r in state['items'] if r['kind']=='task']) == 2
    assert schedule(['09:00','09:30'], [0,2,4]).status_code == 200
    for bad in [[],[True],[7],[0,0],['1'],{},[{}]]:
        assert schedule(['09:00'],bad).status_code == 400, bad
    assert client.get('/api/reminders').json()['schedule_weekdays'] == [0,2,4]
    prefs(instant=False, scheduled=True, system=False)
    # Switching off instant invalidates already queued immediate pushes.
    with db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM push_outbox WHERE state='pending'").fetchone()[0] == 0
    collect_scheduled(now=monday); collect_scheduled(now=monday+10)
    collect_scheduled(now=monday+86400)  # Tuesday is excluded.
    with db() as conn:
        scheduled = conn.execute("SELECT id,body FROM reminders WHERE event_key='scheduled:2026-11-02:09:00'").fetchone()
        assert scheduled and '3' in scheduled['body']
        assert conn.execute("SELECT COUNT(*) FROM reminders WHERE event_key LIKE 'scheduled:%'").fetchone()[0] == 1
    sent=[]
    assert deliver_one(now=monday,sender=lambda **kw:sent.append(kw))
    assert len(sent) == 1  # Timed summaries do not depend on the legacy system category.
    prefs(task_global=False, number_inbox=False)
    collect_scheduled(now=monday+1800)
    with db() as conn:
        summary=conn.execute("SELECT id,body FROM reminders WHERE event_key='scheduled:2026-11-02:09:30'").fetchone()
        assert summary and '1' in summary['body']
        conn.execute('UPDATE tasks SET done=1 WHERE id=?',(tid,))
    # No stale summary reaches a provider after the underlying work is done.
    assert deliver_one(now=monday+1800,sender=lambda **kw:sent.append(kw))
    assert len(sent) == 1
    # Pausing the phone must leave the Windows master gate enabled.
    prefs(mobile=False)
    phone_state = client.get('/api/reminders').json()
    assert phone_state['preferences']['mobile'] is False
    assert client.get('/api/work-todos',headers={'Authorization':'Bearer '+task_token}).json()['reminder_policy'] == {'enabled': True}
    assert client.get('/api/number-inbox/pending',headers={'Authorization':'Bearer '+number_token}).json()['reminder_policy'] == {'enabled': True}
    assert client.post('/api/reminders/test',headers=headers,json={'device_id':phone_state['devices'][0]['id']}).status_code == 400
    from app.reminder_policy import notification_allowed
    assert not notification_allowed(phone_state['preferences'], 'system', 'test:paused-phone')
    assert not notification_allowed(phone_state['preferences'], 'system', 'scheduled:paused-phone')
    with db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM push_outbox WHERE state='pending'").fetchone()[0] == 0
    ensure_reminder_schema()
    assert client.get('/api/reminders').json()['preferences']['mobile'] is False
    prefs(mobile=True)
    assert client.get('/api/reminders').json()['preferences']['mobile'] is True
    prefs(all=False)
    api = client.get('/api/work-todos',headers={'Authorization':'Bearer '+task_token}).json()
    inbox = client.get('/api/number-inbox/pending',headers={'Authorization':'Bearer '+number_token}).json()
    assert api['reminder_policy'] == inbox['reminder_policy']
    assert api['reminder_policy'] == {'enabled': False}
    prefs(all=True, instant=False, scheduled=True, number_inbox=False, task_global=False)
    assert client.get('/api/work-todos',headers={'Authorization':'Bearer '+task_token}).json()['reminder_policy'] == {'enabled': True}
    assert client.get('/api/number-inbox/pending',headers={'Authorization':'Bearer '+number_token}).json()['reminder_policy'] == {'enabled': True}
    assert api['items'][0]['id'] == gid
    prefs(instant=True, scheduled=False, task_global=True)
    with db() as conn:
        conn.execute('UPDATE tasks SET done=0 WHERE id=?',(tid,))
    assert client.post('/api/reminders/preferences',headers=headers,json={'all':True,'instant':False,'scheduled':False}).status_code == 400
    prefs(all=True)
    # Source scopes are independent; read-only customer summaries do not enter the editable global list.
    api = client.get('/api/work-todos',headers={'Authorization':'Bearer '+task_token}).json()
    assert api['customer_task_reminders'][0]['source'] == 'customer'
    assert '客户待办' in api['customer_task_reminders'][0]['title']
    assert all(item['title'] != '客户待办' for item in api['items'])
    assert client.get('/api/work-todos',headers={'Authorization':'Bearer '+number_token}).status_code == 401
    collect_scheduled(now=monday+3600)
    with db() as conn:
        before = desktop_policy(conn)
    ensure_reminder_schema()
    with db() as conn:
        assert desktop_policy(conn) == before  # Restart cannot re-enable disabled rules.
    with db() as conn:
        for key in ('task:bad', 'work-task:bad', 'task:²:invalid'):
            rid = publish_reminder(conn,kind='task',title='兼容事件键',event_key=key)
            row = conn.execute('SELECT * FROM reminders WHERE id=?',(rid,)).fetchone()
            assert not reminder_current(conn,row)
    collect_due(now=monday)  # Generic event API input cannot break the worker.
    # Computer reception is independent of phone rules and persists across restart.
    prefs(desktop=False,mobile=True)
    for url, bearer in [('/api/work-todos',task_token),('/api/number-inbox/pending',number_token)]:
        assert client.get(url,headers={'Authorization':'Bearer '+bearer}).json()['reminder_policy']=={'enabled':False}
    assert client.get('/api/reminders').json()['preferences']['mobile'] is True
    ensure_reminder_schema()
    assert client.get('/api/reminders').json()['preferences']['desktop'] is False
    prefs(mobile=False,desktop=True)
    assert client.get('/api/work-todos',headers={'Authorization':'Bearer '+task_token}).json()['reminder_policy']=={'enabled':True}
    prefs(all=False)
    assert client.get('/api/work-todos',headers={'Authorization':'Bearer '+task_token}).json()['reminder_policy']=={'enabled':False}
    prefs(all=True,mobile=True)
    # Old ordinary-browser records are retained but never receive new notifications.
    assert client.post('/api/reminders/subscriptions',headers=headers,json={'subscription':sub,'name':'桌面浏览器'}).status_code==400
    with db() as conn:
        phone=conn.execute("SELECT * FROM push_devices WHERE name='手机'").fetchone()
        conn.execute("INSERT INTO push_devices(id,endpoint,subscription,name,enabled,created_at,updated_at) VALUES('old-browser','https://web.push.apple.com/old-browser',?,'桌面浏览器',1,1,1)",(phone['subscription'],))
        rid=publish_reminder(conn,kind='system',title='旧浏览器回归',event_key='legacy-browser')
        conn.execute("INSERT OR REPLACE INTO push_outbox(reminder_id,device_id) VALUES(?,'old-browser')",(rid,))
    ensure_reminder_schema()
    with db() as conn:
        assert conn.execute("SELECT enabled FROM push_devices WHERE id='old-browser'").fetchone()[0]==0
        assert conn.execute("SELECT state FROM push_outbox WHERE device_id='old-browser'").fetchone()[0]=='skipped'
        assert conn.execute("SELECT enabled FROM push_devices WHERE id=?",(phone['id'],)).fetchone()[0]==phone['enabled']
    assert client.post('/api/reminders/devices/old-browser',headers=headers,json={'enabled':True}).status_code==400
    print('unified reminders passed: global/customer sources, modes, weekdays, cancellation, scopes, shared desktop feeds, restart')


if __name__ == '__main__':
    main()
