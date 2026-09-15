from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from .db import db, now_iso
from .v026_routes import check_csrf
from . import v13_customer_documents as documents


router = APIRouter()
RESOURCE_TABLE = 'customer_resource_items_v143'


def _clean(value: str, limit: int) -> str:
    return ' '.join((value or '').strip().split())[:limit]


def _clean_multiline(value: str, limit: int) -> str:
    return (value or '').strip()[:limit]


def ensure_customer_resources_v143() -> None:
    with db() as conn:
        conn.execute(
            f'''CREATE TABLE IF NOT EXISTS {RESOURCE_TABLE} (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                   resource_type TEXT NOT NULL DEFAULT '资料',
                   name TEXT NOT NULL DEFAULT '',
                   value TEXT NOT NULL DEFAULT '',
                   note TEXT NOT NULL DEFAULT '',
                   created_at TEXT NOT NULL,
                   updated_at TEXT NOT NULL
               )'''
        )
        conn.execute(
            f'CREATE INDEX IF NOT EXISTS idx_{RESOURCE_TABLE}_customer ON {RESOURCE_TABLE}(customer_id,id DESC)'
        )


def _customer_exists(conn, customer_id: int) -> bool:
    return bool(conn.execute('SELECT 1 FROM customers WHERE id=?', (int(customer_id),)).fetchone())


def _row_payload(row) -> dict:
    return {
        'id': int(row['id']),
        'resource_type': row['resource_type'] or '资料',
        'name': row['name'] or '',
        'value': row['value'] or '',
        'note': row['note'] or '',
        'created_at': row['created_at'] or '',
        'updated_at': row['updated_at'] or '',
    }


@router.get('/customers/{customer_id}/resource-items-v143')
def list_customer_resources_v143(customer_id: int):
    ensure_customer_resources_v143()
    with db() as conn:
        if not _customer_exists(conn, customer_id):
            raise HTTPException(404, '客户不存在')
        rows = conn.execute(
            f'''SELECT * FROM {RESOURCE_TABLE}
                WHERE customer_id=? ORDER BY id DESC''',
            (int(customer_id),),
        ).fetchall()
    return {'ok': True, 'items': [_row_payload(row) for row in rows]}


@router.post('/customers/{customer_id}/resource-items-v143')
def save_customer_resource_v143(
    request: Request,
    customer_id: int,
    csrf: str = Form(...),
    item_id: str = Form(''),
    resource_type: str = Form('资料'),
    name: str = Form(''),
    value: str = Form(''),
    note: str = Form(''),
):
    check_csrf(request, csrf)
    ensure_customer_resources_v143()
    clean_type = _clean(resource_type, 60) or '资料'
    clean_name = _clean(name, 160)
    clean_value = _clean_multiline(value, 8000)
    clean_note = _clean_multiline(note, 4000)
    if not clean_name and not clean_value:
        raise HTTPException(400, '名称和内容至少填写一项')

    with db() as conn:
        if not _customer_exists(conn, customer_id):
            raise HTTPException(404, '客户不存在')
        now = now_iso()
        if item_id.strip():
            try:
                rid = int(item_id)
            except ValueError:
                raise HTTPException(400, '资料编号无效')
            row = conn.execute(
                f'SELECT id FROM {RESOURCE_TABLE} WHERE id=? AND customer_id=?',
                (rid, int(customer_id)),
            ).fetchone()
            if not row:
                raise HTTPException(404, '资料不存在')
            conn.execute(
                f'''UPDATE {RESOURCE_TABLE}
                    SET resource_type=?,name=?,value=?,note=?,updated_at=?
                    WHERE id=? AND customer_id=?''',
                (clean_type, clean_name, clean_value, clean_note, now, rid, int(customer_id)),
            )
        else:
            cur = conn.execute(
                f'''INSERT INTO {RESOURCE_TABLE}
                    (customer_id,resource_type,name,value,note,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?)''',
                (int(customer_id), clean_type, clean_name, clean_value, clean_note, now, now),
            )
            rid = int(cur.lastrowid)
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now, int(customer_id)))
        saved = conn.execute(
            f'SELECT * FROM {RESOURCE_TABLE} WHERE id=? AND customer_id=?',
            (rid, int(customer_id)),
        ).fetchone()
    return JSONResponse({'ok': True, 'item': _row_payload(saved)})


@router.post('/customers/{customer_id}/resource-items-v143/{item_id}/delete')
def delete_customer_resource_v143(
    request: Request,
    customer_id: int,
    item_id: int,
    csrf: str = Form(...),
):
    check_csrf(request, csrf)
    ensure_customer_resources_v143()
    with db() as conn:
        if not _customer_exists(conn, customer_id):
            raise HTTPException(404, '客户不存在')
        row = conn.execute(
            f'SELECT id FROM {RESOURCE_TABLE} WHERE id=? AND customer_id=?',
            (int(item_id), int(customer_id)),
        ).fetchone()
        if not row:
            raise HTTPException(404, '资料不存在')
        conn.execute(
            f'DELETE FROM {RESOURCE_TABLE} WHERE id=? AND customer_id=?',
            (int(item_id), int(customer_id)),
        )
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), int(customer_id)))
    return {'ok': True, 'id': int(item_id)}


@router.post('/customers/{customer_id}/documents-v13')
async def upload_document_free_category_v143(
    request: Request,
    customer_id: int,
    csrf: str = Form(...),
    category: str = Form('文件'),
    file: UploadFile = File(...),
):
    """Reuse the proven remote-file pipeline while allowing any user-entered type."""
    clean_category = _clean(category, 80) or '文件'
    response = await documents.upload_document_v13(
        request=request,
        customer_id=customer_id,
        csrf=csrf,
        category='其他',
        file=file,
    )
    if getattr(response, 'status_code', 200) >= 400:
        return response
    try:
        payload = json.loads(response.body.decode('utf-8'))
        document_id = int(payload['id'])
    except Exception as exc:
        raise HTTPException(500, '文件上传完成，但资料索引返回异常') from exc

    with db() as conn:
        conn.execute(
            'UPDATE customer_documents SET category=? WHERE id=? AND customer_id=?',
            (clean_category, document_id, int(customer_id)),
        )
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), int(customer_id)))
    payload['category'] = clean_category
    return JSONResponse(payload)
