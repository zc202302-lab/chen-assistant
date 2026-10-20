"""Authenticated HTML routes for creating, reading and updating business processes."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.routing import APIRoute
from starlette.datastructures import UploadFile
from starlette.concurrency import run_in_threadpool

from . import config
from .business_processes import (ensure_business_process_schema, load_process, load_step,
    text_fields, revision_value, claim_revision, sanitize_image, MAX_IMAGE_BYTES)
from .db import db, now_iso
from .security import require_csrf
from .templating import Jinja2Templates


class ProcessUploadRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request):
            if request.method != 'POST':
                return await handler(request)
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > 32 * 1024 * 1024:
                    raise HTTPException(413, '一次保存的内容最多32MB，请分次添加图片')
                body.extend(chunk)
            consumed = False

            async def receive():
                nonlocal consumed
                if consumed:
                    return {'type': 'http.disconnect'}
                consumed = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}

            return await handler(Request(request.scope, receive))

        return bounded


router = APIRouter(route_class=ProcessUploadRoute)
templates = Jinja2Templates(directory=config.ROOT / 'app/templates')


def _csrf(request, form):
    try:
        require_csrf(getattr(request.state, 'session', None), str(form.get('csrf', '')))
    except ValueError:
        raise HTTPException(403, 'CSRF校验失败')


def _render(request, template, status=200, **extra):
    return templates.TemplateResponse(template, {'request': request,
        'csrf': request.state.session['csrf_token'], 'app_version': config.APP_VERSION, **extra}, status_code=status)


def _redirect(process_id):
    return RedirectResponse(f'/work/processes/{process_id}', status_code=303)


@router.get('/work/processes', response_class=HTMLResponse)
def process_list(request: Request, q: str = ''):
    q = q.strip()[:200]
    with db() as conn:
        ensure_business_process_schema(conn)
        items = conn.execute('''SELECT p.*, (SELECT COUNT(*) FROM business_process_steps s WHERE s.process_id=p.id) step_count
            FROM business_processes p WHERE ?='' OR instr(lower(p.title||' '||p.description),lower(?))>0
            OR EXISTS(SELECT 1 FROM business_process_steps s WHERE s.process_id=p.id
                AND instr(lower(s.title||' '||s.description),lower(?))>0)
            ORDER BY p.updated_at DESC,p.id DESC''', (q, q, q)).fetchall()
    return _render(request, 'business_process_list.html', items=items, q=q)


@router.get('/work/processes/new', response_class=HTMLResponse)
def process_new(request: Request):
    return _render(request, 'business_process_edit.html', process=None, item={}, images=[], mode='process', error='')


@router.post('/work/processes/new')
async def process_create(request: Request):
    async with request.form(max_files=0, max_fields=10) as form:
        _csrf(request, form)
        try:
            title, description = text_fields(form)
        except HTTPException as exc:
            return _render(request, 'business_process_edit.html', exc.status_code, process=None,
                item=dict(form), images=[], mode='process', error=exc.detail)
        with db() as conn:
            ensure_business_process_schema(conn)
            stamp = now_iso()
            pid = conn.execute('''INSERT INTO business_processes(title,description,created_at,updated_at)
                                  VALUES(?,?,?,?)''', (title, description, stamp, stamp)).lastrowid
    return _redirect(pid)


@router.get('/work/processes/{process_id}/edit', response_class=HTMLResponse)
def process_edit(request: Request, process_id: int):
    with db() as conn:
        item = load_process(conn, process_id)
    return _render(request, 'business_process_edit.html', process=item, item=item, images=[], mode='process', error='')


@router.post('/work/processes/{process_id}/edit')
async def process_update(request: Request, process_id: int):
    async with request.form(max_files=0, max_fields=10) as form:
        _csrf(request, form)
        with db() as conn:
            item = load_process(conn, process_id)
        try:
            title, description = text_fields(form)
            with db() as conn:
                claim_revision(conn, process_id, revision_value(form))
                conn.execute('UPDATE business_processes SET title=?,description=? WHERE id=?', (title, description, process_id))
        except HTTPException as exc:
            return _render(request, 'business_process_edit.html', exc.status_code, process=item,
                item={**dict(form), 'revision': form.get('revision')}, images=[], mode='process', error=exc.detail)
    return _redirect(process_id)


@router.get('/work/processes/{process_id}', response_class=HTMLResponse)
def process_detail(request: Request, process_id: int):
    with db() as conn:
        item = load_process(conn, process_id)
        steps = [dict(row) for row in conn.execute('SELECT * FROM business_process_steps WHERE process_id=? ORDER BY sort_order,id', (process_id,))]
        for step in steps:
            step['images'] = conn.execute('SELECT id FROM business_process_images WHERE step_id=? ORDER BY id', (step['id'],)).fetchall()
    return _render(request, 'business_process_detail.html', process=item, steps=steps)


@router.post('/work/processes/{process_id}/delete')
async def process_delete(request: Request, process_id: int):
    async with request.form(max_files=0, max_fields=10) as form:
        _csrf(request, form)
        with db() as conn:
            load_process(conn, process_id)
            claim_revision(conn, process_id, revision_value(form))
            conn.execute('DELETE FROM business_processes WHERE id=?', (process_id,))
    return RedirectResponse('/work/processes', status_code=303)


def _step_form(request, process_id, step_id=None, error='', values=None, status=200):
    with db() as conn:
        process = load_process(conn, process_id)
        item = load_step(conn, process_id, step_id) if step_id is not None else {}
        images = conn.execute('SELECT id FROM business_process_images WHERE step_id=? ORDER BY id', (step_id,)).fetchall() if step_id else []
    item = {**item, 'revision': process['revision'], **(values or {})}
    return _render(request, 'business_process_edit.html', status, process=process, item=item,
                   images=images, mode='step', error=error)


@router.get('/work/processes/{process_id}/steps/new', response_class=HTMLResponse)
def process_step_new(request: Request, process_id: int):
    return _step_form(request, process_id)


@router.get('/work/processes/{process_id}/steps/{step_id}/edit', response_class=HTMLResponse)
def process_step_edit(request: Request, process_id: int, step_id: int):
    return _step_form(request, process_id, step_id)


async def _save_step(request, process_id, form, step_id=None):
    original_step_id = step_id
    try:
        title, description = text_fields(form)
        revision = revision_value(form)
        photos = []
        for upload in form.getlist('images'):
            if not isinstance(upload, UploadFile) or not upload.filename:
                continue
            content = await upload.read(MAX_IMAGE_BYTES + 1)
            photos.append(await run_in_threadpool(sanitize_image, content))
        try:
            removed = {int(value) for value in form.getlist('remove_images')}
        except (TypeError, ValueError):
            raise HTTPException(400, '配图编号无效')
        with db() as conn:
            load_process(conn, process_id)
            claim_revision(conn, process_id, revision)
            if step_id is None:
                order = conn.execute('SELECT COALESCE(MAX(sort_order),-1)+1 FROM business_process_steps WHERE process_id=?', (process_id,)).fetchone()[0]
                step_id = conn.execute('INSERT INTO business_process_steps(process_id,title,description,sort_order) VALUES(?,?,?,?)',
                                      (process_id, title, description, order)).lastrowid
            else:
                load_step(conn, process_id, step_id)
                conn.execute('UPDATE business_process_steps SET title=?,description=? WHERE id=?', (title, description, step_id))
            existing = {row['id'] for row in conn.execute('SELECT id FROM business_process_images WHERE step_id=?', (step_id,))}
            if not removed <= existing:
                raise HTTPException(400, '不能删除其他步骤的配图')
            for image_id in removed:
                conn.execute('DELETE FROM business_process_images WHERE id=? AND step_id=?', (image_id, step_id))
            for content in photos:
                conn.execute('INSERT INTO business_process_images(step_id,content,created_at) VALUES(?,?,?)', (step_id, content, now_iso()))
    except HTTPException as exc:
        if exc.status_code == 404:
            raise
        values = {'title': str(form.get('title', '')), 'description': str(form.get('description', '')),
                  'revision': form.get('revision', '')}
        return _step_form(request, process_id, original_step_id, str(exc.detail) + '；填写内容已保留，重新保存前请重新选择新增图片。', values, exc.status_code)
    return _redirect(process_id)


@router.post('/work/processes/{process_id}/steps/new')
async def process_step_create(request: Request, process_id: int):
    async with request.form(max_files=12, max_fields=60) as form:
        _csrf(request, form)
        return await _save_step(request, process_id, form)


@router.post('/work/processes/{process_id}/steps/{step_id}/edit')
async def process_step_update(request: Request, process_id: int, step_id: int):
    async with request.form(max_files=12, max_fields=60) as form:
        _csrf(request, form)
        return await _save_step(request, process_id, form, step_id)


@router.post('/work/processes/{process_id}/steps/{step_id}/delete')
async def process_step_delete(request: Request, process_id: int, step_id: int):
    async with request.form(max_files=0, max_fields=10) as form:
        _csrf(request, form)
        with db() as conn:
            load_process(conn, process_id)
            load_step(conn, process_id, step_id)
            claim_revision(conn, process_id, revision_value(form))
            conn.execute('DELETE FROM business_process_steps WHERE id=?', (step_id,))
    return _redirect(process_id)


@router.post('/work/processes/{process_id}/steps/{step_id}/move')
async def process_step_move(request: Request, process_id: int, step_id: int):
    async with request.form(max_files=0, max_fields=10) as form:
        _csrf(request, form)
        direction = str(form.get('direction', ''))
        if direction not in ('up', 'down'):
            raise HTTPException(400, '移动方向无效')
        with db() as conn:
            load_process(conn, process_id)
            load_step(conn, process_id, step_id)
            claim_revision(conn, process_id, revision_value(form))
            ids = [row['id'] for row in conn.execute('SELECT id FROM business_process_steps WHERE process_id=? ORDER BY sort_order,id', (process_id,))]
            index = ids.index(step_id)
            target = index + (-1 if direction == 'up' else 1)
            if 0 <= target < len(ids):
                ids[index], ids[target] = ids[target], ids[index]
                for position, item_id in enumerate(ids):
                    conn.execute('UPDATE business_process_steps SET sort_order=? WHERE id=?', (position, item_id))
    return _redirect(process_id)


@router.get('/work/processes/images/{image_id}')
def process_image(request: Request, image_id: int):
    with db() as conn:
        ensure_business_process_schema(conn)
        row = conn.execute('SELECT content FROM business_process_images WHERE id=?', (image_id,)).fetchone()
    if row is None:
        raise HTTPException(404, '配图不存在或已删除')
    return Response(bytes(row['content']), media_type='image/webp', headers={
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
        'Content-Disposition': 'inline; filename="process-image.webp"'})
