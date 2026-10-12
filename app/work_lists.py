"""Independent, user-defined work lists; never writes the payment ledger."""
from __future__ import annotations

import io
import json
from datetime import date
from decimal import Decimal, InvalidOperation

import xlsxwriter
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
from .templating import Jinja2Templates

from . import config
from .db import db, now_iso
from .security import require_csrf

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')
KINDS = {'text': '文本', 'number': '数字', 'money': '金额', 'date': '日期', 'select': '单选', 'multi': '多选'}
PRESETS = {
    'arrears': [('项目 / 号码', 'text', []), ('欠费金额', 'money', []), ('截止日期', 'date', []), ('处理进度', 'select', ['待联系', '已联系', '已缴费'])],
    'opportunity': [('商机名称', 'text', []), ('预计金额', 'money', []), ('预计成交日期', 'date', []), ('阶段', 'select', ['待跟进', '沟通中', '已成交', '已关闭'])],
    'blank': [('内容', 'text', [])],
}
SCHEMA = '''
CREATE TABLE IF NOT EXISTS work_lists (
 id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 archived INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS work_list_fields (
 id INTEGER PRIMARY KEY AUTOINCREMENT, list_id INTEGER NOT NULL REFERENCES work_lists(id) ON DELETE CASCADE,
 label TEXT NOT NULL, kind TEXT NOT NULL, options_json TEXT NOT NULL DEFAULT '[]',
 position INTEGER NOT NULL DEFAULT 0, hidden INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS work_list_records (
 id INTEGER PRIMARY KEY AUTOINCREMENT, list_id INTEGER NOT NULL REFERENCES work_lists(id) ON DELETE CASCADE,
 customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
 status TEXT NOT NULL DEFAULT 'pending', note TEXT NOT NULL DEFAULT '', values_json TEXT NOT NULL DEFAULT '{}',
 revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_work_list_fields ON work_list_fields(list_id,position,id);
CREATE INDEX IF NOT EXISTS idx_work_list_records ON work_list_records(list_id,status,id);
'''


def ensure_work_lists_schema():
    with db() as conn:
        for statement in SCHEMA.split(';'):
            if statement.strip():
                conn.execute(statement)
        from .work_list_sheet import ensure_sheet_schema
        ensure_sheet_schema(conn)


def _ctx(request, **kwargs):
    return {'request': request, 'csrf': request.state.session['csrf_token'],
            'app_version': config.APP_VERSION, 'kinds': KINDS, **kwargs}


def _csrf(request, value):
    try:
        require_csrf(request.state.session, str(value or ''))
    except ValueError:
        raise HTTPException(403, 'CSRF校验失败')


def _text(value, label, maximum=200, required=False):
    value = str(value or '').strip()
    if (required and not value) or len(value) > maximum:
        raise HTTPException(400, f'{label}不能为空且不能超过{maximum}个字符' if required else f'{label}不能超过{maximum}个字符')
    return value


def _list(conn, list_id, writable=False):
    row = conn.execute('SELECT * FROM work_lists WHERE id=?', (list_id,)).fetchone()
    if row is None:
        raise HTTPException(404, '清单不存在')
    if writable and row['archived']:
        raise HTTPException(409, '清单已归档，请先恢复')
    return dict(row)


def _fields(conn, list_id):
    return [dict(row) | {'options': json.loads(row['options_json'])} for row in conn.execute(
        'SELECT * FROM work_list_fields WHERE list_id=? ORDER BY position,id', (list_id,))]


def _record(conn, list_id, record_id):
    row = conn.execute('SELECT * FROM work_list_records WHERE list_id=? AND id=?', (list_id, record_id)).fetchone()
    if row is None:
        raise HTTPException(404, '记录不存在')
    return dict(row) | {'values': json.loads(row['values_json'])}


def _revision(raw, expected):
    if str(raw or '') != str(expected):
        raise HTTPException(409, '内容已被更新，请刷新页面后重新编辑，避免覆盖其他修改')


def _rows(conn, list_id, q='', status=''):
    if status not in {'', 'pending', 'done'}:
        raise HTTPException(400, '状态无效')
    rows = []
    for row in conn.execute('''SELECT r.*,c.name customer_name FROM work_list_records r
        LEFT JOIN customers c ON c.id=r.customer_id WHERE r.list_id=? ORDER BY r.id''', (list_id,)):
        item = dict(row) | {'values': json.loads(row['values_json'])}
        values = [', '.join(v) if isinstance(v, list) else str(v) for v in item['values'].values()]
        if status and item['status'] != status:
            continue
        if q.strip().casefold() not in '\n'.join([item['customer_name'] or '', item['note'], *values]).casefold():
            continue
        rows.append(item)
    return rows


@router.get('/work/lists', response_class=HTMLResponse)
def work_lists_page(request: Request, archived: int = 0, q: str = '', view: str = ''):
    if view not in ('', 'new'):
        raise HTTPException(400, '无效的清单页面')
    with db() as conn:
        lists = [dict(r) for r in conn.execute('''SELECT l.*,
            (SELECT COUNT(*) FROM work_list_records r WHERE r.list_id=l.id) record_count
            FROM work_lists l WHERE archived=? ORDER BY updated_at DESC,id DESC''', (int(bool(archived)),))]
    lists = [l for l in lists if q.strip().casefold() in (l['title'] + '\n' + l['description']).casefold()]
    return templates.TemplateResponse(request, 'work_lists.html', _ctx(request, lists=lists, archived=bool(archived), q=q, view=view, error=''))


@router.post('/work/lists')
async def create_work_list(request: Request):
    form = await request.form()
    _csrf(request, form.get('csrf'))
    title = _text(form.get('title'), '名称', required=True)
    description = _text(form.get('description'), '说明', 2000)
    preset = str(form.get('preset', 'blank'))
    if preset not in PRESETS:
        raise HTTPException(400, '模板无效')
    with db() as conn:
        now = now_iso()
        cur = conn.execute('INSERT INTO work_lists(title,description,created_at,updated_at) VALUES(?,?,?,?)', (title, description, now, now))
        list_id = cur.lastrowid
        if form.get('sheet_payload') and preset == 'blank':
            from .work_list_sheet import create_grid
            try:
                data = json.loads(str(form['sheet_payload']))
            except (ValueError, TypeError):
                raise HTTPException(400, '表格数据无效')
            create_grid(conn, list_id, data)
        for position, (label, kind, options) in enumerate([] if form.get('sheet_payload') and preset == 'blank' else PRESETS[preset]):
            conn.execute('INSERT INTO work_list_fields(list_id,label,kind,options_json,position) VALUES(?,?,?,?,?)',
                         (list_id, label, kind, json.dumps(options, ensure_ascii=False), position))
    return RedirectResponse(f'/work/lists/{list_id}', 303)


@router.get('/work/lists/{list_id}', response_class=HTMLResponse)
def work_list_page(request: Request, list_id: int, q: str = '', status: str = ''):
    with db() as conn:
        item, fields, rows = _list(conn, list_id), _fields(conn, list_id), _rows(conn, list_id, q, status)
        from .work_list_sheet import snapshot
        sheet = snapshot(conn, item, fields, rows)
    return templates.TemplateResponse(request, 'work_list_detail.html', _ctx(request, item=item, fields=fields, rows=rows, q=q, status=status, sheet=sheet, sheet_readonly=bool(item['archived'] or q or status)))


def _sync_list_shortcut(conn, list_id, title=None):
    from .v101_workspace_routes import HOME_SHORTCUTS_KEY, home_shortcuts
    href = f'/work/lists/{list_id}'
    items = home_shortcuts(conn)
    updated = [dict(item, title=title[:40]) if item['href'] == href else item
               for item in items if item['href'] != href or title is not None]
    if updated != items:
        conn.execute('INSERT OR REPLACE INTO app_meta(key,value) VALUES(?,?)',
                     (HOME_SHORTCUTS_KEY, json.dumps(updated, ensure_ascii=False)))


@router.post('/work/lists/{list_id}/metadata')
async def edit_work_list_metadata(request: Request, list_id: int):
    form = await request.form()
    _csrf(request, form.get('csrf'))
    title = _text(form.get('title'), '名称', required=True)
    description = _text(form.get('description'), '说明', 2000)
    with db(immediate=True) as conn:
        item = _list(conn, list_id)
        _revision(form.get('revision'), item['revision'])
        conn.execute('UPDATE work_lists SET title=?,description=?,revision=revision+1,updated_at=? WHERE id=?',
                     (title, description, now_iso(), list_id))
        _sync_list_shortcut(conn, list_id, title)
    return RedirectResponse('/work/lists' + ('?archived=1' if item['archived'] else ''), 303)


@router.post('/work/lists/{list_id}/delete')
async def delete_work_list(request: Request, list_id: int):
    form = await request.form()
    _csrf(request, form.get('csrf'))
    with db(immediate=True) as conn:
        item = _list(conn, list_id)
        _revision(form.get('revision'), item['revision'])
        conn.execute('DELETE FROM work_lists WHERE id=?', (list_id,))
        _sync_list_shortcut(conn, list_id)
    return RedirectResponse('/work/lists', 303)


@router.get('/work/lists/{list_id}/settings', response_class=HTMLResponse)
def work_list_settings(request: Request, list_id: int):
    with db() as conn:
        item, fields = _list(conn, list_id), _fields(conn, list_id)
    return templates.TemplateResponse(request, 'work_list_settings.html', _ctx(request, item=item, fields=fields))


@router.post('/work/lists/{list_id}/settings')
async def save_work_list_settings(request: Request, list_id: int):
    if request.headers.get('content-type', '').split(';')[0] == 'application/json':
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 12 * 1024 * 1024:
                raise HTTPException(413, '表格内容过大')
            chunks.append(chunk)
        raw = b''.join(chunks)
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            raise HTTPException(400, '表格数据无效')
        if not isinstance(data, dict):
            raise HTTPException(400, '表格数据无效')
        _csrf(request, data.get('csrf'))
        from .work_list_sheet import save_grid
        with db(immediate=True) as conn:
            saved = save_grid(conn, list_id, data)
        return JSONResponse(saved)
    form = await request.form()
    _csrf(request, form.get('csrf'))
    title = _text(form.get('title'), '名称', required=True)
    description = _text(form.get('description'), '说明', 2000)
    with db(immediate=True) as conn:
        item = _list(conn, list_id, True)
        _revision(form.get('revision'), item['revision'])
        fields = _fields(conn, list_id)
        changes = []
        for field in fields:
            label = _text(form.get(f'label_{field["id"]}'), '字段名称', 80, True)
            try:
                position = int(form.get(f'position_{field["id"]}', 0))
                if not 0 <= position <= 999:
                    raise ValueError()
            except (ValueError, TypeError):
                raise HTTPException(400, '字段顺序应为0至999的整数')
            changes.append((label, position, int(form.get(f'hidden_{field["id"]}') == '1'), field['id']))
        conn.executemany('UPDATE work_list_fields SET label=?,position=?,hidden=? WHERE id=?', changes)
        conn.execute('UPDATE work_lists SET title=?,description=?,revision=revision+1,updated_at=? WHERE id=?', (title, description, now_iso(), list_id))
    return RedirectResponse(f'/work/lists/{list_id}', 303)


@router.post('/work/lists/{list_id}/fields')
async def add_work_list_field(request: Request, list_id: int):
    form = await request.form()
    _csrf(request, form.get('csrf'))
    label = _text(form.get('label'), '字段名称', 80, True)
    kind = str(form.get('kind', 'text'))
    if kind not in KINDS:
        raise HTTPException(400, '字段类型无效')
    options = list(dict.fromkeys(line.strip() for line in str(form.get('options', '')).splitlines() if line.strip()))
    if kind in {'select', 'multi'} and (not options or len(options) > 50 or any(len(v) > 100 for v in options)):
        raise HTTPException(400, '单选或多选需要1至50个选项，每个选项最多100个字符')
    with db(immediate=True) as conn:
        item = _list(conn, list_id, True)
        _revision(form.get('revision'), item['revision'])
        fields = _fields(conn, list_id)
        if len(fields) >= 50:
            raise HTTPException(400, '每张清单最多50个字段')
        conn.execute('INSERT INTO work_list_fields(list_id,label,kind,options_json,position) VALUES(?,?,?,?,?)',
                     (list_id, label, kind, json.dumps(options if kind in {'select', 'multi'} else [], ensure_ascii=False), max([f['position'] for f in fields], default=-1) + 1))
        conn.execute('UPDATE work_lists SET revision=revision+1,updated_at=? WHERE id=?', (now_iso(), list_id))
    return RedirectResponse(f'/work/lists/{list_id}/settings', 303)


@router.post('/work/lists/{list_id}/archive')
async def archive_work_list(request: Request, list_id: int):
    form = await request.form()
    _csrf(request, form.get('csrf'))
    with db(immediate=True) as conn:
        item = _list(conn, list_id)
        _revision(form.get('revision'), item['revision'])
        conn.execute('UPDATE work_lists SET archived=?,revision=revision+1,updated_at=? WHERE id=?', (1 - item['archived'], now_iso(), list_id))
    return RedirectResponse('/work/lists', 303)


def _edit_context(request, conn, list_id, record_id=None, form=None, error=''):
    item, fields = _list(conn, list_id, True), _fields(conn, list_id)
    record = _record(conn, list_id, record_id) if record_id is not None else {'values': {}, 'note': '', 'customer_id': None, 'status': 'pending', 'revision': 0}
    if form is not None:
        record.update(note=str(form.get('note', '')), customer_id=str(form.get('customer_id', '')), status=str(form.get('status', 'pending')))
        record['values'] = {str(f['id']): form.getlist(f'f_{f["id"]}') if f['kind'] == 'multi' else str(form.get(f'f_{f["id"]}', '')) for f in fields if not f['hidden']}
    customers = conn.execute('SELECT id,name,group_code FROM customers ORDER BY name,id').fetchall()
    return _ctx(request, item=item, fields=fields, record=record, record_id=record_id, customers=customers, error=error)


@router.get('/work/lists/{list_id}/records/new', response_class=HTMLResponse)
def work_list_record_new(request: Request, list_id: int):
    with db() as conn:
        context = _edit_context(request, conn, list_id)
    return templates.TemplateResponse(request, 'work_list_record.html', context)


@router.get('/work/lists/{list_id}/records/{record_id}/edit', response_class=HTMLResponse)
def work_list_record_edit(request: Request, list_id: int, record_id: int):
    with db() as conn:
        context = _edit_context(request, conn, list_id, record_id)
    return templates.TemplateResponse(request, 'work_list_record.html', context)


def _values(form, fields, previous):
    result = dict(previous)
    for field in fields:
        if field['hidden']:
            continue
        key, kind = str(field['id']), field['kind']
        name = f'f_{key}'
        if kind == 'multi':
            value = list(dict.fromkeys(str(v) for v in form.getlist(name)))
            if any(v not in field['options'] for v in value):
                raise HTTPException(400, f'{field["label"]}选项无效')
        else:
            value = _text(form.get(name), field['label'], 4000)
            if value and kind in {'number', 'money'}:
                try:
                    number = Decimal(value)
                    if not number.is_finite() or abs(number) > Decimal('1e15') or number.as_tuple().exponent < -8:
                        raise InvalidOperation()
                    if kind == 'money' and number.as_tuple().exponent < -2:
                        raise InvalidOperation()
                    value = format(number, 'f')
                except InvalidOperation:
                    raise HTTPException(400, f'{field["label"]}必须是有效数字；金额最多2位小数')
            if value and kind == 'date':
                try:
                    value = date.fromisoformat(value).isoformat()
                except ValueError:
                    raise HTTPException(400, f'{field["label"]}日期无效')
            if value and kind == 'select' and value not in field['options']:
                raise HTTPException(400, f'{field["label"]}选项无效')
        result[key] = value
    return result


@router.post('/work/lists/{list_id}/records/new')
@router.post('/work/lists/{list_id}/records/{record_id}/edit')
async def save_work_list_record(request: Request, list_id: int, record_id: int | None = None):
    form = await request.form()
    _csrf(request, form.get('csrf'))
    try:
        with db(immediate=True) as conn:
            item = _list(conn, list_id, True)
            _revision(form.get('list_revision'), item['revision'])
            fields = _fields(conn, list_id)
            old = _record(conn, list_id, record_id) if record_id is not None else {'values': {}, 'revision': 0}
            _revision(form.get('revision'), old['revision'])
            values = _values(form, fields, old['values'])
            note = _text(form.get('note'), '备注', 20000)
            status = str(form.get('status', 'pending'))
            if status not in {'pending', 'done'}:
                raise HTTPException(400, '状态无效')
            raw_customer = str(form.get('customer_id', '')).strip()
            customer_id = None
            if raw_customer:
                if not raw_customer.isdigit() or not conn.execute('SELECT id FROM customers WHERE id=?', (raw_customer,)).fetchone():
                    raise HTTPException(400, '关联客户不存在')
                customer_id = int(raw_customer)
            now = now_iso()
            encoded = json.dumps(values, ensure_ascii=False)
            if record_id is None:
                conn.execute('''INSERT INTO work_list_records(list_id,customer_id,status,note,values_json,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?)''', (list_id, customer_id, status, note, encoded, now, now))
            else:
                conn.execute('''UPDATE work_list_records SET customer_id=?,status=?,note=?,values_json=?,revision=revision+1,updated_at=?
                    WHERE id=? AND list_id=?''', (customer_id, status, note, encoded, now, record_id, list_id))
            conn.execute('UPDATE work_lists SET updated_at=? WHERE id=?', (now, list_id))
    except HTTPException as exc:
        if exc.status_code != 400:
            raise
        with db() as conn:
            context = _edit_context(request, conn, list_id, record_id, form, str(exc.detail))
        return templates.TemplateResponse(request, 'work_list_record.html', context, status_code=400)
    return RedirectResponse(f'/work/lists/{list_id}', 303)


@router.get('/work/lists/{list_id}/export.xlsx')
def export_work_list(request: Request, list_id: int, q: str = '', status: str = ''):
    with db() as conn:
        item = _list(conn, list_id)
        fields = [f for f in _fields(conn, list_id) if not f['hidden']]
        rows = _rows(conn, list_id, q, status)
        from .work_list_sheet import export_grid
        grid_content = export_grid(conn, item, fields, rows)
    if grid_content is not None:
        return Response(grid_content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': f'attachment; filename="work-list-{item["id"]}.xlsx"'})
    output = io.BytesIO()
    with xlsxwriter.Workbook(output, {'in_memory': True, 'strings_to_formulas': False, 'strings_to_urls': False}) as book:
        sheet = book.add_worksheet('清单')
        header = book.add_format({'bold': True, 'bg_color': '#E7EFF8'})
        sheet.freeze_panes(1, 3)
        sheet.set_column(0, 0, 8)
        sheet.set_column(1, len(fields) + 3, 22)
        labels = ['序号', '状态', '关联客户', *[f['label'] for f in fields], '备注']
        for col, label in enumerate(labels):
            sheet.write_string(0, col, label, header)
        for idx, row in enumerate(rows, 1):
            sheet.write_number(idx, 0, idx)
            sheet.write_string(idx, 1, '已完成' if row['status'] == 'done' else '待处理')
            sheet.write_string(idx, 2, row['customer_name'] or '')
            for col, field in enumerate(fields, 3):
                value = row['values'].get(str(field['id']), '')
                if field['kind'] in {'number', 'money'} and value != '':
                    sheet.write_number(idx, col, float(value))
                else:
                    sheet.write_string(idx, col, '、'.join(value) if isinstance(value, list) else str(value))
            sheet.write_string(idx, len(fields) + 3, row['note'])
        sheet.autofilter(0, 0, len(rows), len(labels) - 1)
    return Response(output.getvalue(), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': f'attachment; filename="work-list-{item["id"]}.xlsx"'})

