from __future__ import annotations

import hashlib
import os
import re
import secrets
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

app = FastAPI(title='Chen Assistant Private Storage', docs_url=None, redoc_url=None, openapi_url=None)

ROOT = Path(os.getenv('CHEN_STORAGE_ROOT', '/data/chen-files')).resolve()
TOKEN = os.getenv('CHEN_STORAGE_TOKEN', '').strip()
MAX_FILE_MB = max(1, min(500, int(os.getenv('CHEN_STORAGE_MAX_FILE_MB', '50'))))
MAX_BYTES = MAX_FILE_MB * 1024 * 1024
KEY_RE = re.compile(r'^[a-f0-9]{32}$')


def require_auth(request: Request) -> None:
    if not TOKEN:
        raise HTTPException(503, 'storage token not configured')
    auth = request.headers.get('authorization', '')
    expected = f'Bearer {TOKEN}'
    if not secrets.compare_digest(auth, expected):
        raise HTTPException(401, 'unauthorized')


def object_path(key: str) -> Path:
    if not KEY_RE.fullmatch(key):
        raise HTTPException(400, 'invalid storage key')
    ROOT.mkdir(parents=True, exist_ok=True)
    return ROOT / key


@app.get('/health')
def health():
    ROOT.mkdir(parents=True, exist_ok=True)
    stat = os.statvfs(ROOT)
    return {
        'ok': True,
        'max_file_mb': MAX_FILE_MB,
        'free_bytes': stat.f_bavail * stat.f_frsize,
    }


@app.put('/objects/{key}')
async def put_object(key: str, request: Request):
    require_auth(request)
    target = object_path(key)
    tmp = ROOT / f'.{key}.{uuid.uuid4().hex}.part'
    size = 0
    digest = hashlib.sha256()
    try:
        with tmp.open('wb') as fh:
            async for chunk in request.stream():
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(413, f'file exceeds {MAX_FILE_MB}MB')
                digest.update(chunk)
                fh.write(chunk)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
    return {'ok': True, 'key': key, 'size': size, 'sha256': digest.hexdigest()}


@app.get('/objects/{key}')
def get_object(key: str, request: Request):
    require_auth(request)
    target = object_path(key)
    if not target.is_file():
        raise HTTPException(404, 'not found')
    return FileResponse(target, media_type='application/octet-stream', filename=key)


@app.delete('/objects/{key}')
def delete_object(key: str, request: Request):
    require_auth(request)
    target = object_path(key)
    if not target.exists():
        raise HTTPException(404, 'not found')
    target.unlink()
    return {'ok': True}
