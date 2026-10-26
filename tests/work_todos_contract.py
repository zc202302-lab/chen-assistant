"""Cross-client todo lifecycle, auth, isolation and stale-write protection."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from v152_high_frequency_flow_acceptance import seed
from cryptography.fernet import Fernet
from app import config
config.APP_ENCRYPTION_KEY = Fernet.generate_key().decode()
from fastapi.testclient import TestClient
from app.main import app
from app.db import db
from app.security import get_session
from app.work_todos import ensure_work_todos_schema

cid, ids, token = seed()
csrf = get_session(token)['csrf_token']
with TestClient(app) as client:
    assert client.get('/work/todos', follow_redirects=False).status_code == 303
    assert client.get('/api/work-todos').status_code == 401
    assert client.post('/api/work-todos', json={'title':'unauthorized'}).status_code == 401
    client.cookies.set('session_token',token)
    assert client.post('/work/todos',data={'title':'bad','csrf':'bad'}).status_code == 403
    assert client.post('/work/todos',data={'title':'work test','note':'independent','remind_at':'2020-01-01T09:00','csrf':csrf}).status_code == 200
    with db() as conn:
        item = dict(conn.execute('SELECT * FROM work_todos').fetchone())
        assert conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 0
    assert client.get('/work').text.count('href="/work/todos"') == 1
    page = client.get('/work/todos?view=settings').text
    with db() as conn:
        secret = conn.execute("SELECT value FROM app_meta WHERE key='work_todos_desktop_token_v1'").fetchone()[0]
    assert secret in page
    assert secret not in client.get('/work/todos').text
    headers = {'Authorization':'Bearer '+secret}
    result = client.get('/api/work-todos',headers=headers).json()
    assert result['items'][0]['due'] is True
    for payload in [{'action':'done','revision':0},{'action':'postpone','revision':1,'remind_at':'yesterday'}]:
        assert client.post(f"/api/work-todos/{item['id']}",headers=headers,json=payload).status_code in (400,409)
    def update(action,rev,**kwargs):
        return client.post(f"/api/work-todos/{item['id']}",headers=headers,json={'action':action,'revision':rev,**kwargs})
    assert update('postpone',1,remind_at='2099-01-01T09:00').json()['items'][0]['due'] is False
    assert update('done',1).status_code == 409
    assert update('done',2).json()['items'][0]['done'] == 1
    assert 'work test' in client.get('/work/todos?view=done').text
    assert update('reopen',3).json()['items'][0]['done'] == 0
    assert update('edit',4,title='changed',note='note',remind_at='').json()['items'][0]['remind_at'] == ''
    assert update('edit',5,title='<script>alert(1)</script>',note='',remind_at='').status_code == 200
    assert '<script>alert(1)</script>' not in client.get('/work/todos').text
    assert client.post('/api/work-todos',headers=headers,json={'title':'desktop new','remind_at':'','note':'x'}).status_code == 200
    assert client.post('/api/work-todos',headers=headers,content=b'x'*17000).status_code == 413
    assert update('delete',6).status_code == 200
    assert update('done',6).status_code == 404
    assert client.post('/work/todos/connection',data={'csrf':csrf}).status_code == 200
    assert client.get('/api/work-todos',headers=headers).status_code == 401
    ensure_work_todos_schema()
    with db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM work_todos').fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 0
print('work todos contract passed: web/desktop lifecycle, separate scope, auth, revisions, clearing and token rotation')
