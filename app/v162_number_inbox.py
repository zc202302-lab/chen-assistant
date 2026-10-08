from __future__ import annotations

import re
import json
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Form, File, UploadFile, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from .templating import Jinja2Templates

from . import config
from .db import execute_schema, connection_scope, db, now_iso
from .security import require_csrf
from . import number_inbox_batch

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')

TOKEN_META_KEY = 'number_inbox_submit_token_v1'
DESKTOP_TOKEN_META_KEY = 'number_inbox_desktop_token_v1'

NUMBER_INBOX_SCHEMA = r'''
CREATE TABLE IF NOT EXISTS number_inbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT NOT NULL,
    normalized_number TEXT NOT NULL,
    submitter TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','done')),
    submitted_at TEXT NOT NULL,
    completed_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_number_inbox_status_time
    ON number_inbox(status, submitted_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_number_inbox_normalized_status
    ON number_inbox(normalized_number, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_number_inbox_one_pending
    ON number_inbox(normalized_number) WHERE status='pending';
'''


def ensure_number_inbox_schema(conn=None) -> str:
    with connection_scope(conn) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        execute_schema(conn, NUMBER_INBOX_SCHEMA)
        execute_schema(conn, number_inbox_batch.BATCH_SCHEMA)
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(number_inbox)')}
        if 'submit_batch' not in columns:
            conn.execute("ALTER TABLE number_inbox ADD COLUMN submit_batch TEXT NOT NULL DEFAULT ''")
        row = conn.execute('SELECT value FROM app_meta WHERE key=?', (TOKEN_META_KEY,)).fetchone()
        token = row['value'] if row else ''
        if not token:
            token = secrets.token_urlsafe(24)
            conn.execute(
                'INSERT OR REPLACE INTO app_meta(key,value) VALUES(?,?)',
                (TOKEN_META_KEY, token),
            )
        return token


def _ctx(request: Request, **extra):
    session = getattr(request.state, 'session', None)
    base = {
        'request': request,
        'csrf': session['csrf_token'] if session else '',
        'app_version': config.APP_VERSION,
    }
    base.update(extra)
    return base


def _csrf(request: Request, value: str):
    try:
        require_csrf(request.state.session, value)
    except ValueError:
        raise HTTPException(403, 'CSRF校验失败')


def _normalize_number(value: str) -> tuple[str, str]:
    raw = (value or '').strip()
    if len(raw) > 64:
        raise HTTPException(400, '号码过长')
    digits = re.sub(r'\D', '', raw)
    if digits.startswith('86') and len(digits) == 13:
        digits = digits[2:]
    if len(digits) < 5 or len(digits) > 20:
        raise HTTPException(400, '请输入有效号码')
    return raw, digits


def _token_matches(conn, token: str) -> bool:
    expected = ensure_number_inbox_schema(conn)
    return bool(token) and secrets.compare_digest(token, expected)


def ensure_desktop_token(conn=None) -> str:
    with connection_scope(conn) as conn:
        ensure_number_inbox_schema(conn)
        row = conn.execute('SELECT value FROM app_meta WHERE key=?', (DESKTOP_TOKEN_META_KEY,)).fetchone()
        token = row['value'] if row else ''
        if not token:
            token = secrets.token_urlsafe(32)
            conn.execute(
                'INSERT OR REPLACE INTO app_meta(key,value) VALUES(?,?)',
                (DESKTOP_TOKEN_META_KEY, token),
            )
        return token


def _desktop_token_from_request(request: Request) -> str:
    auth = (request.headers.get('authorization') or '').strip()
    if not auth.lower().startswith('bearer '):
        return ''
    return auth[7:].strip()


def _desktop_token_matches(conn, request: Request) -> bool:
    supplied = _desktop_token_from_request(request)
    expected = ensure_desktop_token(conn)
    return bool(supplied) and secrets.compare_digest(supplied, expected)


def _display_time(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value)
        return dt.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%m-%d %H:%M')
    except Exception:
        return value or ''


def _pending_items(conn, current_batch: str = ''):

    rows = conn.execute(
        "SELECT number,submitted_at,submit_batch FROM number_inbox WHERE status='pending' "
        "ORDER BY submitted_at DESC,id DESC"
    ).fetchall()
    return [dict(row, submitted_display=_display_time(row['submitted_at']),
                 is_new=bool(current_batch) and row['submit_batch'] == current_batch) for row in rows]


@router.get('/number-submit/{token}', response_class=HTMLResponse)
def public_number_submit_page(request: Request, token: str):
    with db() as conn:
        if not _token_matches(conn, token):
            raise HTTPException(404)
    return templates.TemplateResponse(
        'number_submit_v162.html', {'request': request, 'token': token, 'numbers': ['']},
    )


@router.get('/number-submit/{token}/pending', response_class=HTMLResponse)
def public_number_pending_page(request: Request, token: str, result: str = ''):
    with db() as conn:
        if not _token_matches(conn, token):
            raise HTTPException(404)
        items = _pending_items(conn, request.cookies.get('number_inbox_batch', ''))
    return templates.TemplateResponse(
        'number_pending_v162.html',
        {'request': request, 'token': token, 'items': items, 'result': result},
    )


@router.post('/number-submit/{token}', response_class=HTMLResponse)
def public_number_submit(
    request: Request,
    token: str,
    number: list[str] = Form(...),
):
    with db() as conn:
        if not _token_matches(conn, token):
            raise HTTPException(404)
        values = [value.strip() for value in number if value.strip()]
        if not values or len(number) > 100:
            error = '请至少填写一个号码' if not values else '一次最多提交100个号码'
            return templates.TemplateResponse('number_submit_v162.html', {
                'request': request, 'token': token, 'numbers': number[:100] or [''], 'error': error,
            }, status_code=400)
        try:
            normalized = [_normalize_number(value)[1] for value in values]
        except HTTPException as exc:
            return templates.TemplateResponse('number_submit_v162.html', {
                'request': request, 'token': token, 'numbers': number, 'error': exc.detail,
            }, status_code=400)
        inserted = 0
        batch = secrets.token_urlsafe(24)
        submitted_at = now_iso()
        for digits in dict.fromkeys(normalized):
            cur = conn.execute(
                """INSERT OR IGNORE INTO number_inbox
                   (number,normalized_number,submitter,note,status,submitted_at,completed_at,submit_batch)
                   VALUES(?,?, '', '', 'pending', ?, '', ?)""",
                (digits, digits, submitted_at, batch),
            )
            inserted += cur.rowcount
        result = 'success' if inserted else 'duplicate'
    response = RedirectResponse(f'/number-submit/{token}/pending?result={result}', status_code=303)
    response.set_cookie('number_inbox_batch', batch, httponly=True,
                        secure=request.url.scheme == 'https', samesite='lax',
                        path=f'/number-submit/{token}')
    return response


public_number_submit.__public_token_authenticated__ = True


@router.get('/work/number-inbox', response_class=HTMLResponse)
def number_inbox_admin(request: Request, view: str = 'pending'):
    view = 'settings' if view == 'settings' else 'pending'
    with db() as conn:
        token = ensure_number_inbox_schema(conn)
        desktop_token = ensure_desktop_token(conn) if view == 'settings' else ''
        batch_settings = number_inbox_batch.settings(conn)
        number_inbox_batch.purge_expired(conn)
        done_rows = conn.execute("SELECT id,number,completed_at FROM number_inbox WHERE status='done' ORDER BY completed_at DESC,id DESC").fetchall()
        pending_count = int(
            conn.execute("SELECT COUNT(*) n FROM number_inbox WHERE status='pending'").fetchone()['n']
        )
        rows = conn.execute(
            "SELECT * FROM number_inbox WHERE status='pending' ORDER BY submitted_at DESC,id DESC"
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item['submitted_display'] = _display_time(item['submitted_at'])
        items.append(item)
    share_url = f'https://jituan.zbassistant.site/number-submit/{token}'
    return templates.TemplateResponse(
        'number_inbox_v162.html',
        _ctx(
            request,
            view=view,
            items=items,
            pending_count=pending_count,
            done_items=[dict(row, completed_display=_display_time(row['completed_at'])) for row in done_rows],
            done_count=len(done_rows),
            share_url=share_url,
            desktop_token=desktop_token,
            batch_settings=batch_settings,
            desktop_api_url=str(request.base_url).rstrip('/') + '/api/number-inbox/pending',
        ),
    )


@router.post('/work/number-inbox/{item_id}/done')
def number_inbox_done(request: Request, item_id: int, csrf: str = Form(...)):
    _csrf(request, csrf)
    with db() as conn:
        ensure_number_inbox_schema(conn)
        conn.execute(
            "UPDATE number_inbox SET status='done',completed_at=? WHERE id=? AND status='pending'",
            (now_iso(), item_id),
        )
    return RedirectResponse('/work/number-inbox?status=pending', status_code=303)


@router.post('/work/number-inbox/{item_id}/reopen')
def number_inbox_reopen(request: Request, item_id: int, csrf: str = Form(...)):
    _csrf(request, csrf)
    with db() as conn:
        ensure_number_inbox_schema(conn)
        conn.execute(
            "UPDATE OR IGNORE number_inbox SET status='pending',completed_at='' WHERE id=? AND status='done'",
            (item_id,),
        )
    return RedirectResponse('/work/number-inbox', status_code=303)


@router.get('/api/number-inbox/pending')
def number_inbox_desktop_pending(request: Request):
    with db() as conn:
        if not _desktop_token_matches(conn, request):
            return JSONResponse({'ok': False, 'error': 'unauthorized'}, status_code=401)
        rows = conn.execute(
            """SELECT id,number,submitter,note,submitted_at
               FROM number_inbox
               WHERE status='pending'
               ORDER BY id DESC
               LIMIT 200"""
        ).fetchall()
        total = int(conn.execute("SELECT COUNT(*) n FROM number_inbox WHERE status='pending'").fetchone()['n'])
        pending_ids = [int(row['id']) for row in conn.execute("SELECT id FROM number_inbox WHERE status='pending' ORDER BY id").fetchall()]
    response = JSONResponse(
        {
            'ok': True,
            'pending_count': total,
            'pending_ids': pending_ids,
            'latest_id': int(rows[0]['id']) if rows else 0,
            'items': [
                {
                    'id': int(row['id']),
                    'number': row['number'],
                    'submitter': row['submitter'],
                    'note': row['note'],
                    'submitted_at': row['submitted_at'],
                }
                for row in rows
            ],
        }
    )
    response.headers['Cache-Control'] = 'no-store'
    return response


@router.post('/api/number-inbox/{item_id}/done')
def number_inbox_desktop_done(request: Request, item_id: int):
    with db() as conn:
        if not _desktop_token_matches(conn, request):
            return JSONResponse({'ok': False, 'error': 'unauthorized'}, status_code=401)
        row = conn.execute('SELECT id,status,completed_at FROM number_inbox WHERE id=?', (item_id,)).fetchone()
        if not row:
            return JSONResponse({'ok': False, 'error': 'not_found'}, status_code=404)
        if row['status'] == 'pending':
            completed_at = now_iso()
            conn.execute(
                "UPDATE number_inbox SET status='done',completed_at=? WHERE id=? AND status='pending'",
                (completed_at, item_id),
            )
        else:
            completed_at = row['completed_at'] or ''
    response = JSONResponse({'ok': True, 'id': item_id, 'status': 'done', 'completed_at': completed_at})
    response.headers['Cache-Control'] = 'no-store'
    return response


number_inbox_desktop_done.__desktop_token_authenticated__ = True


@router.post('/work/number-inbox/rotate-desktop-token')
def number_inbox_rotate_desktop_token(request: Request, csrf: str = Form(...)):
    _csrf(request, csrf)
    token = secrets.token_urlsafe(32)
    with db() as conn:
        ensure_number_inbox_schema(conn)
        conn.execute(
            'INSERT OR REPLACE INTO app_meta(key,value) VALUES(?,?)',
            (DESKTOP_TOKEN_META_KEY, token),
        )
    return RedirectResponse('/work/number-inbox?view=settings', status_code=303)


@router.post('/work/number-inbox/rotate-link')
def number_inbox_rotate_link(request: Request, csrf: str = Form(...)):
    _csrf(request, csrf)
    token = secrets.token_urlsafe(24)
    with db() as conn:
        ensure_number_inbox_schema(conn)
        conn.execute(
            'INSERT OR REPLACE INTO app_meta(key,value) VALUES(?,?)',
            (TOKEN_META_KEY, token),
        )
    return RedirectResponse('/work/number-inbox?view=settings', status_code=303)


def pending_number_count(conn) -> int:
    ensure_number_inbox_schema(conn)
    return int(conn.execute("SELECT COUNT(*) n FROM number_inbox WHERE status='pending'").fetchone()['n'])


@router.post('/work/number-inbox/batch-settings')
async def number_inbox_batch_settings(request: Request, csrf: str = Form(...),
                                     role: str = Form(...), manual: str = Form(...),
                                     group_template: UploadFile | None = File(None)):
    _csrf(request, csrf)
    try:
        role, manual = number_inbox_batch.field(role), number_inbox_batch.field(manual)
        groups = None
        if group_template and group_template.filename:
            content = await group_template.read(5 * 1024 * 1024 + 1)
            groups = number_inbox_batch.read_groups(content, group_template.filename)
        with db() as conn:
            ensure_number_inbox_schema(conn)
            saved = number_inbox_batch.settings(conn)
            saved.update(role=role, manual=manual)
            if groups is not None:
                saved.update(groups=groups, filename=group_template.filename.rsplit('/', 1)[-1].rsplit('\\', 1)[-1][:200])
            conn.execute('INSERT OR REPLACE INTO app_meta(key,value) VALUES(?,?)',
                         (number_inbox_batch.META_KEY, json.dumps(saved, ensure_ascii=False)))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    finally:
        if group_template:
            await group_template.close()
    return RedirectResponse('/work/number-inbox?view=settings', status_code=303)


@router.post('/work/number-inbox/batch-add')
def number_inbox_batch_add(request: Request, csrf: str = Form(...)):
    _csrf(request, csrf)
    try:
        with db() as conn:
            ensure_number_inbox_schema(conn)
            rows = conn.execute("SELECT id,normalized_number FROM number_inbox WHERE status='pending' ORDER BY id LIMIT 5001").fetchall()
            numbers = [row['normalized_number'] for row in rows]
            result = number_inbox_batch.signed_batch(numbers, number_inbox_batch.settings(conn), ensure_desktop_token(conn))
            number_inbox_batch.register_batch(conn, result, [row['id'] for row in rows])
    except ValueError as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=400)
    return JSONResponse(result, headers={'Cache-Control': 'no-store'})





@router.post('/work/number-inbox/batch-complete')
async def number_inbox_batch_complete(request: Request):
    _csrf(request, request.headers.get('x-csrf-token', ''))
    return await _complete_batch_receipt(request, desktop=False)


@router.post('/api/number-inbox/batch-complete')
async def number_inbox_desktop_batch_complete(request: Request):
    return await _complete_batch_receipt(request, desktop=True)


async def _complete_batch_receipt(request, desktop):
    raw = await request.body()
    if len(raw) > 4096:
        return JSONResponse({'ok': False, 'error': '回执过大'}, status_code=400)
    try:
        body = json.loads(raw)
        with db(immediate=True) as conn:
            if desktop and not _desktop_token_matches(conn, request):
                return JSONResponse({'ok': False, 'error': 'unauthorized'}, status_code=401)
            ensure_number_inbox_schema(conn)
            result = number_inbox_batch.complete_batch(conn, body, ensure_desktop_token(conn))
    except (ValueError, TypeError, KeyError) as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=400)
    return JSONResponse(result, headers={'Cache-Control': 'no-store'})


number_inbox_desktop_batch_complete.__desktop_token_authenticated__ = True
