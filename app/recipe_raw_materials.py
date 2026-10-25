"""Weight basis for recipes with explicitly named raw material groups."""
import math
from fastapi import HTTPException


def raw_material_total(form, fallback):
    names = form.getlist('ingredient_name')
    groups = form.getlist('ingredient_group')
    amounts = form.getlist('ingredient_amount')
    units = form.getlist('ingredient_unit')
    total = 0.0
    found = False
    for i, name in enumerate(names):
        if not str(name).strip() or i >= len(groups) or str(groups[i]).strip() not in {'原料', '主材'}:
            continue
        found = True
        try:
            value = float(amounts[i])
        except (ValueError, TypeError, IndexError):
            raise HTTPException(400, '每种原料都需要填写重量')
        unit = str(units[i] if i < len(units) else 'g').strip().lower() or 'g'
        factors = {'g': 1, '克': 1, 'kg': 1000, '千克': 1000, '公斤': 1000, '斤': 500, '两': 50}
        if unit not in factors or not math.isfinite(value) or value <= 0:
            raise HTTPException(400, '原料重量必须为正数，单位使用g、kg、克、千克、公斤、斤或两')
        total += value * factors[unit]
    if not math.isfinite(total):
        raise HTTPException(400, '原料总重量过大')
    return (total, 'g') if found else (fallback, str(form.get('base_unit', 'g')).strip() or 'g')
