from __future__ import annotations

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import JSONResponse, Response

from .db import db, now_iso
from .v025_routes import promotion_or_404, service_or_404
from .v026_routes import check_csrf, promotion_bucket

from .promotions import ensure_promotion_schema, available_slot, expiry_text, table_payload, export_table
from .v025_routes import customer_or_404

router = APIRouter()


@router.get('/services/{service_id}/promotions-editor-v029')
def service_promotions_editor_v0211(service_id: int):
    with db() as conn:
        service = service_or_404(conn, service_id)
        ensure_promotion_schema(conn)
        rows = conn.execute(
            '''SELECT id,name,expiry_date,notes,status,slot_number FROM promotions
               WHERE service_id=? AND COALESCE(status,'active')='active'
               ORDER BY slot_number,id''',
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
                'expiry_date': expiry_text(row['expiry_date']),
                'slot_number': row['slot_number'],
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
    expiry_date: str = Form(''),
    slot_number: str = Form(''),
    notes: str = Form(''),
):
    check_csrf(request, csrf)
    clean_name = name.strip()[:200]
    if not clean_name:
        raise HTTPException(400, '优惠名称不能为空')
    expiry_iso = expiry_date
    clean_notes = notes.strip()[:2000]

    with db() as conn:
        service = service_or_404(conn, service_id)
        ensure_promotion_schema(conn)
        if promotion_id.strip():
            try:
                pid = int(promotion_id)
            except ValueError:
                raise HTTPException(400, '优惠编号无效')
            row = promotion_or_404(conn, pid)
            if row['service_id'] != service_id:
                raise HTTPException(400, '优惠不属于当前业务')
            slot = available_slot(conn, service_id, slot_number, pid)
            conn.execute(
                "UPDATE promotions SET slot_number=?,name=?,expiry_date=?,notes=?,status='active',renewed_at=? WHERE id=?",
                (slot, clean_name, expiry_iso, clean_notes, now_iso(), pid),
            )
        else:
            slot = available_slot(conn, service_id, slot_number)
            cur = conn.execute(
                '''INSERT INTO promotions(slot_number,service_id,name,start_date,expiry_date,remind_days,status,notes,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)''',
                (slot, service_id, clean_name, '', expiry_iso, 60, 'active', clean_notes, now_iso()),
            )
            pid = int(cur.lastrowid)
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?', (now_iso(), service['customer_id']))
        bucket = promotion_bucket(expiry_iso, 'active')

    return JSONResponse({
        'ok': True,
        'id': pid,
        'service_id': service_id,
        'name': clean_name,
        'expiry_date': expiry_text(expiry_iso),
        'slot_number': slot,
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


@router.get('/customers/{customer_id}/promotions/table')
def full_promotions_table(customer_id: int):
    with db() as conn:
        customer_or_404(conn, customer_id)
        payload = table_payload(conn, customer_id)
    return JSONResponse({'ok': True, **payload})


@router.get('/customers/{customer_id}/promotions/table.xlsx')
def download_full_promotions_table(customer_id: int):
    with db() as conn:
        customer_or_404(conn, customer_id)
        payload = table_payload(conn, customer_id)
    return Response(export_table(payload), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': 'attachment; filename="promotions.xlsx"', 'Cache-Control': 'no-store'})
