from __future__ import annotations

from datetime import date
from urllib.parse import quote_plus

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from .templating import Jinja2Templates

from . import config
from .db import db, now_iso
from .payment_v02 import current_period, parse_money, service_active_in_period, service_is_due
from .v023_routes import service_or_404
from .v026_routes import check_csrf
from . import v031_fixed_review_patch as review
from . import v031_payment_workflow_routes as workflow

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')


def _ctx(request: Request, **extra):
    session = getattr(request.state, 'session', None)
    base = {
        'request': request,
        'csrf': session['csrf_token'] if session else '',
        'today': date.today(),
        'app_username': config.APP_USERNAME,
        'app_version': config.APP_VERSION,
    }
    base.update(extra)
    return base


@router.post('/services/{service_id}/payment-current')
def payment_save_preserve_reviews_v032(
    request: Request,
    service_id: int,
    csrf: str = Form(...),
    amount: str = Form(...),
):
    """Enter means save *and* confirm this row.

    A real amount change still invalidates notification / initiation / paid workflow
    state that was based on the old amount, but the row just entered is immediately
    confirmed. This keeps the spreadsheet-like invariant users expect on every
    customer payment page: type amount -> Enter -> checkmark -> next pending row.
    """
    check_csrf(request, csrf)
    period = current_period()
    value = parse_money(amount)

    with db() as conn:
        service = service_or_404(conn, service_id)
        existing_current = conn.execute(
            'SELECT id FROM payment_entries WHERE service_id=? AND period=?',
            (service_id, period),
        ).fetchone()
        if not service_active_in_period(service, period) or (not service_is_due(service) and not existing_current):
            return JSONResponse({'ok': False, 'error': '这项业务本月不在缴费范围内'}, status_code=400)

        entry, rule = review._ensure_payment_entry_review_aware(conn, service, period)
        previous = float(entry['amount'] or 0)
        amount_changed = abs(float(value) - previous) > 0.000001
        run = None
        if amount_changed:
            run, _ = workflow._run_v031(conn, service['customer_id'], period)
            if run['paid']:
                review._rollback_completed_payment(conn, int(service['customer_id']), period, run)

        reference = entry['reference_amount']
        if reference is None:
            reference = previous
        now = now_iso()
        source = 'fixed' if rule['mode'] == 'fixed' else 'manual'

        conn.execute(
            '''UPDATE payment_entries
               SET amount=?,reference_amount=?,source=?,confirmed=1,updated_at=? WHERE id=?''',
            (value, reference, source, now, entry['id']),
        )
        conn.execute('UPDATE services SET monthly_fee=? WHERE id=?', (value, service_id))

        if rule['mode'] == 'fixed':
            conn.execute(
                '''INSERT INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(service_id,effective_period)
                   DO UPDATE SET mode='fixed',fixed_amount=excluded.fixed_amount''',
                (service_id, period, 'fixed', value, now),
            )
            conn.execute('UPDATE services SET fixed_fee=1 WHERE id=?', (service_id,))

        if amount_changed and run and not run['paid']:
            workflow._invalidate_after_amount_change(conn, service['customer_id'], period, run)

        payload = review._payment_payload(conn, service['customer_id'], period, service_id)
        current_run, current_stats = workflow._run_v031(conn, service['customer_id'], period)
        payload.update(current_stats)
        payload['workflow_invalidated'] = amount_changed
        payload['workflow_run'] = current_run
        payload['enter_confirmed'] = True
        return JSONResponse(payload)


payment_save_preserve_reviews_v032.__module__ = 'app.v031_fixed_review_patch'


def _compact_number(value: str) -> str:
    return ''.join(ch for ch in (value or '') if ch.isdigit())


def _suggest_item(kind: str, title: str, meta: str, href: str) -> dict[str, str]:
    return {'kind': kind, 'title': title or '', 'meta': meta or '', 'href': href}


@router.get('/quick-search-suggest')
def quick_search_suggest_v151(q: str = '', scope: str = 'work'):
    """Small, customer-first suggestion payload for the top-bar quick search.

    This endpoint never changes the current page. The browser only navigates after
    the user chooses a suggestion or explicitly submits the full search form.
    """
    q = q.strip()
    if not q:
        return JSONResponse({'ok': True, 'groups': []})

    scope = 'global' if scope == 'global' else 'work'
    like = f'%{q}%'
    compact = _compact_number(q)
    groups: list[dict] = []

    with db() as conn:
        customers = conn.execute(
            '''SELECT DISTINCT c.id,c.name,c.group_code,c.tax_id FROM customers c
               LEFT JOIN services s ON s.customer_id=c.id
               LEFT JOIN contacts k ON k.customer_id=c.id
               WHERE c.name LIKE ? OR c.group_code LIKE ? OR c.tax_id LIKE ?
                  OR s.number LIKE ? OR s.account LIKE ? OR s.holder_name LIKE ? OR k.name LIKE ?
                  OR (?<>'' AND REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(s.number,' ',''),'-',''),'(',''),')',''),'—','') LIKE ?)
               ORDER BY CASE WHEN c.name=? THEN 0 WHEN c.name LIKE ? THEN 1 ELSE 2 END,c.name
               LIMIT 6''',
            (like, like, like, like, like, like, like, compact, f'%{compact}%', q, f'{q}%'),
        ).fetchall()
        if customers:
            groups.append({
                'label': '客户',
                'items': [
                    _suggest_item(
                        'customer', row['name'],
                        ' · '.join(x for x in (row['group_code'], row['tax_id']) if x),
                        f"/customers/{row['id']}",
                    ) for row in customers
                ],
            })

        services = conn.execute(
            '''SELECT s.id service_id,s.customer_id,c.name customer_name,
                      s.service_type,s.holder_name,s.number,s.account
               FROM services s JOIN customers c ON c.id=s.customer_id
               WHERE s.number LIKE ? OR s.account LIKE ? OR s.holder_name LIKE ? OR s.service_type LIKE ?
                  OR (?<>'' AND REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(s.number,' ',''),'-',''),'(',''),')',''),'—','') LIKE ?)
               ORDER BY CASE WHEN s.number=? OR s.account=? THEN 0 ELSE 1 END,c.name,s.sort_order,s.id
               LIMIT 6''',
            (like, like, like, like, compact, f'%{compact}%', q, q),
        ).fetchall()
        if services:
            groups.append({
                'label': '号码 / 账号',
                'items': [
                    _suggest_item(
                        'service',
                        row['number'] or row['account'] or row['holder_name'] or row['service_type'] or '业务',
                        ' · '.join(x for x in (row['customer_name'], row['holder_name'], row['account'] if row['number'] else '') if x),
                        f"/customers/{row['customer_id']}?tab=services&focus_service={row['service_id']}",
                    ) for row in services
                ],
            })

        if scope == 'global':
            accounts = conn.execute(
                '''SELECT id,platform,username,email FROM website_accounts
                   WHERE platform LIKE ? OR url LIKE ? OR username LIKE ? OR email LIKE ? OR tags LIKE ?
                   ORDER BY platform LIMIT 5''',
                (like, like, like, like, like),
            ).fetchall()
            if accounts:
                groups.append({
                    'label': '网站账户',
                    'items': [
                        _suggest_item(
                            'account', row['platform'] or row['username'] or '网站账户',
                            row['username'] or row['email'] or '', f"/accounts/{row['id']}",
                        ) for row in accounts
                    ],
                })

            recipes = conn.execute(
                '''SELECT r.id,r.name,r.category FROM recipes r
                   WHERE r.archived=0 AND (r.name LIKE ? OR r.category LIKE ? OR r.tags LIKE ? OR r.description LIKE ?)
                   ORDER BY CASE WHEN r.name=? THEN 0 WHEN r.name LIKE ? THEN 1 ELSE 2 END,r.name LIMIT 5''',
                (like, like, like, like, q, f'{q}%'),
            ).fetchall()
            if recipes:
                groups.append({
                    'label': '菜谱',
                    'items': [_suggest_item('recipe', row['name'], row['category'], f"/life/recipes/{row['id']}") for row in recipes],
                })

            knowledge = conn.execute(
                '''SELECT id,category,title FROM cooking_knowledge
                   WHERE title LIKE ? OR category LIKE ? OR content LIKE ?
                   ORDER BY CASE WHEN title=? THEN 0 WHEN title LIKE ? THEN 1 ELSE 2 END,category,title LIMIT 5''',
                (like, like, like, q, f'{q}%'),
            ).fetchall()
            if knowledge:
                groups.append({
                    'label': '烹饪知识',
                    'items': [
                        _suggest_item('knowledge', row['title'], row['category'], f"/life/knowledge?q={quote_plus(row['title'])}")
                        for row in knowledge
                    ],
                })

    return JSONResponse({'ok': True, 'groups': groups})


@router.get('/search', response_class=HTMLResponse)
def work_search_v124(request: Request, q: str = ''):
    q = q.strip()
    customers = []
    service_hits = []
    if q:
        like = f'%{q}%'
        compact = _compact_number(q)
        with db() as conn:
            service_hits = conn.execute(
                '''SELECT s.id service_id,s.customer_id,c.name customer_name,c.group_code,
                          s.service_type,s.holder_name,s.number,s.account
                   FROM services s JOIN customers c ON c.id=s.customer_id
                   WHERE s.number LIKE ? OR s.account LIKE ? OR s.holder_name LIKE ?
                      OR s.service_type LIKE ? OR c.name LIKE ? OR c.group_code LIKE ?
                      OR (?<>'' AND REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(s.number,' ',''),'-',''),'(',''),')',''),'—','') LIKE ?)
                   ORDER BY CASE WHEN s.number=? OR s.account=? THEN 0 ELSE 1 END,
                            c.name,s.sort_order,s.id LIMIT 50''',
                (like, like, like, like, like, like, compact, f'%{compact}%', q, q),
            ).fetchall()
            customers = conn.execute(
                '''SELECT DISTINCT c.id,c.name,c.group_code,c.tax_id FROM customers c
                   LEFT JOIN services s ON s.customer_id=c.id
                   LEFT JOIN contacts k ON k.customer_id=c.id
                   WHERE c.name LIKE ? OR c.group_code LIKE ? OR c.tax_id LIKE ?
                      OR s.number LIKE ? OR s.account LIKE ? OR s.holder_name LIKE ? OR k.name LIKE ?
                      OR (?<>'' AND REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(s.number,' ',''),'-',''),'(',''),')',''),'—','') LIKE ?)
                   ORDER BY c.name LIMIT 50''',
                (like, like, like, like, like, like, like, compact, f'%{compact}%'),
            ).fetchall()
    return templates.TemplateResponse(
        'search.html',
        _ctx(request, q=q, customers=customers, service_hits=service_hits),
    )


work_search_v124.__name__ = 'work_search_v101'
work_search_v124.__module__ = 'app.v10_routes'

