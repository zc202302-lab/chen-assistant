from __future__ import annotations

from fastapi import APIRouter

from .db import db
from .payment_v02 import current_period
from .v025_routes import customer_or_404, _payment_run
from .v0212_routes import payment_snapshot_v0212
from .v028_routes import _promo_columns

router = APIRouter()


@router.get('/customers/{customer_id}/live-snapshot-v15')
def customer_live_snapshot_v15(customer_id: int):
    """Small authoritative snapshot used to keep an open customer page fresh.

    This intentionally returns only summary/state data. Existing mature module
    controllers remain owners of row editing and complex interactions.
    """
    period = current_period()
    with db() as conn:
        customer = customer_or_404(conn, customer_id)
        _, payment_stats = payment_snapshot_v0212(conn, customer_id, period)
        payment_run = _payment_run(conn, customer_id, period, payment_stats)

        promo_rows = conn.execute(
            '''SELECT p.*,s.service_type,s.holder_name,s.number,s.account,s.customer_id
               FROM promotions p JOIN services s ON s.id=p.service_id
               WHERE s.customer_id=? AND COALESCE(p.status,'active')='active'
               ORDER BY p.expiry_date,p.id''',
            (customer_id,),
        ).fetchall()
        promo_columns = _promo_columns(conn, customer_id, promo_rows)
        promo_attention = sum(len(group['items']) for groups in promo_columns.values() for group in groups)

        tasks = conn.execute(
            'SELECT id,title,remind_date,note,done FROM tasks WHERE customer_id=? ORDER BY done,remind_date,id DESC',
            (customer_id,),
        ).fetchall()
        open_tasks = [row for row in tasks if not row['done']]
        service_count = conn.execute(
            'SELECT COUNT(*) n FROM services WHERE customer_id=?', (customer_id,)
        ).fetchone()['n']
        contact_count = conn.execute(
            'SELECT COUNT(*) n FROM contacts WHERE customer_id=?', (customer_id,)
        ).fetchone()['n']
        visit_count = conn.execute(
            'SELECT COUNT(*) n FROM visits WHERE customer_id=?', (customer_id,)
        ).fetchone()['n']

    return {
        'ok': True,
        'customer': {
            'id': int(customer['id']),
            'name': customer['name'] or '',
            'group_code': customer['group_code'] or '',
            'tax_id': customer['tax_id'] or '',
            'payment_enabled': bool(customer['payment_enabled']),
        },
        'counts': {
            'services': int(service_count or 0),
            'promotions': int(promo_attention or 0),
            'contacts': int(contact_count or 0),
            'tasks_open': len(open_tasks),
            'visits': int(visit_count or 0),
        },
        'task_preview': [
            {
                'id': int(row['id']),
                'title': row['title'] or '',
                'remind_date': row['remind_date'] or '',
                'note': row['note'] or '',
            }
            for row in open_tasks[:2]
        ],
        'payment': {
            'period': period,
            'stats': payment_stats,
            'run': payment_run,
        },
    }
