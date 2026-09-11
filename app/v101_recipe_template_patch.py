from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import config
from .db import db, now_iso
from .v10_routes import _ctx, _current_version, _recipe_or_404, _scaled_amount, _version_payload, ensure_v10_schema
from .v101_recipe_template_data import TEMPLATE_CATEGORIES, TEMPLATE_IMPORT_MARKER, TEMPLATE_RECIPES

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')


def ensure_v101_recipe_templates(conn=None):
    """Import every worksheet matching the 糖醋排骨 standard template once.

    Existing user-created versions are never overwritten. If a recipe still only
    has its original v1.0 seed version, the imported Excel version becomes the
    current standard; otherwise it is appended to history without replacing the
    user's current standard.
    """
    owns = conn is None
    if owns:
        cm = db()
        conn = cm.__enter__()
    try:
        ensure_v10_schema(conn)
        now = now_iso()
        for name, payload in TEMPLATE_RECIPES.items():
            recipe = conn.execute('SELECT * FROM recipes WHERE name=?', (name,)).fetchone()
            if recipe is None:
                cur = conn.execute(
                    '''INSERT INTO recipes(name,category,tags,description,source,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?)''',
                    (name, TEMPLATE_CATEGORIES.get(name, '其他'), '', payload.get('description', ''), 'excel-template', now, now),
                )
                recipe_id = int(cur.lastrowid)
                version_count = 0
                current_id = None
            else:
                recipe_id = int(recipe['id'])
                version_count = int(conn.execute(
                    'SELECT COUNT(*) n FROM recipe_versions WHERE recipe_id=?', (recipe_id,)
                ).fetchone()['n'])
                current_id = recipe['current_version_id']
                if payload.get('description') and not recipe['description']:
                    conn.execute('UPDATE recipes SET description=?,updated_at=? WHERE id=?', (payload['description'], now, recipe_id))

            already = conn.execute(
                'SELECT id FROM recipe_versions WHERE recipe_id=? AND change_summary LIKE ? LIMIT 1',
                (recipe_id, f'{TEMPLATE_IMPORT_MARKER}%'),
            ).fetchone()
            if already:
                continue

            next_no = int(conn.execute(
                'SELECT COALESCE(MAX(version_no),0)+1 n FROM recipe_versions WHERE recipe_id=?', (recipe_id,)
            ).fetchone()['n'])
            summary = f'{TEMPLATE_IMPORT_MARKER} 从《菜谱.xlsm》Sheet“{name}”按糖醋排骨标准模板导入；步骤保留原始文本'
            vcur = conn.execute(
                '''INSERT INTO recipe_versions(recipe_id,version_no,base_amount,base_unit,change_summary,created_at)
                   VALUES(?,?,?,?,?,?)''',
                (recipe_id, next_no, payload['base_amount'], payload.get('base_unit', 'g'), summary, now),
            )
            version_id = int(vcur.lastrowid)

            for idx, item in enumerate(payload['ingredients'], 1):
                group_name, ing_name, amount, unit, scale_mode, note = item
                conn.execute(
                    '''INSERT INTO recipe_ingredients(version_id,group_name,name,amount,unit,scale_mode,note,sort_order)
                       VALUES(?,?,?,?,?,?,?,?)''',
                    (version_id, group_name or '其他', ing_name, amount, unit, scale_mode, note, idx * 10),
                )
            for item in payload['steps']:
                step_no, title, action, heat, duration, judgement, principle, risk = item
                conn.execute(
                    '''INSERT INTO recipe_steps(version_id,step_no,title,action,heat,duration,judgement,principle,risk)
                       VALUES(?,?,?,?,?,?,?,?,?)''',
                    (version_id, step_no, title, action, heat, duration, judgement, principle, risk),
                )

            # v1.0 seeded recipes only had one initial version. Those are safe to
            # upgrade automatically. If the user has already created versions,
            # preserve their current standard and only append the Excel import.
            if version_count <= 1 or current_id is None:
                conn.execute('UPDATE recipes SET current_version_id=?,updated_at=? WHERE id=?', (version_id, now, recipe_id))
    finally:
        if owns:
            cm.__exit__(None, None, None)


def _print_groups(conn, version):
    ingredients, steps, grouped = _version_payload(conn, version['id'])
    groups = []
    for group_name, rows in grouped.items():
        groups.append({
            'name': group_name,
            'items': [
                {
                    'name': row['name'],
                    'amount': _scaled_amount(row, version, float(version['base_amount'] or 0)),
                    'unit': row['unit'],
                    'note': row['note'],
                }
                for row in rows
            ],
        })
    return ingredients, steps, groups


@router.get('/life/recipes/{recipe_id}/print', response_class=HTMLResponse)
def recipe_print_v101(request: Request, recipe_id: int):
    with db() as conn:
        ensure_v101_recipe_templates(conn)
        recipe = _recipe_or_404(conn, recipe_id)
        version = _current_version(conn, recipe)
        ingredients, steps, groups = _print_groups(conn, version)
    char_count = sum(len(str(s['action'] or '')) + len(str(s['principle'] or '')) for s in steps)
    char_count += sum(len(str(i['name'] or '')) + len(str(i['note'] or '')) for i in ingredients)
    density = 'dense' if char_count > 1700 else ('compact' if char_count > 1050 else 'normal')
    return templates.TemplateResponse('recipe_print_v101.html', _ctx(
        request,
        recipe=recipe,
        version=version,
        ingredient_groups=groups,
        steps=steps,
        print_density=density,
    ))


@router.post('/life/recipes/{recipe_id}/cook/start')
def recipe_cook_start_disabled_v101(recipe_id: int):
    # The dedicated cooking-mode workflow was removed by design in v1.0.1.
    return RedirectResponse(f'/life/recipes/{recipe_id}', status_code=303)
