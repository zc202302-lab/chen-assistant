from __future__ import annotations

from .db import db, now_iso
from .v10_routes import ensure_v10_schema
from .v12_seed import STANDARD_RECIPES

MIGRATION_KEY = 'v1.2-standard-template-recipes'


def _next_version_no(conn, recipe_id: int) -> int:
    row = conn.execute(
        'SELECT COALESCE(MAX(version_no),0)+1 AS n FROM recipe_versions WHERE recipe_id=?',
        (recipe_id,),
    ).fetchone()
    return int(row['n'])


def _import_one(conn, name: str, payload: dict):
    now = now_iso()
    recipe = conn.execute('SELECT * FROM recipes WHERE name=?', (name,)).fetchone()
    if recipe:
        recipe_id = int(recipe['id'])
    else:
        cur = conn.execute(
            'INSERT INTO recipes(name,category,tags,description,source,archived,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
            (name, payload['category'], '', '', 'excel-template-v12', 0, now, now),
        )
        recipe_id = int(cur.lastrowid)

    version_no = _next_version_no(conn, recipe_id)
    cur = conn.execute(
        'INSERT INTO recipe_versions(recipe_id,version_no,base_amount,base_unit,change_summary,created_at) VALUES(?,?,?,?,?,?)',
        (
            recipe_id,
            version_no,
            float(payload['base_amount']),
            payload.get('base_unit') or 'g',
            f"v1.2 从 Excel「{payload['source_sheet']}」按糖醋排骨模板原样导入",
            now,
        ),
    )
    version_id = int(cur.lastrowid)

    for idx, (group_name, item_name, amount, note) in enumerate(payload['ingredients'], 1):
        conn.execute(
            'INSERT INTO recipe_ingredients(version_id,group_name,name,amount,unit,scale_mode,note,sort_order) VALUES(?,?,?,?,?,?,?,?)',
            (
                version_id,
                group_name or '配料',
                item_name,
                amount,
                '',
                'proportional' if amount is not None else 'manual',
                note or '',
                idx * 10,
            ),
        )

    for step_no, title, action, principle in payload['steps']:
        conn.execute(
            'INSERT INTO recipe_steps(version_id,step_no,title,action,heat,duration,judgement,principle,risk) VALUES(?,?,?,?,?,?,?,?,?)',
            (version_id, step_no, title, action, '', '', '', principle or '', ''),
        )

    conn.execute(
        "UPDATE recipes SET category=?,description=?,source='excel-template-v12',archived=0,current_version_id=?,updated_at=? WHERE id=?",
        (
            payload['category'],
            f"来源：原《菜谱.xlsm》Sheet「{payload['source_sheet']}」；步骤保留 Excel 原始文本。",
            version_id,
            now,
            recipe_id,
        ),
    )


def ensure_v12_schema(conn=None):
    owns = conn is None
    if owns:
        manager = db()
        conn = manager.__enter__()
    try:
        ensure_v10_schema(conn)
        conn.execute(
            'CREATE TABLE IF NOT EXISTS app_data_migrations (migration_key TEXT PRIMARY KEY, applied_at TEXT NOT NULL)'
        )
        if conn.execute(
            'SELECT 1 FROM app_data_migrations WHERE migration_key=?', (MIGRATION_KEY,)
        ).fetchone():
            return

        names = tuple(STANDARD_RECIPES.keys())
        marks = ','.join('?' for _ in names)
        conn.execute(
            f"UPDATE recipes SET archived=1 WHERE source='excel-catalog' AND name NOT IN ({marks})",
            names,
        )
        for name, payload in STANDARD_RECIPES.items():
            _import_one(conn, name, payload)
        conn.execute(
            'INSERT INTO app_data_migrations(migration_key,applied_at) VALUES(?,?)',
            (MIGRATION_KEY, now_iso()),
        )
    finally:
        if owns:
            manager.__exit__(None, None, None)
