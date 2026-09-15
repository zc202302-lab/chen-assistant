from __future__ import annotations

import math

from fastapi import APIRouter, HTTPException, Request

from .db import db, now_iso
from . import v10_routes as v10
from . import v101_recipe_template_patch as v101


router = APIRouter()


def _safe_ensure_v10_schema(conn=None):
    """Transaction-safe replacement for the historical schema/seed helper.

    The original helper manually called a context manager's ``__enter__`` and then
    always called ``__exit__(None, None, None)``. If seeding raised halfway through,
    that pattern could commit partial seed data before the exception propagated.
    This implementation uses a real ``with`` block when it owns the connection, so
    app.db.db() can roll the transaction back on every exception.
    """
    if conn is None:
        with db() as owned:
            return ensure_v10_schema(owned)

    conn.executescript(V10_SCHEMA)
    for name, category, tags in RECIPE_CATALOG:
        _seed_recipe(conn, name, category, tags)
    now = now_iso()
    for category, title, content in KNOWLEDGE_SEED:
        conn.execute(
            '''INSERT OR IGNORE INTO cooking_knowledge(category,title,content,source,created_at,updated_at)
               VALUES(?,?,?,?,?,?)''',
            (category, title, content, 'excel-knowledge', now, now),
        )


def _safe_ensure_v101_recipe_templates(conn=None):
    """Transaction-safe replacement for the v1.0.1 Excel template importer."""
    if conn is None:
        with db() as owned:
            return ensure_v101_recipe_templates(owned)

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
                conn.execute(
                    'UPDATE recipes SET description=?,updated_at=? WHERE id=?',
                    (payload['description'], now, recipe_id),
                )

        already = conn.execute(
            'SELECT id FROM recipe_versions WHERE recipe_id=? AND change_summary LIKE ? LIMIT 1',
            (recipe_id, f'{TEMPLATE_IMPORT_MARKER}%'),
        ).fetchone()
        if already:
            continue

        next_no = int(conn.execute(
            'SELECT COALESCE(MAX(version_no),0)+1 n FROM recipe_versions WHERE recipe_id=?',
            (recipe_id,),
        ).fetchone()['n'])
        summary = (
            f'{TEMPLATE_IMPORT_MARKER} 从《菜谱.xlsm》Sheet“{name}”'
            '按糖醋排骨标准模板导入；步骤保留原始文本'
        )
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

        if version_count <= 1 or current_id is None:
            conn.execute(
                'UPDATE recipes SET current_version_id=?,updated_at=? WHERE id=?',
                (version_id, now, recipe_id),
            )


# main.py imported these function objects before v101_workspace_routes imports this
# module. Swap only their code objects so every already-imported reference (including
# main.py's startup callback) receives the transaction-safe implementation.
v10.ensure_v10_schema.__code__ = _safe_ensure_v10_schema.__code__
v10.ensure_v10_schema.__v144_transaction_safe__ = True
v101.ensure_v101_recipe_templates.__code__ = _safe_ensure_v101_recipe_templates.__code__
v101.ensure_v101_recipe_templates.__v144_transaction_safe__ = True


def _form_float(form, key: str, default: float = 0.0) -> float:
    raw = str(form.get(key, '')).strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise HTTPException(400, '数值格式不正确')
    if not math.isfinite(value):
        raise HTTPException(400, '数值必须是有限数字')
    return value


@router.post('/life/recipes/new')
async def recipe_new_validation_v144(request: Request):
    form = await request.form()
    v10._csrf(request, str(form.get('csrf', '')))
    base_amount = _form_float(form, 'base_amount', 500.0)
    if base_amount <= 0:
        raise HTTPException(400, '标准主材重量必须大于0')
    return await v10.recipe_new_v10(request)


@router.post('/life/recipes/{recipe_id}/edit')
async def recipe_edit_validation_v144(request: Request, recipe_id: int):
    form = await request.form()
    v10._csrf(request, str(form.get('csrf', '')))
    name = str(form.get('name', '')).strip()
    if not name:
        raise HTTPException(400, '菜名不能为空')
    base_amount = _form_float(form, 'base_amount', 0.0)
    if base_amount <= 0:
        raise HTTPException(400, '标准主材重量必须大于0')

    for raw in form.getlist('ingredient_amount'):
        text = str(raw).strip()
        if not text:
            continue
        try:
            amount = float(text)
        except (TypeError, ValueError):
            raise HTTPException(400, '配料用量必须是数字')
        if not math.isfinite(amount) or amount < 0:
            raise HTTPException(400, '配料用量必须是大于等于0的有限数字')

    with db() as conn:
        if not conn.execute('SELECT 1 FROM recipes WHERE id=? AND archived=0', (recipe_id,)).fetchone():
            raise HTTPException(404, '菜谱不存在')
        duplicate = conn.execute(
            'SELECT id FROM recipes WHERE name=? AND id<>? LIMIT 1',
            (name, recipe_id),
        ).fetchone()
        if duplicate:
            raise HTTPException(409, '同名菜谱已经存在')
    return await v10.recipe_edit_v10(request, recipe_id)


@router.post('/life/knowledge/new')
async def knowledge_new_validation_v144(request: Request):
    form = await request.form()
    v10._csrf(request, str(form.get('csrf', '')))
    title = str(form.get('title', '')).strip()
    if not title:
        raise HTTPException(400, '知识点标题不能为空')
    with db() as conn:
        if conn.execute('SELECT 1 FROM cooking_knowledge WHERE title=?', (title,)).fetchone():
            raise HTTPException(409, '同名知识点已经存在')
    return await v10.knowledge_new_v10(request)


@router.post('/life/knowledge/{item_id}/edit')
async def knowledge_edit_validation_v144(request: Request, item_id: int):
    form = await request.form()
    v10._csrf(request, str(form.get('csrf', '')))
    title = str(form.get('title', '')).strip()
    if not title:
        raise HTTPException(400, '知识点标题不能为空')
    with db() as conn:
        if not conn.execute('SELECT 1 FROM cooking_knowledge WHERE id=?', (item_id,)).fetchone():
            raise HTTPException(404, '知识点不存在')
        if conn.execute(
            'SELECT 1 FROM cooking_knowledge WHERE title=? AND id<>? LIMIT 1',
            (title, item_id),
        ).fetchone():
            raise HTTPException(409, '同名知识点已经存在')
    return await v10.knowledge_edit_v10(request, item_id)
