"""Persistent directory order; filtered moves preserve hidden customer slots."""
import hashlib
import json

from fastapi import APIRouter, Form, HTTPException, Request
from .db import db
from .security import require_csrf

router = APIRouter()
ORDER_KEY = 'customer_directory_order'


def directory_order(conn):
    baseline = [row['id'] for row in conn.execute('SELECT id FROM customers ORDER BY name,id')]
    entry = conn.execute('SELECT value FROM app_meta WHERE key=?', (ORDER_KEY,)).fetchone()
    try:
        saved = json.loads(entry['value']) if entry else []
    except (ValueError, TypeError):
        saved = []
    if not isinstance(saved, list):
        saved = []
    existing = set(baseline)
    seen = set()
    ordered = []
    for cid in saved:
        if type(cid) is int and cid in existing and cid not in seen:
            ordered.append(cid)
            seen.add(cid)
    ordered.extend(cid for cid in baseline if cid not in seen)
    revision = hashlib.sha256(json.dumps(ordered).encode()).hexdigest()
    return ordered, revision


@router.post('/customers/order')
def save_customer_order(request: Request, csrf: str = Form(...), ids_json: str = Form(...), revision: str = Form(...)):
    try:
        require_csrf(request.state.session, csrf)
    except ValueError:
        raise HTTPException(403, '请刷新页面后重试')
    try:
        ids = json.loads(ids_json)
    except ValueError:
        raise HTTPException(400, '排序数据无效')
    if not isinstance(ids, list) or not ids or any(type(cid) is not int or cid <= 0 for cid in ids) or len(set(ids)) != len(ids):
        raise HTTPException(400, '排序数据无效')
    # Serialize comparison and write; two windows cannot silently overwrite.
    with db(immediate=True) as conn:
        current, expected = directory_order(conn)
        if revision != expected:
            raise HTTPException(409, '客户列表已更新，请刷新后重新排序')
        selected = set(ids)
        if not selected.issubset(set(current)):
            raise HTTPException(400, '客户不存在，请刷新后重试')
        incoming = iter(ids)
        result = [next(incoming) if cid in selected else cid for cid in current]
        conn.execute('INSERT OR REPLACE INTO app_meta(key,value) VALUES(?,?)', (ORDER_KEY, json.dumps(result)))
        _, updated_revision = directory_order(conn)
    return {'ok': True, 'revision': updated_revision}
