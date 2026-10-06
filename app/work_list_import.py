from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.datastructures import FormData

from .db import db, now_iso
from .security import decrypt_secret, encrypt_secret
from .work_list_excel import ExcelTable, MAX_BYTES
from .work_lists import KINDS, _csrf, _ctx, _fields, _list, _revision, _text, _values, templates

router = APIRouter()


def ensure_work_list_import_schema():
    with db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS work_list_imports (
            token TEXT PRIMARY KEY, owner TEXT NOT NULL, payload_enc TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1, expires_at TEXT NOT NULL)''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_work_list_import_expiry ON work_list_imports(expires_at)')
        conn.execute('DELETE FROM work_list_imports WHERE expires_at<?', (now_iso(),))


def _encode(payload):
    text = json.dumps(payload, ensure_ascii=False)
    if len(text.encode()) > 16 * 1024 * 1024:
        raise HTTPException(400, '导入预览过大，请拆分文件')
    return encrypt_secret(text)


def _job(conn, request, token):
    row = conn.execute('SELECT * FROM work_list_imports WHERE token=? AND owner=?', (token, request.state.session['token_hash'])).fetchone()
    if row is None:
        raise HTTPException(404, '导入预览不存在')
    if row['expires_at'] < now_iso():
        raise HTTPException(410, '导入预览已过期，请重新上传')
    return dict(row), json.loads(decrypt_secret(row['payload_enc']))


def _save(conn, job, payload):
    conn.execute('UPDATE work_list_imports SET payload_enc=?,revision=revision+1 WHERE token=?', (_encode(payload), job['token']))


def _page(request, job, payload, error='', code=200, edit=False):
    with db() as conn:
        lists = conn.execute('SELECT id,title FROM work_lists WHERE archived=0 ORDER BY title,id').fetchall()
        target = payload.get('target', 0)
        item = _list(conn, target) if target else None
        fields = _fields(conn, target) if target else []
    return templates.TemplateResponse(request, 'work_list_import.html', _ctx(request, job=job, data=payload,
        lists=lists, item=item, fields=fields, error=error, edit=edit), status_code=code)


@router.get('/work/list-import', response_class=HTMLResponse)
def import_excel_page(request: Request, list_id: int = 0):
    return _page(request, None, {'phase': 'upload', 'target': list_id})


@router.post('/work/list-import/upload')
async def import_excel_upload(request: Request):
    length = request.headers.get('content-length', '')
    if length.isdigit() and int(length) > MAX_BYTES + 512 * 1024:
        raise HTTPException(413, '文件不能超过5 MB')
    form = await request.form(max_files=1, max_fields=10)
    _csrf(request, form.get('csrf'))
    upload = form.get('file')
    if not isinstance(upload, UploadFile):
        # Starlette's form parser creates its own UploadFile superclass.
        from starlette.datastructures import UploadFile as StarletteUploadFile
        if not isinstance(upload, StarletteUploadFile):
            return _page(request, None, {'phase': 'upload', 'target': 0}, '请选择 Excel 文件', 400)
    try:
        content = await upload.read(MAX_BYTES + 1)
    finally:
        await upload.close()
    filename = str(upload.filename or '').replace('\\', '/').rsplit('/', 1)[-1][:200]
    try:
        reader = ExcelTable(content, filename)
        sheets = reader.sheets
        reader.close()
        target = int(form.get('target', 0) or 0)
        with db() as conn:
            if target:
                _list(conn, target, True)
            conn.execute('DELETE FROM work_list_imports WHERE expires_at<?', (now_iso(),))
            owner = request.state.session['token_hash']
            drafts = conn.execute('SELECT payload_enc FROM work_list_imports WHERE owner=?', (owner,)).fetchall()
            active = sum(json.loads(decrypt_secret(row['payload_enc'])).get('phase') != 'done' for row in drafts)
            if active >= 10:
                raise ValueError('同时保留的预览最多10份，请在清单中完成导入或稍后再试')
            token = secrets.token_urlsafe(32)
            payload = {'phase': 'config', 'filename': filename, 'source': base64.b64encode(content).decode(),
                       'sheets': sheets, 'sheet': sheets[0], 'header': 1, 'first': 'A', 'last': '', 'end': 0,
                       'title': filename.rsplit('.', 1)[0], 'target': target}
            expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(timespec='seconds')
            conn.execute('INSERT INTO work_list_imports(token,owner,payload_enc,expires_at) VALUES(?,?,?,?)', (token, owner, _encode(payload), expires))
    except (ValueError, HTTPException) as exc:
        return _page(request, None, {'phase': 'upload', 'target': 0}, str(exc.detail) if isinstance(exc, HTTPException) else str(exc), 400)
    return RedirectResponse(f'/work/list-import/{token}', 303)


@router.get('/work/list-import/{token}', response_class=HTMLResponse)
def import_excel_draft(request: Request, token: str, edit: int = 0):
    with db() as conn:
        job, payload = _job(conn, request, token)
    return _page(request, job, payload, edit=bool(edit))


@router.post('/work/list-import/{token}/prepare')
async def import_excel_prepare(request: Request, token: str):
    form = await request.form()
    _csrf(request, form.get('csrf'))
    with db(immediate=True) as conn:
        job, payload = _job(conn, request, token)
        _revision(form.get('revision'), job['revision'])
        if payload['phase'] == 'done':
            return RedirectResponse(f'/work/list-import/{token}', 303)
        try:
            payload.update(sheet=str(form.get('sheet', '')), header=int(form.get('header', 1)), first=str(form.get('first', 'A')),
                           last=str(form.get('last', '')), end=int(form.get('end', 0) or 0), target=int(form.get('target', 0) or 0),
                           title=_text(form.get('title'), '新清单名称', required=True))
            if payload['target']:
                _list(conn, payload['target'], True)
            reader = ExcelTable(base64.b64decode(payload['source']), payload['filename'])
            try:
                payload['table'] = reader.read(payload['sheet'], payload['header'], payload['first'], payload['last'], payload['end'])
            finally:
                reader.close()
            payload['phase'] = 'mapping'
            payload.pop('plan', None)
            payload.pop('mapping', None)
            _save(conn, job, payload)
        except (ValueError, HTTPException) as exc:
            error = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
            # Render after ending the transaction; another connection is used by _page.
            payload['phase'] = 'config'
        else:
            error = ''
    if error:
        return _page(request, job, payload, error, 400)
    return RedirectResponse(f'/work/list-import/{token}', 303)


def _fingerprint(values, status, note, customer_id, fields):
    normalized = {str(f['id']): values.get(str(f['id']), [] if f['kind'] == 'multi' else '') for f in fields}
    value = json.dumps([normalized, status, note, customer_id], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(value.encode()).hexdigest()


def _plan(conn, payload, form):
    target = payload['target']
    item = _list(conn, target, True) if target else None
    existing = _fields(conn, target) if target else []
    available = {str(f['id']): f for f in existing if not f['hidden']}
    columns = payload['table']['columns']
    mapping, fields, used = [], [], set()
    for col in columns:
        key = col['key']
        destination = str(form.get(f'dest_{key}', 'new'))
        entry = {'dest': destination, 'label': str(form.get(f'label_{key}', col['label'])), 'kind': str(form.get(f'kind_{key}', 'text'))}
        mapping.append(entry)
        if destination == 'skip':
            continue
        if destination != 'new' and destination in used:
            raise ValueError('同一个字段或关联项不能对应多个 Excel 列')
        used.add(destination)
        if destination == 'new':
            label = _text(entry['label'], '字段名称', 80, True)
            kind = entry['kind']
            if kind not in {'text', 'number', 'money', 'date'}:
                raise ValueError('新字段支持文本、数字、金额和日期')
            fields.append({'id': 'new_' + key, 'label': label, 'kind': kind, 'options': [], 'hidden': 0})
        elif destination in available:
            fields.append(available[destination])
        elif destination not in {'note', 'status', 'customer_name', 'customer_code'}:
            raise ValueError('目标字段无效，请重新匹配')
    if len(existing) + sum(str(f['id']).startswith('new_') for f in fields) > 50:
        raise ValueError('清单字段总数不能超过50，请忽略不需要的列')
    if not used or used == {'skip'}:
        raise ValueError('请至少选择一列用于导入')
    if not target and not fields:
        raise ValueError('新清单至少需要一个自定义字段')
    payload['mapping'] = mapping
    rows, errors = [], []
    for source in payload['table']['rows']:
        if not any(cell.strip() for cell, entry in zip(source['cells'], mapping) if entry['dest'] != 'skip'):
            continue
        values_form, note, status, customer_id = [], '', 'pending', None
        try:
            field_index = 0
            for col, cell, entry in zip(columns, source['cells'], mapping):
                dest = entry['dest']
                if dest == 'skip':
                    continue
                if dest == 'note':
                    note = _text(cell, '备注', 20000)
                elif dest == 'status':
                    statuses = {'': 'pending', '待处理': 'pending', '未完成': 'pending', 'pending': 'pending', '已完成': 'done', 'done': 'done'}
                    if cell.strip() not in statuses:
                        raise ValueError('状态须为待处理或已完成')
                    status = statuses[cell.strip()]
                elif dest in {'customer_name', 'customer_code'}:
                    if cell.strip():
                        column = 'name' if dest == 'customer_name' else 'group_code'
                        matches = conn.execute(f'SELECT id FROM customers WHERE {column}=?', (cell.strip(),)).fetchall()
                        if len(matches) != 1:
                            raise ValueError(f'客户“{cell.strip()}”未唯一匹配；可改为普通文本列后导入')
                        if customer_id is not None and customer_id != matches[0]['id']:
                            raise ValueError('客户名称和集团编码指向不同客户')
                        customer_id = matches[0]['id']
                else:
                    field = fields[field_index]
                    field_index += 1
                    if field['kind'] == 'date' and 'T' in cell:
                        cell = cell.split('T', 1)[0]
                    if field['kind'] == 'multi':
                        parts = [p.strip() for p in re_split(cell) if p.strip()]
                        values_form.extend((f'f_{field["id"]}', part) for part in parts)
                    else:
                        values_form.append((f'f_{field["id"]}', cell))
            values = _values(FormData(values_form), fields, {})
            rows.append({'source_row': source['row'], 'values': values, 'note': note, 'status': status, 'customer_id': customer_id})
        except (ValueError, HTTPException) as exc:
            errors.append(f'第{source["row"]}行：' + (str(exc.detail) if isinstance(exc, HTTPException) else str(exc)))
    if errors:
        raise ValueError('\n'.join(errors[:30]) + (f'\n共{len(errors)}行有问题，请修改文件或字段匹配后重试。' if len(errors) > 30 else ''))
    if not rows:
        raise ValueError('匹配后的列没有可导入内容，请检查字段匹配')
    duplicate_mode = str(form.get('duplicates', 'skip'))
    if duplicate_mode not in {'skip', 'append'}:
        raise ValueError('重复处理方式无效')
    comparison_fields = existing + [f for f in fields if str(f['id']).startswith('new_')]
    seen = set()
    if target and duplicate_mode == 'skip':
        for record in conn.execute('SELECT * FROM work_list_records WHERE list_id=?', (target,)):
            seen.add(_fingerprint(json.loads(record['values_json']), record['status'], record['note'], record['customer_id'], comparison_fields))
    skipped = 0
    for row in rows:
        fingerprint = _fingerprint(row['values'], row['status'], row['note'], row['customer_id'], comparison_fields)
        row['duplicate'] = duplicate_mode == 'skip' and fingerprint in seen
        skipped += row['duplicate']
        seen.add(fingerprint)
    return {'fields': fields, 'rows': rows, 'list_revision': item['revision'] if item else 0,
            'duplicates': duplicate_mode, 'skipped': skipped, 'count': len(rows) - skipped}


def re_split(value):
    import re
    return re.split('[、,，;；\n]', value)


@router.post('/work/list-import/{token}/preview')
async def import_excel_preview(request: Request, token: str):
    form = await request.form()
    _csrf(request, form.get('csrf'))
    with db(immediate=True) as conn:
        job, payload = _job(conn, request, token)
        _revision(form.get('revision'), job['revision'])
        if payload['phase'] not in {'mapping', 'preview'}:
            raise HTTPException(409, '请先选择工作表和范围')
        try:
            payload['plan'] = _plan(conn, payload, form)
            payload['phase'] = 'preview'
            _save(conn, job, payload)
        except (ValueError, HTTPException) as exc:
            error = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
            payload['phase'] = 'mapping'
        else:
            error = ''
    if error:
        return _page(request, job, payload, error, 400)
    return RedirectResponse(f'/work/list-import/{token}', 303)


@router.post('/work/list-import/{token}/confirm')
async def import_excel_confirm(request: Request, token: str):
    form = await request.form()
    _csrf(request, form.get('csrf'))
    with db(immediate=True) as conn:
        job, payload = _job(conn, request, token)
        if payload['phase'] == 'done':
            return RedirectResponse(f'/work/list-import/{token}', 303)
        _revision(form.get('revision'), job['revision'])
        if payload['phase'] != 'preview':
            raise HTTPException(409, '请先生成导入预览')
        plan = payload['plan']
        target, now = payload['target'], now_iso()
        if target:
            item = _list(conn, target, True)
            _revision(plan['list_revision'], item['revision'])
        else:
            cur = conn.execute('INSERT INTO work_lists(title,description,created_at,updated_at) VALUES(?,?,?,?)',
                (payload['title'], '从 Excel 导入：' + payload['filename'] + ' / ' + payload['sheet'], now, now))
            target = cur.lastrowid
        # Customer references can change after preview; do not silently lose an association.
        for row in plan['rows']:
            if row['customer_id'] and not conn.execute('SELECT id FROM customers WHERE id=?', (row['customer_id'],)).fetchone():
                raise HTTPException(409, '关联客户已删除，请重新预览')
        all_fields = _fields(conn, target)
        position = max([f['position'] for f in all_fields], default=-1) + 1
        ids = {}
        for field in plan['fields']:
            if str(field['id']).startswith('new_'):
                cur = conn.execute('INSERT INTO work_list_fields(list_id,label,kind,position) VALUES(?,?,?,?)', (target, field['label'], field['kind'], position))
                ids[str(field['id'])] = str(cur.lastrowid)
                position += 1
        if ids:
            conn.execute('UPDATE work_lists SET revision=revision+1 WHERE id=?', (target,))
        all_fields = _fields(conn, target)
        seen = set()
        if plan['duplicates'] == 'skip':
            for record in conn.execute('SELECT * FROM work_list_records WHERE list_id=?', (target,)):
                seen.add(_fingerprint(json.loads(record['values_json']), record['status'], record['note'], record['customer_id'], all_fields))
        imported = skipped = 0
        for row in plan['rows']:
            values = {ids.get(key, key): value for key, value in row['values'].items()}
            fingerprint = _fingerprint(values, row['status'], row['note'], row['customer_id'], all_fields)
            if plan['duplicates'] == 'skip' and fingerprint in seen:
                skipped += 1
                continue
            conn.execute('''INSERT INTO work_list_records(list_id,customer_id,status,note,values_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?)''', (target, row['customer_id'], row['status'], row['note'], json.dumps(values, ensure_ascii=False), now, now))
            imported += 1
            seen.add(fingerprint)
        conn.execute('UPDATE work_lists SET updated_at=? WHERE id=?', (now, target))
        # Once consumed, discard the uploaded workbook and previews, retaining only the receipt.
        receipt = {'phase': 'done', 'target': target, 'imported': imported, 'skipped': skipped}
        _save(conn, job, receipt)
    return RedirectResponse(f'/work/list-import/{token}', 303)

