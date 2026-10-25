from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from .templating import Jinja2Templates

from . import config
from .db import connection_scope, db, now_iso
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
    with connection_scope(conn) as conn:
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


def _print_amount(row, version):
    amount = _scaled_amount(row, version, float(version['base_amount'] or 0))
    unit = str(row['unit'] or '')
    return f'{amount}{unit}' if amount else unit


def _print_step_method(step):
    parts = [str(step['action'] or '').strip()]
    for label, key in (('火候', 'heat'), ('时长', 'duration'), ('判断', 'judgement')):
        value = str(step[key] or '').strip()
        if value:
            parts.append(f'{label}：{value}')
    return '\n'.join(part for part in parts if part)


def _print_step_principle(step):
    parts = [str(step['principle'] or '').strip()]
    risk = str(step['risk'] or '').strip()
    if risk:
        parts.append(f'注意：{risk}')
    return '\n'.join(part for part in parts if part)


def _excel_print_layout(conn, version):
    ingredients, steps, grouped = _version_payload(conn, version['id'])
    ordered_groups = list(grouped.items())
    # An absent 主材 group must not promote the first cooking stage into the main row.
    main_index = next((idx for idx, (name, _) in enumerate(ordered_groups) if name in {'主材', '原料'}), None)
    main_name, main_rows = ordered_groups.pop(main_index) if main_index is not None else ('原料', [])

    main_slots = [''] * 9
    overflow_notes = []
    for idx, row in enumerate(main_rows):
        item_text = f"{row['name']} {_print_amount(row, version)}".strip()
        if idx < 4:
            main_slots[idx * 2] = str(row['name'] or '')
            main_slots[idx * 2 + 1] = _print_amount(row, version)
        elif item_text:
            main_slots[8] = '\n'.join(filter(None, [main_slots[8], item_text]))

    grid_groups = []
    for group_name, rows in ordered_groups:
        chunks = [rows[i:i + 9] for i in range(0, len(rows), 9)] or [[]]
        for chunk_index, chunk in enumerate(chunks):
            grid_groups.append({
                'name': group_name if chunk_index == 0 else f'{group_name}（续）',
                'items': [
                    {'name': str(row['name'] or ''), 'amount': _print_amount(row, version)}
                    for row in chunk
                ],
            })

    if len(grid_groups) > 4:
        for extra in grid_groups[4:]:
            values = [
                f"{item['name']} {item['amount']}".strip()
                for item in extra['items']
                if item['name'] or item['amount']
            ]
            if values:
                overflow_notes.append(f"{extra['name']}：{'，'.join(values)}")
        grid_groups = grid_groups[:4]

    while len(grid_groups) < 4:
        grid_groups.append({'name': '', 'items': []})
    for group in grid_groups:
        group['items'] = group['items'][:9] + [{'name': '', 'amount': ''}] * (9 - len(group['items']))

    ingredient_notes = []
    for row in ingredients:
        note = str(row['note'] or '').strip()
        if note:
            ingredient_notes.append(f"{row['name']}：{note}")
    ingredient_notes.extend(overflow_notes)

    print_steps = []
    for step in steps:
        item = {
            'title': str(step['title'] or ''),
            'method': _print_step_method(step),
            'principle': _print_step_principle(step),
        }
        if len(print_steps) < 4:
            print_steps.append(item)
        else:
            suffix = f"{step['step_no']}. {item['title']}\n{item['method']}".strip()
            if suffix:
                print_steps[-1]['method'] = '\n'.join(filter(None, [print_steps[-1]['method'], suffix]))
            if item['principle']:
                print_steps[-1]['principle'] = '\n'.join(filter(None, [print_steps[-1]['principle'], item['principle']]))

    while len(print_steps) < 4:
        print_steps.append({'title': '', 'method': '', 'principle': ''})

    return {
        'main_label': '原料',
        'main_slots': main_slots,
        'ingredient_groups': grid_groups,
        'ingredient_notes': '\n'.join(ingredient_notes),
        'print_steps': print_steps,
    }


@router.get('/life/recipes/{recipe_id}/print', response_class=HTMLResponse)
def recipe_print_v101(request: Request, recipe_id: int):
    with db() as conn:
        ensure_v101_recipe_templates(conn)
        recipe = _recipe_or_404(conn, recipe_id)
        version = _current_version(conn, recipe)
        layout = _excel_print_layout(conn, version)
    if request.query_params.get('format') == 'pdf':
        from urllib.parse import quote
        from .recipe_print_pdf import recipe_pdf
        filename = quote(str(recipe['name']) + '.pdf', safe='')
        return Response(recipe_pdf(recipe['name'], layout), media_type='application/pdf', headers={
            'Content-Disposition': f"attachment; filename=recipe.pdf; filename*=UTF-8''{filename}",
            'Cache-Control': 'no-store',
        })
    return templates.TemplateResponse('recipe_print_v101.html', _ctx(
        request,
        recipe=recipe,
        version=version,
        **layout,
    ))


@router.post('/life/recipes/{recipe_id}/cook/start')
def recipe_cook_start_disabled_v101(recipe_id: int):
    # The dedicated cooking-mode workflow was removed by design in v1.0.1.
    return RedirectResponse(f'/life/recipes/{recipe_id}', status_code=303)


# Compatibility marker; safety is implemented in this original function.
ensure_v101_recipe_templates.__v144_transaction_safe__ = True
