"""Independent work todos and a separately scoped desktop connection."""
from datetime import datetime
from zoneinfo import ZoneInfo
import secrets
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from . import config
from .db import db, now_iso, execute_schema
from .security import require_csrf
from .templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')
TZ = ZoneInfo('Asia/Shanghai')
TOKEN_KEY = 'work_todos_desktop_token_v1'
SCHEMA = '''CREATE TABLE IF NOT EXISTS work_todos (
 id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
 remind_at TEXT NOT NULL DEFAULT '', done INTEGER NOT NULL DEFAULT 0,
 revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 completed_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_work_todos_due ON work_todos(done,remind_at,id);'''


def ensure_work_todos_schema():
    with db() as conn:
        execute_schema(conn, SCHEMA)


def local_now():
    return datetime.now(TZ).strftime('%Y-%m-%dT%H:%M')


def text(value, label, maximum, required=False):
    value = str(value or '').strip()
    if len(value) > maximum or (required and not value):
        raise HTTPException(400, f'{label}不能为空且最多{maximum}字' if required else f'{label}最多{maximum}字')
    return value


def reminder(value):
    value = str(value or '').strip()
    if not value:
        return ''
    try:
        parsed = datetime.strptime(value, '%Y-%m-%dT%H:%M')
        if parsed.strftime('%Y-%m-%dT%H:%M') != value:
            raise ValueError()
    except ValueError:
        raise HTTPException(400, '提醒时间格式无效，请使用北京时间，精确到分钟')
    return value


def desktop_token(conn):
    row = conn.execute('SELECT value FROM app_meta WHERE key=?', (TOKEN_KEY,)).fetchone()
    if row:
        return row['value']
    token = secrets.token_urlsafe(32)
    conn.execute('INSERT INTO app_meta(key,value) VALUES(?,?)', (TOKEN_KEY, token))
    return token


def authorize(conn, request):
    scheme, _, supplied = request.headers.get('authorization', '').partition(' ')
    row = conn.execute('SELECT value FROM app_meta WHERE key=?', (TOKEN_KEY,)).fetchone()
    if scheme.lower() != 'bearer' or not row or not supplied or not secrets.compare_digest(supplied, row['value']):
        raise HTTPException(401, '待办连接码无效，请在网页版重新连接')


def snapshot(conn):
    items = [dict(r) for r in conn.execute("SELECT * FROM work_todos ORDER BY done,CASE WHEN remind_at='' THEN 1 ELSE 0 END,remind_at,id DESC")]
    now = local_now()
    for item in items:
        item['due'] = bool(not item['done'] and item['remind_at'] and item['remind_at'] <= now)
    return items


def change(conn, item_id, payload):
    # Acquire a write transaction before checking revision, including desktop requests.
    row = conn.execute('SELECT * FROM work_todos WHERE id=?', (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, '待办不存在')
    if str(payload.get('revision', '')) != str(row['revision']):
        raise HTTPException(409, '待办已在其他端更新，请刷新后重试')
    action = payload.get('action')
    title, note, remind_at, done = row['title'], row['note'], row['remind_at'], row['done']
    if action == 'edit':
        title = text(payload.get('title'), '标题', 200, True)
        note = text(payload.get('note'), '备注', 4000)
        remind_at = reminder(payload.get('remind_at'))
    elif action == 'postpone':
        if done:
            raise HTTPException(409, '已结办事项请先重新打开')
        remind_at = reminder(payload.get('remind_at'))
        if not remind_at or remind_at <= local_now():
            raise HTTPException(400, '延期时间须晚于当前时间')
    elif action in ('done', 'reopen'):
        done = int(action == 'done')
    elif action == 'delete':
        conn.execute('DELETE FROM work_todos WHERE id=?', (item_id,))
        return
    else:
        raise HTTPException(400, '待办操作无效')
    conn.execute('''UPDATE work_todos SET title=?,note=?,remind_at=?,done=?,completed_at=?,
        revision=revision+1,updated_at=? WHERE id=?''',
        (title, note, remind_at, done, (row['completed_at'] or now_iso()) if done else '', now_iso(), item_id))


def csrf(request, value):
    try:
        require_csrf(request.state.session, str(value or ''))
    except ValueError:
        raise HTTPException(403, 'CSRF校验失败')


@router.get('/work/todos')
def work_todos_page(request: Request, view: str = 'pending', q: str = ''):
    if view not in {'pending', 'done', 'all', 'new', 'settings'}:
        raise HTTPException(400, '待办页面无效')
    with db() as conn:
        items = snapshot(conn)
        token = desktop_token(conn) if view == 'settings' else ''
    if view in {'pending', 'done'}:
        items = [i for i in items if bool(i['done']) == (view == 'done')]
    if q.strip():
        items = [i for i in items if q.strip().casefold() in (i['title'] + '\n' + i['note']).casefold()]
    return templates.TemplateResponse(request, 'work_todos.html', {
        'request': request, 'csrf': request.state.session['csrf_token'], 'items': items,
        'view': view, 'q': q, 'desktop_token': token,
    })


@router.post('/work/todos')
async def create_work_todo(request: Request):
    form = await request.form()
    csrf(request, form.get('csrf'))
    title, note, at = text(form.get('title'), '标题', 200, True), text(form.get('note'), '备注', 4000), reminder(form.get('remind_at'))
    with db() as conn:
        conn.execute('INSERT INTO work_todos(title,note,remind_at,created_at,updated_at) VALUES(?,?,?,?,?)', (title,note,at,now_iso(),now_iso()))
    return RedirectResponse('/work/todos', 303)


@router.post('/work/todos/connection')
async def rotate_work_todo_connection(request: Request):
    form = await request.form()
    csrf(request, form.get('csrf'))
    with db() as conn:
        conn.execute('INSERT INTO app_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (TOKEN_KEY,secrets.token_urlsafe(32)))
    return RedirectResponse('/work/todos?view=settings', 303)


@router.post('/work/todos/{item_id}')
async def update_work_todo(request: Request, item_id: int):
    form = await request.form()
    csrf(request, form.get('csrf'))
    with db(immediate=True) as conn:
        change(conn, item_id, form)
    return RedirectResponse('/work/todos', 303)


@router.get('/api/work-todos')
def desktop_work_todos(request: Request):
    with db() as conn:
        authorize(conn, request)
        return {'ok': True, 'items': snapshot(conn), 'server_time': local_now()}


@router.post('/api/work-todos')
@router.post('/api/work-todos/{item_id}')
async def desktop_update_work_todo(request: Request, item_id: int | None = None):
    # Authenticate before reading the body; no cookie-based desktop mutations.
    with db() as conn:
        authorize(conn, request)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16384:
            raise HTTPException(413, '待办内容过大')
    import json
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError):
        raise HTTPException(400, '待办数据格式错误')
    if not isinstance(payload, dict):
        raise HTTPException(400, '待办数据格式错误')
    with db(immediate=True) as conn:
        authorize(conn, request)
        if item_id is not None:
            change(conn, item_id, payload)
        else:
            title = text(payload.get('title'), '标题', 200, True)
            note = text(payload.get('note'), '备注', 4000)
            at = reminder(payload.get('remind_at'))
            conn.execute('INSERT INTO work_todos(title,note,remind_at,created_at,updated_at) VALUES(?,?,?,?,?)', (title,note,at,now_iso(),now_iso()))
        return {'ok': True, 'items': snapshot(conn), 'server_time': local_now()}
