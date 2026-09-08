from __future__ import annotations

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import JSONResponse

from .db import db, now_iso
from .v025_routes import promotion_or_404, service_or_404
from .v026_routes import check_csrf, parse_date_text, date_text, promotion_bucket

router = APIRouter()


@router.get('/services/{service_id}/promotions-editor-v029')
def service_promotions_editor_v0211(service_id: int):
    with db() as conn:
        service = service_or_404(conn, service_id)
        rows = conn.execute(
            '''SELECT id,name,expiry_date,notes,status FROM promotions
               WHERE service_id=? AND COALESCE(status,'active')='active'
               ORDER BY expiry_date,id''',
            (service_id,),
        ).fetchall()
    return JSONResponse({
        'ok': True,
        'service_id': service_id,
        'number': service['number'] or '',
        'promotions': [
            {
                'id': row['id'],
                'name': row['name'] or '',
                'expiry_date': date_text(row['expiry_date']),
                'notes': row['notes'] or '',
            }
            for row in rows
        ],
    })


@router.post('/services/{service_id}/promotions-editor-v029')
def save_service_promotion_v0211(
    request: Request,
    service_id: int,
    csrf: str = Form(...),
    promotion_id: str = Form(''),
    name: str = Form(...),
    expiry_date: str = Form(...),
    notes: str = Form(''),
):
    check_csrf(request, csrf)
    clean_name = name.strip()[:200]
    if not clean_name:
        raise HTTPException(400, '优惠名称不能为空')
    expiry_iso = parse_date_text(expiry_date, required=True, field='优惠到期日期')
    clean_notes = notes.strip()[:2000]

    with db() as conn:
        service = service_or_404(conn, service_id)
        if promotion_id.strip():
            try:
                pid = int(promotion_id)
            except ValueError:
                raise HTTPException(400, '优惠编号无效')
            row = promotion_or_404(conn, pid)
            if row['service_id'] != service_id:
                raise HTTPException(400, '优惠不属于当前业务')
            conn.execute(
                "UPDATE promotions SET name=?,expiry_date=?,notes=?,status='active',renewed_at=? WHERE id=?",
                (clean_name, expiry_iso, clean_notes, now_iso(), pid),
            )
        else:
            cur = conn.execute(
                '''INSERT INTO promotions(service_id,name,start_date,expiry_date,remind_days,status,notes,created_at)
                   VALUES(?,?,?,?,?,?,?,?)''',
                (service_id, clean_name, '', expiry_iso, 60, 'active', clean_notes, now_iso()),
            )
            pid = int(cur.lastrowid)
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), service['customer_id']))
        bucket = promotion_bucket(expiry_iso, 'active')

    return JSONResponse({
        'ok': True,
        'id': pid,
        'service_id': service_id,
        'name': clean_name,
        'expiry_date': date_text(expiry_iso),
        'notes': clean_notes,
        'bucket': bucket,
        'visible': bucket in {'expired', 'soon'},
    })


@router.post('/promotions/{promotion_id}/name-v030')
def rename_promotion_v0211(
    request: Request,
    promotion_id: int,
    csrf: str = Form(...),
    name: str = Form(...),
):
    check_csrf(request, csrf)
    clean_name = name.strip()[:200]
    if not clean_name:
        raise HTTPException(400, '优惠名称不能为空')

    with db() as conn:
        row = promotion_or_404(conn, promotion_id)
        service = service_or_404(conn, row['service_id'])
        conn.execute('UPDATE promotions SET name=? WHERE id=?', (clean_name, promotion_id))
        conn.execute(
            'UPDATE customers SET updated_at=? WHERE id=?',
            (now_iso(), service['customer_id']),
        )

    return JSONResponse({
        'ok': True,
        'id': promotion_id,
        'service_id': service['id'],
        'customer_id': service['customer_id'],
        'name': clean_name,
    })


@router.post('/promotions/{promotion_id}/close-editor-v029')
def close_service_promotion_v0211(
    request: Request,
    promotion_id: int,
    csrf: str = Form(...),
):
    check_csrf(request, csrf)
    with db() as conn:
        row = promotion_or_404(conn, promotion_id)
        service = service_or_404(conn, row['service_id'])
        conn.execute("UPDATE promotions SET status='closed' WHERE id=?", (promotion_id,))
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), service['customer_id']))
    return JSONResponse({'ok': True, 'id': promotion_id, 'service_id': service['id']})
