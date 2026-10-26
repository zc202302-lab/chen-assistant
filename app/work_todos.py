"""Independent work todos and a separately scoped desktop connection."""
from calendar import monthrange
from datetime import datetime, timedelta
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
WEEKDAYS = ('周一', '周二', '周三', '周四', '周五', '周六', '周日')
SCHEMA = '''CREATE TABLE IF NOT EXISTS work_todos (
 id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
 remind_at TEXT NOT NULL DEFAULT '', done INTEGER NOT NULL DEFAULT 0,
 revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 completed_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_work_todos_due ON work_todos(done,remind_at,id);'''


def desktop_token_authenticated(endpoint):
    endpoint.__desktop_token_authenticated__ = True
    return endpoint


def ensure_work_todos_schema():
    with db() as conn:
        execute_schema(conn, SCHEMA)
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(work_todos)')}
        if 'repeat_rule' not in columns:
            conn.execute("ALTER TABLE work_todos ADD COLUMN repeat_rule TEXT NOT NULL DEFAULT ''")
        if 'repeat_time' not in columns:
            conn.execute("ALTER TABLE work_todos ADD COLUMN repeat_time TEXT NOT NULL DEFAULT ''")


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


def _day_number(value, low, high, label):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise HTTPException(400, f'{label}无效')
    if not low <= number <= high:
        raise HTTPException(400, f'{label}无效')
    return number


def normalize_repeat(kind, weekday='', monthday=''):
    kind = str(kind or 'none').strip().lower()
    if kind == 'none':
        return ''
    if kind == 'daily':
        return 'daily'
    if kind == 'weekly':
        return f"weekly:{_day_number(weekday, 0, 6, '星期')}"
    if kind == 'monthly':
        return f"monthly:{_day_number(monthday, 1, 31, '日期')}"
    raise HTTPException(400, '循环提醒频率无效')


def validate_repeat_rule(value):
    value = str(value or '').strip().lower()
    if value in ('', 'daily'):
        return value
    if value.startswith('weekly:'):
        return f"weekly:{_day_number(value.partition(':')[2], 0, 6, '星期')}"
    if value.startswith('monthly:'):
        return f"monthly:{_day_number(value.partition(':')[2], 1, 31, '日期')}"
    raise HTTPException(400, '循环提醒频率无效')


def repeat_fields(rule):
    if rule == 'daily':
        return 'daily', '', ''
    if rule.startswith('weekly:'):
        return 'weekly', int(rule.split(':', 1)[1]), ''
    if rule.startswith('monthly:'):
        return 'monthly', '', int(rule.split(':', 1)[1])
    return 'none', '', ''


def repeat_label(rule, repeat_time=''):
    if not rule:
        return ''
    at = repeat_time or '固定时间'
    if rule == 'daily':
        return f'每天 {at}'
    if rule.startswith('weekly:'):
        return f"每{WEEKDAYS[int(rule.split(':', 1)[1])]} {at}"
    if rule.startswith('monthly:'):
        return f"每月{int(rule.split(':', 1)[1])}日 {at}"
    return ''


def next_occurrence(rule, repeat_time, now_value=None):
    """Return the next scheduled Beijing occurrence strictly after now_value."""
    now_value = now_value or local_now()
    try:
        now = datetime.strptime(now_value, '%Y-%m-%dT%H:%M')
        hour, minute = map(int, repeat_time.split(':', 1))
    except (ValueError, AttributeError):
        raise HTTPException(400, '循环提醒时间无效')
    if rule == 'daily':
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
    elif rule.startswith('weekly:'):
        weekday = int(rule.split(':', 1)[1])
        candidate_date = now.date() + timedelta(days=(weekday - now.weekday()) % 7)
        candidate = datetime.combine(candidate_date, now.time().replace(hour=hour, minute=minute, second=0, microsecond=0))
        if candidate <= now:
            candidate += timedelta(days=7)
    elif rule.startswith('monthly:'):
        day = int(rule.split(':', 1)[1])
        year, month = now.year, now.month
        while True:
            actual_day = min(day, monthrange(year, month)[1])
            candidate = now.replace(day=actual_day, hour=hour, minute=minute, second=0, microsecond=0)
            if candidate > now:
                break
            month += 1
            if month > 12:
                year, month = year + 1, 1
    else:
        raise HTTPException(400, '循环提醒频率无效')
    return candidate.strftime('%Y-%m-%dT%H:%M')


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
        kind, weekday, monthday = repeat_fields(item.get('repeat_rule', ''))
        item['repeat_kind'], item['repeat_weekday'], item['repeat_monthday'] = kind, weekday, monthday
        item['repeat_label'] = repeat_label(item.get('repeat_rule', ''), item.get('repeat_time', ''))
    return items


def _repeat_for_payload(payload, current_rule, remind_at):
    if 'repeat_rule' in payload:
        rule = validate_repeat_rule(payload.get('repeat_rule'))
    elif 'repeat_kind' in payload:
        rule = normalize_repeat(payload.get('repeat_kind'), payload.get('repeat_weekday'), payload.get('repeat_monthday'))
    else:
        rule = current_rule
    if rule and not remind_at:
        raise HTTPException(400, '循环提醒必须设置首次提醒时间')
    return rule


def change(conn, item_id, payload):
    row = conn.execute('SELECT * FROM work_todos WHERE id=?', (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, '待办不存在')
    if str(payload.get('revision', '')) != str(row['revision']):
        raise HTTPException(409, '待办已在其他端更新，请刷新后重试')
    action = payload.get('action')
    title, note = row['title'], row['note']
    remind_at, repeat_rule, repeat_time, done = row['remind_at'], row['repeat_rule'], row['repeat_time'], row['done']
    completed_at = row['completed_at']
    if action == 'edit':
        title = text(payload.get('title'), '标题', 200, True)
        note = text(payload.get('note'), '备注', 4000)
        remind_at = reminder(payload.get('remind_at'))
        new_repeat_rule = _repeat_for_payload(payload, repeat_rule, remind_at)
        if new_repeat_rule != repeat_rule or (new_repeat_rule and remind_at[11:16] != (row['remind_at'] or '')[11:16]):
            repeat_time = remind_at[11:16] if new_repeat_rule else ''
        repeat_rule = new_repeat_rule
    elif action == 'postpone':
        if done:
            raise HTTPException(409, '已结办事项请先重新打开')
        remind_at = reminder(payload.get('remind_at'))
        if not remind_at or remind_at <= local_now():
            raise HTTPException(400, '延期时间须晚于当前时间')
    elif action in ('done', 'reopen', 'complete_occurrence', 'stop_repeat'):
        if action == 'reopen':
            done, completed_at = 0, ''
        elif action == 'stop_repeat':
            done, completed_at, repeat_rule, repeat_time = 1, now_iso(), '', ''
        elif repeat_rule:
            # Completing a repeating task completes this occurrence and keeps the
            # next one active at its fixed Beijing clock time.
            anchor = max(local_now(), remind_at)
            remind_at = next_occurrence(repeat_rule, repeat_time, anchor)
            done, completed_at = 0, ''
        else:
            done, completed_at = 1, now_iso()
    elif action == 'delete':
        conn.execute('DELETE FROM work_todos WHERE id=?', (item_id,))
        return
    else:
        raise HTTPException(400, '待办操作无效')
    conn.execute('''UPDATE work_todos SET title=?,note=?,remind_at=?,done=?,completed_at=?,
        repeat_rule=?,repeat_time=?,revision=revision+1,updated_at=? WHERE id=?''',
        (title, note, remind_at, done, completed_at, repeat_rule, repeat_time, now_iso(), item_id))


def _csrf(request, value):
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
    _csrf(request, form.get('csrf'))
    title = text(form.get('title'), '标题', 200, True)
    note = text(form.get('note'), '备注', 4000)
    at = reminder(form.get('remind_at'))
    rule = _repeat_for_payload(form, '', at)
    repeat_time = at[11:16] if rule else ''
    with db() as conn:
        conn.execute('''INSERT INTO work_todos(title,note,remind_at,repeat_rule,repeat_time,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?)''', (title, note, at, rule, repeat_time, now_iso(), now_iso()))
    return RedirectResponse('/work/todos', 303)


@router.post('/work/todos/connection')
async def rotate_work_todo_connection(request: Request):
    form = await request.form()
    _csrf(request, form.get('csrf'))
    with db() as conn:
        conn.execute('INSERT INTO app_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (TOKEN_KEY,secrets.token_urlsafe(32)))
    return RedirectResponse('/work/todos?view=settings', 303)


@router.post('/work/todos/{item_id}')
async def update_work_todo(request: Request, item_id: int):
    form = await request.form()
    _csrf(request, form.get('csrf'))
    with db(immediate=True) as conn:
        change(conn, item_id, form)
    return RedirectResponse('/work/todos?view=all' if form.get('action') in {'done', 'complete_occurrence', 'stop_repeat'} else '/work/todos', 303)


@router.get('/api/work-todos')
def desktop_work_todos(request: Request):
    with db() as conn:
        authorize(conn, request)
        return {'ok': True, 'items': snapshot(conn), 'server_time': local_now()}


@router.post('/api/work-todos')
@router.post('/api/work-todos/{item_id}')
@desktop_token_authenticated
async def desktop_update_work_todo(request: Request, item_id: int | None = None):
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
            rule = _repeat_for_payload(payload, '', at)
            repeat_time = at[11:16] if rule else ''
            conn.execute('''INSERT INTO work_todos(title,note,remind_at,repeat_rule,repeat_time,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?)''', (title, note, at, rule, repeat_time, now_iso(), now_iso()))
        return {'ok': True, 'items': snapshot(conn), 'server_time': local_now()}
