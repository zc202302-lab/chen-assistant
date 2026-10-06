from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from .templating import Jinja2Templates

from . import config
from .db import db
from .v12_migration import ensure_v12_schema

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')


def _ctx(request: Request, **extra):
    session = getattr(request.state, 'session', None)
    data = {
        'request': request,
        'csrf': session['csrf_token'] if session else '',
        'today': date.today(),
        'app_version': config.APP_VERSION,
    }
    data.update(extra)
    return data


def _recipe_or_404(conn, recipe_id: int):
    row = conn.execute('SELECT * FROM recipes WHERE id=? AND archived=0', (recipe_id,)).fetchone()
    if not row:
        raise HTTPException(404, '菜谱不存在')
    return row


def _current_version(conn, recipe):
    row = conn.execute('SELECT * FROM recipe_versions WHERE id=?', (recipe['current_version_id'],)).fetchone()
    if not row:
        raise HTTPException(409, '菜谱没有当前标准版本')
    return row


def _display_number(value):
    if value is None:
        return ''
    value = float(value)
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f'{value:.2f}'.rstrip('0').rstrip('.')


def _recipe_payload(conn, version, amount: float | None):
    target = float(amount if amount is not None else version['base_amount'])
    base = float(version['base_amount'] or 0)
    rows = conn.execute(
        'SELECT * FROM recipe_ingredients WHERE version_id=? ORDER BY sort_order,id',
        (version['id'],),
    ).fetchall()
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = row['amount']
        if value is not None and row['scale_mode'] == 'proportional' and base > 0:
            value = float(value) * target / base
        groups[row['group_name'] or '配料'].append({
            'name': row['name'],
            'amount': _display_number(value),
            'note': row['note'],
        })
    steps = conn.execute(
        'SELECT * FROM recipe_steps WHERE version_id=? ORDER BY step_no,id',
        (version['id'],),
    ).fetchall()
    return target, dict(groups), steps


@router.get('/life', response_class=HTMLResponse)
def life_home_v12(request: Request):
    with db() as conn:
        ensure_v12_schema(conn)
        count = int(conn.execute(
            "SELECT COUNT(*) n FROM recipes WHERE archived=0 AND source='excel-template-v12'"
        ).fetchone()['n'])
        recent = conn.execute(
            "SELECT id,name,category FROM recipes WHERE archived=0 AND source='excel-template-v12' ORDER BY updated_at DESC,name LIMIT 8"
        ).fetchall()
    return templates.TemplateResponse(
        'life_home_v12.html', _ctx(request, recipe_count=count, recent=recent)
    )


@router.get('/life/recipes', response_class=HTMLResponse)
def recipe_list_v12(request: Request, q: str = '', category: str = ''):
    with db() as conn:
        ensure_v12_schema(conn)
        sql = "SELECT r.*,rv.version_no FROM recipes r LEFT JOIN recipe_versions rv ON rv.id=r.current_version_id WHERE r.archived=0 AND r.source='excel-template-v12'"
        args: list[Any] = []
        if q.strip():
            sql += ' AND r.name LIKE ?'
            args.append(f'%{q.strip()}%')
        if category.strip():
            sql += ' AND r.category=?'
            args.append(category.strip())
        sql += ' ORDER BY r.category,r.name'
        recipes = conn.execute(sql, args).fetchall()
        categories = [r['category'] for r in conn.execute(
            "SELECT DISTINCT category FROM recipes WHERE archived=0 AND source='excel-template-v12' AND category<>'' ORDER BY category"
        ).fetchall()]
    return templates.TemplateResponse('recipe_list_v12.html', _ctx(
        request, recipes=recipes, categories=categories, q=q, category=category
    ))


@router.get('/life/recipes/{recipe_id}', response_class=HTMLResponse)
def recipe_detail_v12(request: Request, recipe_id: int, amount: float | None = None):
    with db() as conn:
        ensure_v12_schema(conn)
        recipe = _recipe_or_404(conn, recipe_id)
        version = _current_version(conn, recipe)
        target, groups, steps = _recipe_payload(conn, version, amount)
        version_count = int(conn.execute(
            'SELECT COUNT(*) n FROM recipe_versions WHERE recipe_id=?', (recipe_id,)
        ).fetchone()['n'])
    return templates.TemplateResponse('recipe_detail_v12.html', _ctx(
        request,
        recipe=recipe,
        version=version,
        target_amount=target,
        ingredient_groups=groups,
        steps=steps,
        version_count=version_count,
    ))


@router.get('/life/recipes/{recipe_id}/print', response_class=HTMLResponse)
def recipe_print_v12(request: Request, recipe_id: int, amount: float | None = None):
    with db() as conn:
        ensure_v12_schema(conn)
        recipe = _recipe_or_404(conn, recipe_id)
        version = _current_version(conn, recipe)
        target, groups, steps = _recipe_payload(conn, version, amount)
    return templates.TemplateResponse('recipe_print_v12.html', _ctx(
        request,
        recipe=recipe,
        version=version,
        target_amount=target,
        ingredient_groups=groups,
        steps=steps,
    ))


@router.get('/life/tools', response_class=HTMLResponse)
def cooking_tools_v12(request: Request):
    return templates.TemplateResponse('cooking_tools_v12.html', _ctx(request))


@router.get('/life/knowledge')
def knowledge_redirect_v12():
    return RedirectResponse('/life/tools', status_code=302)


@router.get('/life/records')
def records_redirect_v12():
    return RedirectResponse('/life/recipes', status_code=302)

