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


def print_raw_weights(values, ingredients):
    """Validate this batch's individual weights and derive its gram total."""
    if not values:
        return {}, None
    rows = {str(row['id']): row for row in ingredients if row['group_name'] in {'原料', '主材'}}
    weights = {}
    factors = {'g': 1, '克': 1, 'kg': 1000, '千克': 1000, '公斤': 1000, '斤': 500, '两': 50}
    total = 0.0
    for entry in values:
        try:
            key, value = entry.split(':', 1)
            amount = float(value)
            row = rows[key]
            factor = factors[str(row['unit'] or 'g').strip().lower()]
        except (ValueError, TypeError, KeyError):
            raise HTTPException(400, '原料重量或单位无效')
        if key in weights or not math.isfinite(amount) or amount <= 0:
            raise HTTPException(400, '每种原料需要唯一且有效的正数重量')
        weights[key] = amount
        total += amount * factor
    if weights.keys() != rows.keys() or not math.isfinite(total) or total <= 0:
        raise HTTPException(400, '请填写全部原料的有效重量')
    return weights, total


def saved_raw_weights(conn, recipe_id, version, ingredients):
    import json
    row = conn.execute('SELECT value FROM app_meta WHERE key=?', (f'recipe-raw-weights:{recipe_id}',)).fetchone()
    if not row:
        return {}, None
    try:
        payload = json.loads(row['value'])
        if payload['version_id'] != version['id']:
            return {}, None
        if payload['raw']:
            return print_raw_weights(payload['raw'], ingredients)
        amount = float(payload['amount'])
        if math.isfinite(amount) and amount > 0:
            return {}, amount
    except (ValueError, KeyError, TypeError, HTTPException):
        pass
    return {}, None


def save_raw_weights(conn, recipe_id, version, ingredients, form):
    import json
    if str(form.get('version_id')) != str(version['id']):
        raise HTTPException(409, '标准配方已更新，请刷新后重新填写')
    values = form.getlist('raw')
    weights, total = print_raw_weights(values, ingredients)
    has_raw = any(row['group_name'] in {'主材', '原料'} for row in ingredients)
    if has_raw and not values:
        raise HTTPException(400, '请填写全部原料重量')
    if total is None:
        try:
            total = float(form.get('amount', ''))
        except (ValueError, TypeError):
            raise HTTPException(400, '原料重量无效')
        if not math.isfinite(total) or total <= 0:
            raise HTTPException(400, '原料重量必须为正数')
    try:
        revision = int(form.get('revision', ''))
    except (ValueError, TypeError):
        raise HTTPException(400, '保存标识无效')
    if revision <= 0 or revision > 9007199254740991:
        raise HTTPException(400, '保存标识无效')
    payload = json.dumps({'version_id': version['id'], 'raw': values, 'amount': total, 'revision': revision})
    # A slower earlier request must never overwrite the latest edit.
    conn.execute('''INSERT INTO app_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value
                    WHERE CAST(json_extract(app_meta.value,'$.revision') AS INTEGER) <= ?''',
                 (f'recipe-raw-weights:{recipe_id}', payload, revision))
    return total


def raw_weight_basis(version, ingredients):
    """Old imported recipes may store only the first raw's weight as their basis."""
    rows = [row for row in ingredients if row['group_name'] in {'原料', '主材'}]
    if rows:
        try:
            _, total = print_raw_weights([f"{row['id']}:{row['amount']}" for row in rows], rows)
            return dict(version) | {'base_amount': total, 'base_unit': 'g'}
        except HTTPException:
            pass
    return version
