from __future__ import annotations

import math

from fastapi import APIRouter, HTTPException, Request

from .db import db
from . import v10_routes as v10
from . import v101_recipe_template_patch as v101


router = APIRouter()


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

