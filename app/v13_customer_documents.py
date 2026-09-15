from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from . import config
from .db import db
from .v026_routes import check_csrf

router = APIRouter()

ALLOWED_EXTENSIONS = {
    '.pdf', '.jpg', '.jpeg', '.png', '.webp', '.doc', '.docx', '.xls', '.xlsx',
    '.ppt', '.pptx', '.txt', '.zip', '.rar', '.7z'
}
CATEGORIES = {'营业执照', '合同', '报价单', '方案', '身份证明', '其他'}
_KEY_RE = re.compile(r'^[a-f0-9]{32}$')


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def ensure_v13_customer_documents() -> None:
    with db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS customer_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                category TEXT NOT NULL DEFAULT '其他',
                original_name TEXT NOT NULL,
                storage_key TEXT NOT NULL UNIQUE,
                size INTEGER NOT NULL DEFAULT 0,
                mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
                sha256 TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_customer_documents_customer ON customer_documents(customer_id, created_at DESC)')


def _customer_exists(conn, customer_id: int) -> bool:
    return bool(conn.execute('SELECT 1 FROM customers WHERE id=?', (customer_id,)).fetchone())


def _storage_configured() -> bool:
    return bool(config.REMOTE_STORAGE_BASE_URL and config.REMOTE_STORAGE_TOKEN)


def _storage_headers() -> dict[str, str]:
    return {'Authorization': f'Bearer {config.REMOTE_STORAGE_TOKEN}'}


def _storage_url(key: str) -> str:
    base = config.REMOTE_STORAGE_BASE_URL.rstrip('/')
    return f'{base}/objects/{key}'


def _safe_download_name(name: str) -> str:
    cleaned = (name or 'download').replace('\r', ' ').replace('\n', ' ').replace('"', '')
    return cleaned[:180] or 'download'


async def _best_effort_remote_delete(storage_key: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.delete(_storage_url(storage_key), headers=_storage_headers())
    except Exception:
        pass


@router.get('/customers/{customer_id}/documents-v13')
def list_documents_v13(customer_id: int):
    ensure_v13_customer_documents()
    with db() as conn:
        if not _customer_exists(conn, customer_id):
            raise HTTPException(404, '客户不存在')
        rows = conn.execute(
            '''SELECT id,category,original_name,size,mime_type,sha256,created_at
               FROM customer_documents WHERE customer_id=? ORDER BY id DESC''',
            (customer_id,),
        ).fetchall()
    return {
        'ok': True,
        'storage_configured': _storage_configured(),
        'max_file_mb': config.REMOTE_STORAGE_MAX_FILE_MB,
        'categories': sorted(CATEGORIES),
        'items': [dict(row) for row in rows],
    }


@router.post('/customers/{customer_id}/documents-v13')
async def upload_document_v13(
    request: Request,
    customer_id: int,
    csrf: str = Form(...),
    category: str = Form('其他'),
    file: UploadFile = File(...),
):
    check_csrf(request, csrf)
    ensure_v13_customer_documents()
    with db() as conn:
        if not _customer_exists(conn, customer_id):
            raise HTTPException(404, '客户不存在')
    if not _storage_configured():
        raise HTTPException(503, '远程资料存储尚未配置')

    original_name = _safe_download_name(file.filename or '')
    suffix = os.path.splitext(original_name)[1].lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f'不支持的文件类型：{suffix or "无扩展名"}')
    category = category if category in CATEGORIES else '其他'
    max_bytes = int(config.REMOTE_STORAGE_MAX_FILE_MB) * 1024 * 1024
    storage_key = uuid.uuid4().hex
    digest = hashlib.sha256()
    sent = 0
    mime_type = file.content_type or mimetypes.guess_type(original_name)[0] or 'application/octet-stream'

    async def body_stream():
        nonlocal sent
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            sent += len(chunk)
            if sent > max_bytes:
                raise HTTPException(413, f'单个文件不能超过 {config.REMOTE_STORAGE_MAX_FILE_MB}MB')
            digest.update(chunk)
            yield chunk

    headers = _storage_headers()
    headers.update({
        'X-Original-Name': quote(original_name, safe=''),
        'X-Max-Bytes': str(max_bytes),
        'Content-Type': mime_type,
    })
    timeout = httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.put(_storage_url(storage_key), headers=headers, content=body_stream())
            if response.status_code >= 400:
                detail = response.text[:300] or f'远程存储返回 {response.status_code}'
                raise HTTPException(502, f'远程存储失败：{detail}')
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f'无法连接美国资料存储节点：{exc}') from exc
    finally:
        await file.close()

    try:
        with db() as conn:
            cur = conn.execute(
                '''INSERT INTO customer_documents
                   (customer_id,category,original_name,storage_key,size,mime_type,sha256,created_at)
                   VALUES(?,?,?,?,?,?,?,?)''',
                (customer_id, category, original_name, storage_key, sent, mime_type, digest.hexdigest(), _now_iso()),
            )
            document_id = int(cur.lastrowid)
    except Exception:
        await _best_effort_remote_delete(storage_key)
        raise
    return JSONResponse({'ok': True, 'id': document_id, 'name': original_name, 'size': sent})


@router.get('/customers/{customer_id}/documents-v13/{document_id}/download')
async def download_document_v13(customer_id: int, document_id: int):
    ensure_v13_customer_documents()
    if not _storage_configured():
        raise HTTPException(503, '远程资料存储尚未配置')
    with db() as conn:
        row = conn.execute(
            '''SELECT id,customer_id,original_name,storage_key,size,mime_type,sha256
               FROM customer_documents WHERE id=? AND customer_id=?''',
            (document_id, customer_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, '资料不存在')
    if not _KEY_RE.fullmatch(row['storage_key']):
        raise HTTPException(500, '资料存储标识无效')

    client = httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0))
    try:
        remote = await client.send(
            client.build_request('GET', _storage_url(row['storage_key']), headers=_storage_headers()),
            stream=True,
        )
    except Exception as exc:
        await client.aclose()
        raise HTTPException(502, f'无法连接美国资料存储节点：{exc}') from exc
    if remote.status_code != 200:
        status = remote.status_code
        await remote.aclose()
        await client.aclose()
        if status == 404:
            raise HTTPException(404, '美国节点中的文件不存在')
        raise HTTPException(502, f'美国资料存储节点返回 {status}')

    async def iterator():
        try:
            async for chunk in remote.aiter_bytes(1024 * 1024):
                yield chunk
        finally:
            await remote.aclose()
            await client.aclose()

    name = _safe_download_name(row['original_name'])
    disposition = f"attachment; filename*=UTF-8''{quote(name, safe='')}"
    return StreamingResponse(
        iterator(),
        media_type=row['mime_type'] or 'application/octet-stream',
        headers={
            'Content-Disposition': disposition,
            'Content-Length': str(int(row['size'] or 0)),
            'X-Content-SHA256': row['sha256'] or '',
        },
    )


@router.post('/customers/{customer_id}/documents-v13/{document_id}/delete')
async def delete_document_v13(request: Request, customer_id: int, document_id: int, csrf: str = Form(...)):
    check_csrf(request, csrf)
    ensure_v13_customer_documents()
    if not _storage_configured():
        raise HTTPException(503, '远程资料存储尚未配置')
    with db() as conn:
        row = conn.execute(
            'SELECT id,storage_key FROM customer_documents WHERE id=? AND customer_id=?',
            (document_id, customer_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, '资料不存在')

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.delete(_storage_url(row['storage_key']), headers=_storage_headers())
            if response.status_code not in (200, 204, 404):
                raise HTTPException(502, f'美国资料存储节点返回 {response.status_code}')
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f'无法连接美国资料存储节点：{exc}') from exc

    with db() as conn:
        conn.execute('DELETE FROM customer_documents WHERE id=? AND customer_id=?', (document_id, customer_id))
    return {'ok': True}
