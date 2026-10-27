"""Native adapter for the existing single public collection and pending page.

Direct mini-program entry uses the same public collection as the web invitation.
Pending responses expose only the fields already shown by the public web page;
admin/desktop credentials, notes and completed records remain private.
"""
import json

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from .db import db
from .number_collection import collect_numbers, normalize_number
from .v162_number_inbox import _token_matches, ensure_number_inbox_schema, _pending_items

router = APIRouter()
MAX_BODY_BYTES = 32768


def authorize(invite):
    if not invite or len(invite) > 128 or not invite.isascii():
        raise HTTPException(401, '收集入口码无效或已更换，请联系入口提供者')
    with db() as conn:
        if not _token_matches(conn, invite):
            raise HTTPException(401, '收集入口码无效或已更换，请联系入口提供者')


def save_submission(invite, numbers):
    # Validate every number before writing any; invitation is rechecked inside
    # the transaction in case it was rotated while the request was received.
    normalized = [normalize_number(value)[1] for value in numbers if value.strip()]
    if not normalized:
        raise HTTPException(400, '请至少填写一个号码')
    with db() as conn:
        if not _token_matches(conn, invite):
            raise HTTPException(401, '收集入口码已更换，请联系入口提供者')
        result = collect_numbers(conn, normalized)
    return {'ok': True, 'received': result['received'], 'added': result['added'],
            'duplicates': result['duplicates'], 'batch': result['batch']}


@router.get('/number-submit/mini/entry')
def mini_program_entry():
    # This product has one public inbox. Resolve its current invitation server-side
    # so opening the mini program needs no per-device setup or embedded secret.
    with db() as conn:
        invite = ensure_number_inbox_schema(conn)
    return {'ok': True, 'invite': invite}


@router.get('/number-submit/mini/pending')
def mini_program_pending(request: Request, batch: str = ''):
    scheme, _, invite = request.headers.get('authorization', '').partition(' ')
    authorize(invite if scheme.lower() == 'bearer' else '')
    if len(batch) > 128 or (batch and not all(c.isascii() and (c.isalnum() or c in '_-') for c in batch)):
        raise HTTPException(400, '提交批次格式错误')
    with db() as conn:
        if not _token_matches(conn, invite):
            raise HTTPException(401, '收集入口码已更换，请重新打开小程序')
        items = [{'number': row['number'], 'submitted_display': row['submitted_display'],
                  'is_new': row['is_new']} for row in _pending_items(conn, batch)]
    return {'ok': True, 'items': items}


@router.post('/number-submit/mini/submit')
async def mini_program_submit(request: Request):
    scheme, _, invite = request.headers.get('authorization', '').partition(' ')
    await run_in_threadpool(authorize, invite if scheme.lower() == 'bearer' else '')
    if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
        raise HTTPException(415, '请使用JSON提交')
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(413, '提交内容过大')
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError):
        raise HTTPException(400, '提交内容格式错误')
    if not isinstance(payload, dict) or payload.get('consent') is not True:
        raise HTTPException(400, '请先阅读并同意号码收集说明')
    numbers = payload.get('numbers')
    if not isinstance(numbers, list) or not 1 <= len(numbers) <= 100:
        raise HTTPException(400, '每次请提交1至100个号码')
    if any(not isinstance(value, str) for value in numbers):
        raise HTTPException(400, '号码必须是文本')
    return await run_in_threadpool(save_submission, invite, numbers)


mini_program_submit.__public_token_authenticated__ = True
