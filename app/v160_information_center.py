from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from .templating import Jinja2Templates

from . import config
from .db import execute_schema, connection_scope, db, now_iso
from .security import decrypt_secret, encrypt_secret, require_csrf

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')

V160_SCHEMA = r'''
CREATE TABLE IF NOT EXISTS information_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    body_enc TEXT NOT NULL DEFAULT '',
    link_url TEXT NOT NULL DEFAULT '',
    pinned INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_information_records_updated
    ON information_records(archived,pinned,updated_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS idx_information_records_category
    ON information_records(archived,category,updated_at DESC);
'''


def ensure_v160_schema(conn=None):
    with connection_scope(conn) as conn:
        execute_schema(conn, V160_SCHEMA)


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


def _record_payload(row):
    item = dict(row)
    try:
        item['body'] = decrypt_secret(item.pop('body_enc', '') or '')
        item['decrypt_error'] = False
    except Exception:
        item['body'] = ''
        item['decrypt_error'] = True
    return item


def _record_or_404(conn, record_id: int):
    row = conn.execute(
        'SELECT * FROM information_records WHERE id=? AND archived=0',
        (record_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, '资料不存在')
    return row


@router.on_event('startup')
def startup_v160_information_center():
    ensure_v160_schema()


@router.get('/info', response_class=HTMLResponse)
def information_center_v160(request: Request, q: str = '', category: str = ''):
    q = q.strip()
    category = category.strip()
    with db() as conn:
        ensure_v160_schema(conn)
        rows = conn.execute(
            '''SELECT * FROM information_records
               WHERE archived=0
               ORDER BY pinned DESC,updated_at DESC,id DESC'''
        ).fetchall()
        categories = [
            r['category'] for r in conn.execute(
                """SELECT DISTINCT category FROM information_records
                   WHERE archived=0 AND category<>'' ORDER BY category"""
            ).fetchall()
        ]
        account_count = int(conn.execute('SELECT COUNT(*) n FROM website_accounts').fetchone()['n'])

    items = []
    q_lower = q.casefold()
    for row in rows:
        item = _record_payload(row)
        if category and item['category'] != category:
            continue
        if q:
            haystack = '\n'.join([
                item['title'] or '',
                item['category'] or '',
                item['tags'] or '',
                item['body'] or '',
                item['link_url'] or '',
            ]).casefold()
            if q_lower not in haystack:
                continue
        items.append(item)

    return templates.TemplateResponse(
        'information_center_v160.html',
        _ctx(
            request,
            records=items,
            q=q,
            category=category,
            categories=categories,
            account_count=account_count,
        ),
    )


@router.get('/info/new', response_class=HTMLResponse)
def information_new_page_v160(request: Request):
    return templates.TemplateResponse(
        'information_edit_v160.html',
        _ctx(request, item=None),
    )


@router.post('/info/new')
async def information_new_v160(request: Request):
    form = await request.form()
    _csrf(request, str(form.get('csrf', '')))
    title = str(form.get('title', '')).strip()
    if not title:
        raise HTTPException(400, '标题不能为空')
    now = now_iso()
    with db() as conn:
        ensure_v160_schema(conn)
        cur = conn.execute(
            '''INSERT INTO information_records
               (title,category,tags,body_enc,link_url,pinned,archived,created_at,updated_at)
               VALUES(?,?,?,?,?,?,0,?,?)''',
            (
                title,
                str(form.get('category', '')).strip(),
                str(form.get('tags', '')).strip(),
                encrypt_secret(str(form.get('body', ''))),
                str(form.get('link_url', '')).strip(),
                1 if str(form.get('pinned', '')) == '1' else 0,
                now,
                now,
            ),
        )
        record_id = int(cur.lastrowid)
    return RedirectResponse(f'/info/{record_id}', status_code=303)


@router.get('/info/{record_id}', response_class=HTMLResponse)
def information_detail_v160(request: Request, record_id: int):
    with db() as conn:
        ensure_v160_schema(conn)
        item = _record_payload(_record_or_404(conn, record_id))
    return templates.TemplateResponse(
        'information_detail_v160.html',
        _ctx(request, item=item),
    )


@router.get('/info/{record_id}/edit', response_class=HTMLResponse)
def information_edit_page_v160(request: Request, record_id: int):
    with db() as conn:
        ensure_v160_schema(conn)
        item = _record_payload(_record_or_404(conn, record_id))
    return templates.TemplateResponse(
        'information_edit_v160.html',
        _ctx(request, item=item),
    )


@router.post('/info/{record_id}/edit')
async def information_edit_v160(request: Request, record_id: int):
    form = await request.form()
    _csrf(request, str(form.get('csrf', '')))
    title = str(form.get('title', '')).strip()
    if not title:
        raise HTTPException(400, '标题不能为空')
    with db() as conn:
        ensure_v160_schema(conn)
        _record_or_404(conn, record_id)
        conn.execute(
            '''UPDATE information_records
               SET title=?,category=?,tags=?,body_enc=?,link_url=?,pinned=?,updated_at=?
               WHERE id=?''',
            (
                title,
                str(form.get('category', '')).strip(),
                str(form.get('tags', '')).strip(),
                encrypt_secret(str(form.get('body', ''))),
                str(form.get('link_url', '')).strip(),
                1 if str(form.get('pinned', '')) == '1' else 0,
                now_iso(),
                record_id,
            ),
        )
    return RedirectResponse(f'/info/{record_id}', status_code=303)


@router.post('/info/{record_id}/archive')
async def information_archive_v160(request: Request, record_id: int):
    form = await request.form()
    _csrf(request, str(form.get('csrf', '')))
    with db() as conn:
        ensure_v160_schema(conn)
        _record_or_404(conn, record_id)
        conn.execute(
            'UPDATE information_records SET archived=1,updated_at=? WHERE id=?',
            (now_iso(), record_id),
        )
    return RedirectResponse('/info', status_code=303)

