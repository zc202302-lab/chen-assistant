from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from .templating import Jinja2Templates

from . import config
from .db import execute_schema, connection_scope, db, now_iso
from .security import decrypt_secret, require_csrf
from .v160_information_center import ensure_v160_schema
from .v10_seed import KNOWLEDGE_SEED, RECIPE_CATALOG, STRUCTURED_RECIPES

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')

V10_SCHEMA = r'''
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    current_version_id INTEGER DEFAULT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recipe_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    version_no INTEGER NOT NULL,
    base_amount REAL NOT NULL DEFAULT 0,
    base_unit TEXT NOT NULL DEFAULT 'g',
    change_summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(recipe_id, version_no)
);

CREATE TABLE IF NOT EXISTS recipe_ingredients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER NOT NULL REFERENCES recipe_versions(id) ON DELETE CASCADE,
    group_name TEXT NOT NULL DEFAULT '配料',
    name TEXT NOT NULL,
    amount REAL DEFAULT NULL,
    unit TEXT NOT NULL DEFAULT 'g',
    scale_mode TEXT NOT NULL DEFAULT 'proportional',
    note TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS recipe_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER NOT NULL REFERENCES recipe_versions(id) ON DELETE CASCADE,
    step_no INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL DEFAULT '',
    heat TEXT NOT NULL DEFAULT '',
    duration TEXT NOT NULL DEFAULT '',
    judgement TEXT NOT NULL DEFAULT '',
    principle TEXT NOT NULL DEFAULT '',
    risk TEXT NOT NULL DEFAULT '',
    UNIQUE(version_id, step_no)
);

CREATE TABLE IF NOT EXISTS cook_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    version_id INTEGER NOT NULL REFERENCES recipe_versions(id),
    started_at TEXT NOT NULL,
    cooked_at TEXT NOT NULL DEFAULT '',
    base_amount REAL NOT NULL DEFAULT 0,
    current_step INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active',
    rating INTEGER DEFAULT NULL,
    taste TEXT NOT NULL DEFAULT '',
    texture TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    next_change TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cook_adjustments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES cook_sessions(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL DEFAULT 'ingredient',
    item_ref INTEGER DEFAULT NULL,
    label TEXT NOT NULL DEFAULT '',
    standard_value TEXT NOT NULL DEFAULT '',
    actual_value TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cooking_knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_recipe_versions_recipe ON recipe_versions(recipe_id, version_no DESC);
CREATE INDEX IF NOT EXISTS idx_recipe_ingredients_version ON recipe_ingredients(version_id, sort_order, id);
CREATE INDEX IF NOT EXISTS idx_recipe_steps_version ON recipe_steps(version_id, step_no);
CREATE INDEX IF NOT EXISTS idx_cook_sessions_recipe ON cook_sessions(recipe_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_cook_adjustments_session ON cook_adjustments(session_id, id);
CREATE INDEX IF NOT EXISTS idx_cooking_knowledge_category ON cooking_knowledge(category, title);
'''


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


def _csrf(request: Request, value: str):
    try:
        require_csrf(request.state.session, value)
    except ValueError:
        raise HTTPException(403, 'CSRF校验失败')


def _seed_recipe(conn, name: str, category: str, tags: str):
    now = now_iso()
    row = conn.execute('SELECT id,current_version_id FROM recipes WHERE name=?', (name,)).fetchone()
    if row:
        return int(row['id'])
    cur = conn.execute(
        '''INSERT INTO recipes(name,category,tags,description,source,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?)''',
        (name, category, tags, '', 'excel-catalog', now, now),
    )
    recipe_id = int(cur.lastrowid)
    structured = STRUCTURED_RECIPES.get(name)
    base_amount = float(structured['base_amount']) if structured else 500.0
    base_unit = str(structured['base_unit']) if structured else 'g'
    summary = structured['change_summary'] if structured else '从现有 Excel 菜谱目录导入，待继续结构化完善'
    vcur = conn.execute(
        '''INSERT INTO recipe_versions(recipe_id,version_no,base_amount,base_unit,change_summary,created_at)
           VALUES(?,?,?,?,?,?)''',
        (recipe_id, 1, base_amount, base_unit, summary, now),
    )
    version_id = int(vcur.lastrowid)
    if structured:
        for idx, item in enumerate(structured['ingredients'], 1):
            group_name, ing_name, amount, unit, scale_mode, note = item
            conn.execute(
                '''INSERT INTO recipe_ingredients(version_id,group_name,name,amount,unit,scale_mode,note,sort_order)
                   VALUES(?,?,?,?,?,?,?,?)''',
                (version_id, group_name, ing_name, amount, unit, scale_mode, note, idx * 10),
            )
        for item in structured['steps']:
            step_no, title, action, heat, duration, judgement, principle, risk = item
            conn.execute(
                '''INSERT INTO recipe_steps(version_id,step_no,title,action,heat,duration,judgement,principle,risk)
                   VALUES(?,?,?,?,?,?,?,?,?)''',
                (version_id, step_no, title, action, heat, duration, judgement, principle, risk),
            )
    conn.execute('UPDATE recipes SET current_version_id=? WHERE id=?', (version_id, recipe_id))
    return recipe_id


def ensure_v10_schema(conn=None):
    with connection_scope(conn) as conn:
        execute_schema(conn, V10_SCHEMA)
        for name, category, tags in RECIPE_CATALOG:
            _seed_recipe(conn, name, category, tags)
        now = now_iso()
        for category, title, content in KNOWLEDGE_SEED:
            conn.execute(
                '''INSERT OR IGNORE INTO cooking_knowledge(category,title,content,source,created_at,updated_at)
                   VALUES(?,?,?,?,?,?)''',
                (category, title, content, 'excel-knowledge', now, now),
            )


def _recipe_or_404(conn, recipe_id: int):
    row = conn.execute('SELECT * FROM recipes WHERE id=? AND archived=0', (recipe_id,)).fetchone()
    if not row:
        raise HTTPException(404, '菜谱不存在')
    return row


def _version_or_404(conn, version_id: int):
    row = conn.execute('SELECT * FROM recipe_versions WHERE id=?', (version_id,)).fetchone()
    if not row:
        raise HTTPException(404, '菜谱版本不存在')
    return row


def _current_version(conn, recipe):
    version_id = recipe['current_version_id']
    if version_id:
        row = conn.execute('SELECT * FROM recipe_versions WHERE id=?', (version_id,)).fetchone()
        if row:
            return row
    row = conn.execute(
        'SELECT * FROM recipe_versions WHERE recipe_id=? ORDER BY version_no DESC LIMIT 1',
        (recipe['id'],),
    ).fetchone()
    if not row:
        raise HTTPException(409, '菜谱还没有标准版本')
    return row


def _version_payload(conn, version_id: int):
    ingredients = conn.execute(
        'SELECT * FROM recipe_ingredients WHERE version_id=? ORDER BY sort_order,id',
        (version_id,),
    ).fetchall()
    steps = conn.execute(
        'SELECT * FROM recipe_steps WHERE version_id=? ORDER BY step_no,id',
        (version_id,),
    ).fetchall()
    grouped: dict[str, list[Any]] = defaultdict(list)
    for row in ingredients:
        grouped[row['group_name'] or '配料'].append(row)
    return ingredients, steps, dict(grouped)


def _display_number(value: float | None) -> str:
    if value is None:
        return ''
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f'{value:.2f}'.rstrip('0').rstrip('.')


def _scaled_amount(ingredient, version, target_amount: float) -> str:
    amount = ingredient['amount']
    if amount is None:
        return ''
    if ingredient['scale_mode'] == 'proportional' and float(version['base_amount'] or 0) > 0:
        amount = float(amount) * target_amount / float(version['base_amount'])
    return _display_number(float(amount))


def _clone_version(conn, recipe_id: int, source_version_id: int, summary: str):
    source = _version_or_404(conn, source_version_id)
    next_no = int(conn.execute(
        'SELECT COALESCE(MAX(version_no),0)+1 n FROM recipe_versions WHERE recipe_id=?',
        (recipe_id,),
    ).fetchone()['n'])
    now = now_iso()
    cur = conn.execute(
        '''INSERT INTO recipe_versions(recipe_id,version_no,base_amount,base_unit,change_summary,created_at)
           VALUES(?,?,?,?,?,?)''',
        (recipe_id, next_no, source['base_amount'], source['base_unit'], summary, now),
    )
    new_id = int(cur.lastrowid)
    rows = conn.execute(
        'SELECT group_name,name,amount,unit,scale_mode,note,sort_order FROM recipe_ingredients WHERE version_id=? ORDER BY sort_order,id',
        (source_version_id,),
    ).fetchall()
    for row in rows:
        conn.execute(
            '''INSERT INTO recipe_ingredients(version_id,group_name,name,amount,unit,scale_mode,note,sort_order)
               VALUES(?,?,?,?,?,?,?,?)''',
            (new_id, row['group_name'], row['name'], row['amount'], row['unit'], row['scale_mode'], row['note'], row['sort_order']),
        )
    steps = conn.execute(
        'SELECT step_no,title,action,heat,duration,judgement,principle,risk FROM recipe_steps WHERE version_id=? ORDER BY step_no',
        (source_version_id,),
    ).fetchall()
    for row in steps:
        conn.execute(
            '''INSERT INTO recipe_steps(version_id,step_no,title,action,heat,duration,judgement,principle,risk)
               VALUES(?,?,?,?,?,?,?,?,?)''',
            (new_id, row['step_no'], row['title'], row['action'], row['heat'], row['duration'], row['judgement'], row['principle'], row['risk']),
        )
    conn.execute('UPDATE recipes SET current_version_id=?,updated_at=? WHERE id=?', (new_id, now, recipe_id))
    return new_id, next_no


def _home_work_summary(conn):
    today = date.today().isoformat()
    tasks = conn.execute(
        '''SELECT t.id,t.title,t.remind_date,c.id customer_id,c.name customer_name
           FROM tasks t LEFT JOIN customers c ON c.id=t.customer_id
           WHERE t.done=0 AND (t.remind_date='' OR t.remind_date<=?)
           ORDER BY CASE WHEN t.remind_date='' THEN 1 ELSE 0 END,t.remind_date,t.id DESC LIMIT 6''',
        (today,),
    ).fetchall()
    recent = conn.execute(
        'SELECT id,name,group_code FROM customers ORDER BY updated_at DESC LIMIT 5'
    ).fetchall()
    customer_count = int(conn.execute('SELECT COUNT(*) n FROM customers').fetchone()['n'])
    open_tasks = int(conn.execute('SELECT COUNT(*) n FROM tasks WHERE done=0').fetchone()['n'])
    return tasks, recent, customer_count, open_tasks


@router.get('/', response_class=HTMLResponse)
def home_v10(request: Request):
    with db() as conn:
        ensure_v10_schema(conn)
        tasks, customers, customer_count, open_tasks = _home_work_summary(conn)
        recipe_count = int(conn.execute('SELECT COUNT(*) n FROM recipes WHERE archived=0').fetchone()['n'])
        recent_recipes = conn.execute(
            '''SELECT r.id,r.name,r.category,rv.version_no,
                      (SELECT MAX(COALESCE(cs.cooked_at,cs.started_at)) FROM cook_sessions cs WHERE cs.recipe_id=r.id) last_cooked
               FROM recipes r LEFT JOIN recipe_versions rv ON rv.id=r.current_version_id
               WHERE r.archived=0
               ORDER BY COALESCE(last_cooked,r.updated_at) DESC,r.name LIMIT 5'''
        ).fetchall()
        last_records = conn.execute(
            '''SELECT cs.id,cs.cooked_at,cs.rating,r.name recipe_name,r.id recipe_id
               FROM cook_sessions cs JOIN recipes r ON r.id=cs.recipe_id
               WHERE cs.status='completed' ORDER BY cs.cooked_at DESC,cs.id DESC LIMIT 3'''
        ).fetchall()
    return templates.TemplateResponse('home_v10.html', _ctx(
        request,
        tasks=tasks,
        recent_customers=customers,
        customer_count=customer_count,
        open_tasks=open_tasks,
        recipe_count=recipe_count,
        recent_recipes=recent_recipes,
        last_records=last_records,
    ))


@router.get('/work', response_class=HTMLResponse)
def work_home_v10(request: Request):
    with db() as conn:
        ensure_v10_schema(conn)
        tasks, customers, customer_count, open_tasks = _home_work_summary(conn)
        product_count = int(conn.execute("SELECT COUNT(DISTINCT service_type) n FROM services WHERE service_type<>''").fetchone()['n'])
        account_count = int(conn.execute('SELECT COUNT(*) n FROM website_accounts').fetchone()['n'])
    return templates.TemplateResponse('work_home_v10.html', _ctx(
        request,
        tasks=tasks,
        recent_customers=customers,
        customer_count=customer_count,
        open_tasks=open_tasks,
        product_count=product_count,
        account_count=account_count,
    ))


@router.get('/life', response_class=HTMLResponse)
def life_home_v10(request: Request):
    with db() as conn:
        ensure_v10_schema(conn)
        recipe_count = int(conn.execute('SELECT COUNT(*) n FROM recipes WHERE archived=0').fetchone()['n'])
        knowledge_count = int(conn.execute('SELECT COUNT(*) n FROM cooking_knowledge').fetchone()['n'])
        record_count = int(conn.execute("SELECT COUNT(*) n FROM cook_sessions WHERE status='completed'").fetchone()['n'])
        recent = conn.execute(
            '''SELECT r.id,r.name,r.category,rv.version_no,
                      (SELECT MAX(COALESCE(cs.cooked_at,cs.started_at)) FROM cook_sessions cs WHERE cs.recipe_id=r.id) last_cooked
               FROM recipes r LEFT JOIN recipe_versions rv ON rv.id=r.current_version_id
               WHERE r.archived=0 ORDER BY COALESCE(last_cooked,r.updated_at) DESC LIMIT 6'''
        ).fetchall()
    return templates.TemplateResponse('life_home_v10.html', _ctx(
        request,
        recipe_count=recipe_count,
        knowledge_count=knowledge_count,
        record_count=record_count,
        recent_recipes=recent,
    ))


@router.get('/search', response_class=HTMLResponse)
def global_search_v10(request: Request, q: str = ''):
    q = q.strip()
    customers = accounts = information = recipes = knowledge = []
    if q:
        like = f'%{q}%'
        with db() as conn:
            ensure_v10_schema(conn)
            customers = conn.execute(
                '''SELECT DISTINCT c.id,c.name,c.group_code,c.tax_id FROM customers c
                   LEFT JOIN services s ON s.customer_id=c.id LEFT JOIN contacts k ON k.customer_id=c.id
                   WHERE c.name LIKE ? OR c.group_code LIKE ? OR c.tax_id LIKE ? OR s.number LIKE ? OR s.account LIKE ? OR s.holder_name LIKE ? OR k.name LIKE ?
                   ORDER BY c.name LIMIT 30''',
                (like, like, like, like, like, like, like),
            ).fetchall()
            accounts = conn.execute(
                '''SELECT id,platform,url,username,email,tags FROM website_accounts
                   WHERE platform LIKE ? OR url LIKE ? OR username LIKE ? OR email LIKE ? OR tags LIKE ?
                   ORDER BY platform LIMIT 20''',
                (like, like, like, like, like),
            ).fetchall()
            ensure_v160_schema(conn)
            info_rows = conn.execute(
                '''SELECT id,title,category,tags,body_enc,link_url
                   FROM information_records WHERE archived=0
                   ORDER BY pinned DESC,updated_at DESC,id DESC'''
            ).fetchall()
            q_lower = q.casefold()
            for row in info_rows:
                try:
                    body = decrypt_secret(row['body_enc'] or '')
                except Exception:
                    body = ''
                haystack = '\\n'.join([
                    row['title'] or '', row['category'] or '', row['tags'] or '',
                    body, row['link_url'] or '',
                ]).casefold()
                if q_lower in haystack:
                    information.append(dict(row))
                if len(information) >= 30:
                    break
            recipes = conn.execute(
                '''SELECT r.id,r.name,r.category,r.tags,rv.version_no FROM recipes r
                   LEFT JOIN recipe_versions rv ON rv.id=r.current_version_id
                   WHERE r.archived=0 AND (r.name LIKE ? OR r.category LIKE ? OR r.tags LIKE ? OR r.description LIKE ?)
                   ORDER BY r.name LIMIT 30''',
                (like, like, like, like),
            ).fetchall()
            knowledge = conn.execute(
                '''SELECT id,category,title,content FROM cooking_knowledge
                   WHERE title LIKE ? OR category LIKE ? OR content LIKE ? ORDER BY category,title LIMIT 30''',
                (like, like, like),
            ).fetchall()
    return templates.TemplateResponse('search_v10.html', _ctx(
        request, q=q, customers=customers, accounts=accounts, information=information, recipes=recipes, knowledge=knowledge
    ))


@router.get('/life/recipes', response_class=HTMLResponse)
def recipe_list_v10(request: Request, q: str = '', category: str = ''):
    with db() as conn:
        ensure_v10_schema(conn)
        where = ['r.archived=0']
        params: list[Any] = []
        if q.strip():
            like = f'%{q.strip()}%'
            where.append('(r.name LIKE ? OR r.tags LIKE ? OR r.description LIKE ?)')
            params.extend([like, like, like])
        if category.strip():
            where.append('r.category=?')
            params.append(category.strip())
        rows = conn.execute(
            f'''SELECT r.*,rv.version_no,rv.base_amount,rv.base_unit,
                       (SELECT COUNT(*) FROM cook_sessions cs WHERE cs.recipe_id=r.id AND cs.status='completed') cook_count,
                       (SELECT MAX(COALESCE(cs.cooked_at,cs.started_at)) FROM cook_sessions cs WHERE cs.recipe_id=r.id AND cs.status='completed') last_cooked,
                       (SELECT ROUND(AVG(cs.rating),1) FROM cook_sessions cs WHERE cs.recipe_id=r.id AND cs.status='completed' AND cs.rating IS NOT NULL) avg_rating
                FROM recipes r LEFT JOIN recipe_versions rv ON rv.id=r.current_version_id
                WHERE {' AND '.join(where)}
                ORDER BY CASE WHEN last_cooked IS NULL THEN 1 ELSE 0 END,last_cooked DESC,r.name''',
            params,
        ).fetchall()
        categories = [r['category'] for r in conn.execute(
            "SELECT DISTINCT category FROM recipes WHERE archived=0 AND category<>'' ORDER BY category"
        ).fetchall()]
    return templates.TemplateResponse('recipe_list_v10.html', _ctx(
        request, recipes=rows, categories=categories, q=q, category=category
    ))


@router.get('/life/recipes/new', response_class=HTMLResponse)
def recipe_new_page_v10(request: Request):
    return templates.TemplateResponse('recipe_new_v10.html', _ctx(request))


@router.post('/life/recipes/new')
async def recipe_new_v10(request: Request):
    form = await request.form()
    _csrf(request, str(form.get('csrf', '')))
    name = str(form.get('name', '')).strip()
    if not name:
        raise HTTPException(400, '菜名不能为空')
    category = str(form.get('category', '')).strip()
    tags = str(form.get('tags', '')).strip()
    description = str(form.get('description', '')).strip()
    base_unit = str(form.get('base_unit', 'g')).strip() or 'g'
    try:
        base_amount = float(form.get('base_amount', 500) or 500)
    except Exception:
        raise HTTPException(400, '标准主材重量必须是数字')
    now = now_iso()
    with db() as conn:
        ensure_v10_schema(conn)
        if conn.execute('SELECT 1 FROM recipes WHERE name=?', (name,)).fetchone():
            raise HTTPException(409, '同名菜谱已经存在')
        cur = conn.execute(
            '''INSERT INTO recipes(name,category,tags,description,source,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?)''',
            (name, category, tags, description, 'manual', now, now),
        )
        recipe_id = int(cur.lastrowid)
        vcur = conn.execute(
            '''INSERT INTO recipe_versions(recipe_id,version_no,base_amount,base_unit,change_summary,created_at)
               VALUES(?,?,?,?,?,?)''',
            (recipe_id, 1, base_amount, base_unit, '创建初始标准配方', now),
        )
        conn.execute('UPDATE recipes SET current_version_id=? WHERE id=?', (int(vcur.lastrowid), recipe_id))
    return RedirectResponse(f'/life/recipes/{recipe_id}/edit', status_code=303)


@router.get('/life/recipes/{recipe_id}', response_class=HTMLResponse)
def recipe_detail_v10(request: Request, recipe_id: int, amount: float | None = None):
    with db() as conn:
        ensure_v10_schema(conn)
        recipe = _recipe_or_404(conn, recipe_id)
        version = _current_version(conn, recipe)
        ingredients, steps, grouped = _version_payload(conn, version['id'])
        target = float(amount) if amount and amount > 0 else float(version['base_amount'] or 0)
        display_groups = []
        for group_name, rows in grouped.items():
            display_groups.append({
                'name': '原料' if group_name == '主材' else group_name,
                'items': [dict(row) | {'scaled_amount': _scaled_amount(row, version, target)} for row in rows],
            })
        cook_stats = conn.execute(
            '''SELECT COUNT(*) n,ROUND(AVG(rating),1) avg_rating,MAX(cooked_at) last_cooked
               FROM cook_sessions WHERE recipe_id=? AND status='completed' ''',
            (recipe_id,),
        ).fetchone()
        recent_records = conn.execute(
            '''SELECT id,cooked_at,rating,base_amount,notes FROM cook_sessions
               WHERE recipe_id=? AND status='completed' ORDER BY cooked_at DESC,id DESC LIMIT 5''',
            (recipe_id,),
        ).fetchall()
    return templates.TemplateResponse('recipe_detail_v10.html', _ctx(
        request,
        recipe=recipe,
        version=version,
        ingredient_groups=display_groups,
        ingredients=ingredients,
        steps=steps,
        target_amount=target,
        cook_stats=cook_stats,
        recent_records=recent_records,
    ))


@router.get('/life/recipes/{recipe_id}/edit', response_class=HTMLResponse)
def recipe_edit_page_v10(request: Request, recipe_id: int):
    with db() as conn:
        ensure_v10_schema(conn)
        recipe = _recipe_or_404(conn, recipe_id)
        version = _current_version(conn, recipe)
        ingredients, steps, _ = _version_payload(conn, version['id'])
    return templates.TemplateResponse('recipe_edit_v10.html', _ctx(
        request, recipe=recipe, version=version, ingredients=ingredients, steps=steps
    ))


@router.post('/life/recipes/{recipe_id}/edit')
async def recipe_edit_v10(request: Request, recipe_id: int):
    form = await request.form()
    _csrf(request, str(form.get('csrf', '')))
    name = str(form.get('name', '')).strip()
    if not name:
        raise HTTPException(400, '菜名不能为空')
    category = str(form.get('category', '')).strip()
    tags = str(form.get('tags', '')).strip()
    description = str(form.get('description', '')).strip()
    summary = str(form.get('change_summary', '')).strip() or '更新标准配方'
    base_unit = str(form.get('base_unit', 'g')).strip() or 'g'
    try:
        base_amount = float(form.get('base_amount', 0) or 0)
    except Exception:
        raise HTTPException(400, '标准主材重量必须是数字')
    if base_amount <= 0:
        raise HTTPException(400, '标准主材重量必须大于0')

    from .recipe_raw_materials import raw_material_total
    base_amount, base_unit = raw_material_total(form, base_amount)

    groups = list(form.getlist('ingredient_group'))
    ing_names = list(form.getlist('ingredient_name'))
    amounts = list(form.getlist('ingredient_amount'))
    units = list(form.getlist('ingredient_unit'))
    modes = list(form.getlist('ingredient_mode'))
    notes = list(form.getlist('ingredient_note'))

    step_titles = list(form.getlist('step_title'))
    actions = list(form.getlist('step_action'))
    heats = list(form.getlist('step_heat'))
    durations = list(form.getlist('step_duration'))
    judgements = list(form.getlist('step_judgement'))
    principles = list(form.getlist('step_principle'))
    risks = list(form.getlist('step_risk'))

    now = now_iso()
    with db() as conn:
        ensure_v10_schema(conn)
        _recipe_or_404(conn, recipe_id)
        next_no = int(conn.execute(
            'SELECT COALESCE(MAX(version_no),0)+1 n FROM recipe_versions WHERE recipe_id=?',
            (recipe_id,),
        ).fetchone()['n'])
        conn.execute(
            'UPDATE recipes SET name=?,category=?,tags=?,description=?,updated_at=? WHERE id=?',
            (name, category, tags, description, now, recipe_id),
        )
        cur = conn.execute(
            '''INSERT INTO recipe_versions(recipe_id,version_no,base_amount,base_unit,change_summary,created_at)
               VALUES(?,?,?,?,?,?)''',
            (recipe_id, next_no, base_amount, base_unit, summary, now),
        )
        version_id = int(cur.lastrowid)
        for idx, ing_name in enumerate(ing_names):
            ing_name = str(ing_name).strip()
            if not ing_name:
                continue
            raw_amount = str(amounts[idx] if idx < len(amounts) else '').strip()
            try:
                amount_value = float(raw_amount) if raw_amount else None
            except Exception:
                raise HTTPException(400, f'配料“{ing_name}”的用量必须是数字')
            mode = str(modes[idx] if idx < len(modes) else 'proportional').strip()
            if mode not in {'proportional', 'fixed', 'manual'}:
                mode = 'proportional'
            conn.execute(
                '''INSERT INTO recipe_ingredients(version_id,group_name,name,amount,unit,scale_mode,note,sort_order)
                   VALUES(?,?,?,?,?,?,?,?)''',
                (
                    version_id,
                    str(groups[idx] if idx < len(groups) else '配料').strip() or '配料',
                    ing_name,
                    amount_value,
                    str(units[idx] if idx < len(units) else 'g').strip(),
                    mode,
                    str(notes[idx] if idx < len(notes) else '').strip(),
                    (idx + 1) * 10,
                ),
            )
        for idx, title in enumerate(step_titles):
            title = str(title).strip()
            action = str(actions[idx] if idx < len(actions) else '').strip()
            if not title and not action:
                continue
            conn.execute(
                '''INSERT INTO recipe_steps(version_id,step_no,title,action,heat,duration,judgement,principle,risk)
                   VALUES(?,?,?,?,?,?,?,?,?)''',
                (
                    version_id,
                    idx + 1,
                    title or f'步骤{idx + 1}',
                    action,
                    str(heats[idx] if idx < len(heats) else '').strip(),
                    str(durations[idx] if idx < len(durations) else '').strip(),
                    str(judgements[idx] if idx < len(judgements) else '').strip(),
                    str(principles[idx] if idx < len(principles) else '').strip(),
                    str(risks[idx] if idx < len(risks) else '').strip(),
                ),
            )
        conn.execute('UPDATE recipes SET current_version_id=? WHERE id=?', (version_id, recipe_id))
    return RedirectResponse(f'/life/recipes/{recipe_id}', status_code=303)


@router.get('/life/recipes/{recipe_id}/versions', response_class=HTMLResponse)
def recipe_versions_v10(request: Request, recipe_id: int):
    return RedirectResponse(f'/life/recipes/{recipe_id}', status_code=303)


@router.post('/life/recipes/{recipe_id}/versions/{version_id}/restore')
async def recipe_restore_v10(request: Request, recipe_id: int, version_id: int):
    form = await request.form()
    _csrf(request, str(form.get('csrf', '')))
    raise HTTPException(410, '菜谱历史恢复功能已移除')


@router.post('/life/recipes/{recipe_id}/cook/start')
async def cook_start_v10(request: Request, recipe_id: int):
    form = await request.form()
    _csrf(request, str(form.get('csrf', '')))
    try:
        base_amount = float(form.get('base_amount', 0) or 0)
    except Exception:
        raise HTTPException(400, '本次主材重量必须是数字')
    with db() as conn:
        ensure_v10_schema(conn)
        recipe = _recipe_or_404(conn, recipe_id)
        version = _current_version(conn, recipe)
        if base_amount <= 0:
            base_amount = float(version['base_amount'] or 0)
        step_count = int(conn.execute('SELECT COUNT(*) n FROM recipe_steps WHERE version_id=?', (version['id'],)).fetchone()['n'])
        if step_count == 0:
            raise HTTPException(409, '当前标准还没有烹饪步骤，请先编辑菜谱')
        now = now_iso()
        cur = conn.execute(
            '''INSERT INTO cook_sessions(recipe_id,version_id,started_at,base_amount,current_step,status,created_at,updated_at)
               VALUES(?,?,?,?,1,'active',?,?)''',
            (recipe_id, version['id'], now, base_amount, now, now),
        )
        session_id = int(cur.lastrowid)
    return RedirectResponse(f'/life/cook/{session_id}', status_code=303)


@router.get('/life/cook/{session_id}', response_class=HTMLResponse)
def cook_mode_v10(request: Request, session_id: int):
    with db() as conn:
        ensure_v10_schema(conn)
        session = conn.execute('SELECT * FROM cook_sessions WHERE id=?', (session_id,)).fetchone()
        if not session:
            raise HTTPException(404, '烹饪记录不存在')
        recipe = _recipe_or_404(conn, int(session['recipe_id']))
        version = _version_or_404(conn, int(session['version_id']))
        ingredients, steps, _ = _version_payload(conn, version['id'])
        target = float(session['base_amount'] or version['base_amount'] or 0)
        scaled_ingredients = [dict(row) | {'scaled_amount': _scaled_amount(row, version, target)} for row in ingredients]
        current_step_no = max(1, min(int(session['current_step'] or 1), max(len(steps), 1)))
        current_step = steps[current_step_no - 1] if steps else None
        adjustments = conn.execute(
            'SELECT * FROM cook_adjustments WHERE session_id=? ORDER BY id DESC', (session_id,)
        ).fetchall()
    return templates.TemplateResponse('cook_mode_v10.html', _ctx(
        request,
        session=session,
        recipe=recipe,
        version=version,
        ingredients=scaled_ingredients,
        steps=steps,
        current_step=current_step,
        current_step_no=current_step_no,
        step_count=len(steps),
        adjustments=adjustments,
    ))


@router.post('/life/cook/{session_id}/step')
async def cook_step_v10(request: Request, session_id: int):
    form = await request.form()
    _csrf(request, str(form.get('csrf', '')))
    action = str(form.get('action', 'next'))
    with db() as conn:
        ensure_v10_schema(conn)
        session = conn.execute('SELECT * FROM cook_sessions WHERE id=?', (session_id,)).fetchone()
        if not session:
            raise HTTPException(404)
        count = int(conn.execute('SELECT COUNT(*) n FROM recipe_steps WHERE version_id=?', (session['version_id'],)).fetchone()['n'])
        current = int(session['current_step'] or 1)
        if action == 'prev':
            current = max(1, current - 1)
        else:
            if current >= count:
                return RedirectResponse(f'/life/cook/{session_id}/complete', status_code=303)
            current = min(count, current + 1)
        conn.execute('UPDATE cook_sessions SET current_step=?,updated_at=? WHERE id=?', (current, now_iso(), session_id))
    return RedirectResponse(f'/life/cook/{session_id}', status_code=303)


@router.post('/life/cook/{session_id}/adjustments')
async def cook_adjustment_v10(request: Request, session_id: int):
    form = await request.form()
    _csrf(request, str(form.get('csrf', '')))
    item_ref_raw = str(form.get('ingredient_id', '')).strip()
    actual_value = str(form.get('actual_value', '')).strip()
    note = str(form.get('note', '')).strip()
    if not item_ref_raw or not actual_value:
        return RedirectResponse(f'/life/cook/{session_id}#adjustment', status_code=303)
    try:
        item_ref = int(item_ref_raw)
    except Exception:
        raise HTTPException(400, '配料选择无效')
    with db() as conn:
        ensure_v10_schema(conn)
        session = conn.execute('SELECT * FROM cook_sessions WHERE id=?', (session_id,)).fetchone()
        if not session:
            raise HTTPException(404)
        version = _version_or_404(conn, int(session['version_id']))
        ingredient = conn.execute(
            'SELECT * FROM recipe_ingredients WHERE id=? AND version_id=?',
            (item_ref, version['id']),
        ).fetchone()
        if not ingredient:
            raise HTTPException(400, '配料不属于本次菜谱版本')
        standard = _scaled_amount(ingredient, version, float(session['base_amount']))
        conn.execute(
            '''INSERT INTO cook_adjustments(session_id,item_type,item_ref,label,standard_value,actual_value,unit,note,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)''',
            (session_id, 'ingredient', item_ref, ingredient['name'], standard, actual_value, ingredient['unit'], note, now_iso()),
        )
    return RedirectResponse(f'/life/cook/{session_id}#adjustment', status_code=303)


@router.get('/life/cook/{session_id}/complete', response_class=HTMLResponse)
def cook_complete_page_v10(request: Request, session_id: int):
    with db() as conn:
        ensure_v10_schema(conn)
        session = conn.execute('SELECT * FROM cook_sessions WHERE id=?', (session_id,)).fetchone()
        if not session:
            raise HTTPException(404)
        recipe = _recipe_or_404(conn, int(session['recipe_id']))
        adjustments = conn.execute('SELECT * FROM cook_adjustments WHERE session_id=? ORDER BY id', (session_id,)).fetchall()
    return templates.TemplateResponse('cook_complete_v10.html', _ctx(
        request, session=session, recipe=recipe, adjustments=adjustments
    ))


@router.post('/life/cook/{session_id}/complete')
async def cook_complete_v10(request: Request, session_id: int):
    form = await request.form()
    _csrf(request, str(form.get('csrf', '')))
    rating_raw = str(form.get('rating', '')).strip()
    rating = None
    if rating_raw:
        try:
            rating = max(1, min(10, int(rating_raw)))
        except Exception:
            raise HTTPException(400, '评分应为1-10的整数')
    taste = str(form.get('taste', '')).strip()
    texture = str(form.get('texture', '')).strip()
    notes = str(form.get('notes', '')).strip()
    next_change = str(form.get('next_change', '')).strip()
    now = now_iso()
    with db() as conn:
        ensure_v10_schema(conn)
        session = conn.execute('SELECT * FROM cook_sessions WHERE id=?', (session_id,)).fetchone()
        if not session:
            raise HTTPException(404)
        conn.execute(
            '''UPDATE cook_sessions SET status='completed',cooked_at=?,rating=?,taste=?,texture=?,notes=?,next_change=?,updated_at=? WHERE id=?''',
            (now, rating, taste, texture, notes, next_change, now, session_id),
        )
        conn.execute('UPDATE recipes SET updated_at=? WHERE id=?', (now, session['recipe_id']))
    return RedirectResponse(f'/life/records/{session_id}', status_code=303)


@router.get('/life/records', response_class=HTMLResponse)
def cook_records_v10(request: Request, recipe_id: int | None = None):
    with db() as conn:
        ensure_v10_schema(conn)
        params: list[Any] = []
        where = ["cs.status='completed'"]
        if recipe_id:
            where.append('cs.recipe_id=?')
            params.append(recipe_id)
        rows = conn.execute(
            f'''SELECT cs.*,r.name recipe_name,rv.version_no,
                       (SELECT COUNT(*) FROM cook_adjustments ca WHERE ca.session_id=cs.id) adjustment_count
                FROM cook_sessions cs JOIN recipes r ON r.id=cs.recipe_id
                JOIN recipe_versions rv ON rv.id=cs.version_id
                WHERE {' AND '.join(where)} ORDER BY cs.cooked_at DESC,cs.id DESC''',
            params,
        ).fetchall()
        recipes = conn.execute('SELECT id,name FROM recipes WHERE archived=0 ORDER BY name').fetchall()
    return templates.TemplateResponse('cook_records_v10.html', _ctx(
        request, records=rows, recipes=recipes, recipe_id=recipe_id
    ))


@router.get('/life/records/{session_id}', response_class=HTMLResponse)
def cook_record_detail_v10(request: Request, session_id: int):
    with db() as conn:
        ensure_v10_schema(conn)
        session = conn.execute(
            '''SELECT cs.*,r.name recipe_name,r.current_version_id,rv.version_no,rv.base_amount standard_base_amount,rv.base_unit
               FROM cook_sessions cs JOIN recipes r ON r.id=cs.recipe_id JOIN recipe_versions rv ON rv.id=cs.version_id
               WHERE cs.id=?''',
            (session_id,),
        ).fetchone()
        if not session:
            raise HTTPException(404)
        adjustments = conn.execute('SELECT * FROM cook_adjustments WHERE session_id=? ORDER BY id', (session_id,)).fetchall()
    return templates.TemplateResponse('cook_record_detail_v10.html', _ctx(
        request, session=session, adjustments=adjustments
    ))


@router.post('/life/records/{session_id}/promote')
async def cook_record_promote_v10(request: Request, session_id: int):
    form = await request.form()
    _csrf(request, str(form.get('csrf', '')))
    selected = set()
    for raw in form.getlist('adjustment_id'):
        try:
            selected.add(int(raw))
        except Exception:
            pass
    with db() as conn:
        ensure_v10_schema(conn)
        session = conn.execute("SELECT * FROM cook_sessions WHERE id=? AND status='completed'", (session_id,)).fetchone()
        if not session:
            raise HTTPException(404)
        old_version = _version_or_404(conn, int(session['version_id']))
        new_id, new_no = _clone_version(
            conn,
            int(session['recipe_id']),
            int(session['version_id']),
            f"基于 {str(session['cooked_at'])[:10]} 的实际制作创建标准 V{int(old_version['version_no']) + 1}",
        )
        if selected:
            rows = conn.execute(
                f"SELECT * FROM cook_adjustments WHERE session_id=? AND id IN ({','.join('?' for _ in selected)}) ORDER BY id",
                (session_id, *sorted(selected)),
            ).fetchall()
            for adj in rows:
                if adj['item_type'] != 'ingredient' or not adj['item_ref']:
                    continue
                source_ing = conn.execute('SELECT * FROM recipe_ingredients WHERE id=?', (adj['item_ref'],)).fetchone()
                if not source_ing:
                    continue
                try:
                    actual = float(adj['actual_value'])
                except Exception:
                    continue
                if source_ing['scale_mode'] == 'proportional' and float(session['base_amount'] or 0) > 0:
                    actual = actual * float(old_version['base_amount']) / float(session['base_amount'])
                conn.execute(
                    '''UPDATE recipe_ingredients SET amount=? WHERE version_id=? AND group_name=? AND name=?''',
                    (actual, new_id, source_ing['group_name'], source_ing['name']),
                )
        conn.execute('UPDATE recipes SET current_version_id=?,updated_at=? WHERE id=?', (new_id, now_iso(), session['recipe_id']))
    return RedirectResponse(f"/life/recipes/{session['recipe_id']}?promoted={new_no}", status_code=303)


@router.get('/life/knowledge', response_class=HTMLResponse)
def knowledge_list_v10(request: Request, q: str = '', category: str = ''):
    with db() as conn:
        ensure_v10_schema(conn)
        where = ['1=1']
        params: list[Any] = []
        if q.strip():
            like = f'%{q.strip()}%'
            where.append('(title LIKE ? OR content LIKE ?)')
            params.extend([like, like])
        if category.strip():
            where.append('category=?')
            params.append(category.strip())
        rows = conn.execute(
            f"SELECT * FROM cooking_knowledge WHERE {' AND '.join(where)} ORDER BY category,title",
            params,
        ).fetchall()
        categories = [r['category'] for r in conn.execute(
            "SELECT DISTINCT category FROM cooking_knowledge WHERE category<>'' ORDER BY category"
        ).fetchall()]
    return templates.TemplateResponse('knowledge_list_v10.html', _ctx(
        request, knowledge=rows, categories=categories, q=q, category=category
    ))


@router.get('/life/knowledge/new', response_class=HTMLResponse)
def knowledge_new_page_v10(request: Request):
    return templates.TemplateResponse('knowledge_edit_v10.html', _ctx(request, item=None))


@router.post('/life/knowledge/new')
async def knowledge_new_v10(request: Request):
    form = await request.form()
    _csrf(request, str(form.get('csrf', '')))
    title = str(form.get('title', '')).strip()
    if not title:
        raise HTTPException(400, '知识点标题不能为空')
    now = now_iso()
    with db() as conn:
        ensure_v10_schema(conn)
        conn.execute(
            '''INSERT INTO cooking_knowledge(category,title,content,source,created_at,updated_at)
               VALUES(?,?,?,?,?,?)''',
            (str(form.get('category', '')).strip(), title, str(form.get('content', '')).strip(), 'manual', now, now),
        )
    return RedirectResponse('/life/knowledge', status_code=303)


@router.get('/life/knowledge/{item_id}/edit', response_class=HTMLResponse)
def knowledge_edit_page_v10(request: Request, item_id: int):
    with db() as conn:
        ensure_v10_schema(conn)
        item = conn.execute('SELECT * FROM cooking_knowledge WHERE id=?', (item_id,)).fetchone()
        if not item:
            raise HTTPException(404)
    return templates.TemplateResponse('knowledge_edit_v10.html', _ctx(request, item=item))


@router.post('/life/knowledge/{item_id}/edit')
async def knowledge_edit_v10(request: Request, item_id: int):
    form = await request.form()
    _csrf(request, str(form.get('csrf', '')))
    title = str(form.get('title', '')).strip()
    if not title:
        raise HTTPException(400, '知识点标题不能为空')
    with db() as conn:
        ensure_v10_schema(conn)
        if not conn.execute('SELECT 1 FROM cooking_knowledge WHERE id=?', (item_id,)).fetchone():
            raise HTTPException(404)
        conn.execute(
            'UPDATE cooking_knowledge SET category=?,title=?,content=?,updated_at=? WHERE id=?',
            (str(form.get('category', '')).strip(), title, str(form.get('content', '')).strip(), now_iso(), item_id),
        )
    return RedirectResponse('/life/knowledge', status_code=303)


# Compatibility marker; safety is implemented in this original function.
ensure_v10_schema.__v144_transaction_safe__ = True
