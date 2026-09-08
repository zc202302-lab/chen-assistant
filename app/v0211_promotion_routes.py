from __future__ import annotations

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import JSONResponse

from .db import db, now_iso
from .v025_routes import promotion_or_404, service_or_404
from .v026_routes import check_csrf

router = APIRouter()


@router.post('/promotions/{promotion_id}/name-v030')
def rename_promotion_v0211(
    request: Request,
    promotion_id: int,
    csrf: str = Form(...),
    name: str = Form(...),
):
    """Rename an existing promotion from the v0.2.11 promotions workspace.

    v0.2.11 still uses the v030 inline-rename URL in service-promotions.js.
    Keep that URL owned by the current runtime router so the feature does not
    depend on an older compatibility router remaining mounted.
    """
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
