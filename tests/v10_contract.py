from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v10-contract-')
os.environ['APP_DB_PATH'] = str(Path(_TMPDIR.name) / 'app.db')
os.environ.setdefault('APP_USERNAME', 'v10-test')
os.environ.setdefault('APP_PASSWORD_SALT', 'dGVzdHNhbHQ=')
os.environ.setdefault('APP_PASSWORD_HASH', 'x')
os.environ.setdefault('APP_SESSION_SECRET', 'v10-contract-session')
os.environ.setdefault('APP_ENCRYPTION_KEY', 'x')
os.environ.setdefault('APP_SECURE_COOKIE', '0')

from app import config  # noqa: E402
from app.db import db, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.v10_routes import ensure_v10_schema, _clone_version, _scaled_amount  # noqa: E402


def first_route(path: str, method: str = 'GET'):
    rows = [r for r in app.router.routes if getattr(r, 'path', '') == path and method in getattr(r, 'methods', set())]
    assert rows, (path, method)
    return rows[0]


def main():
    assert config.APP_VERSION == '1.0'
    assert app.version == '1.0'
    for path in ('/', '/search', '/work', '/life', '/life/recipes', '/life/records', '/life/knowledge'):
        assert first_route(path).endpoint.__module__ == 'app.v10_routes', path
    assert first_route('/customers/{customer_id}').endpoint.__module__ == 'app.v0212_routes'
    assert first_route('/customers/{customer_id}/payment.txt').endpoint.__module__ == 'app.v033_payment_flow_patch'

    init_db()
    ensure_v10_schema()
    ensure_v10_schema()  # idempotency
    with db() as conn:
        tables = {r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for table in ('recipes','recipe_versions','recipe_ingredients','recipe_steps','cook_sessions','cook_adjustments','cooking_knowledge'):
            assert table in tables, table
        assert conn.execute('SELECT COUNT(*) n FROM recipes').fetchone()['n'] >= 33
        assert conn.execute('SELECT COUNT(*) n FROM cooking_knowledge').fetchone()['n'] >= 17

        recipe = conn.execute("SELECT * FROM recipes WHERE name='糖醋排骨'").fetchone()
        assert recipe and recipe['current_version_id']
        v1 = conn.execute('SELECT * FROM recipe_versions WHERE id=?', (recipe['current_version_id'],)).fetchone()
        assert v1['version_no'] == 1 and float(v1['base_amount']) == 500
        salt = conn.execute("SELECT * FROM recipe_ingredients WHERE version_id=? AND name='盐'", (v1['id'],)).fetchone()
        vinegar = conn.execute("SELECT * FROM recipe_ingredients WHERE version_id=? AND name='6度白醋'", (v1['id'],)).fetchone()
        assert float(salt['amount']) == 2.5
        assert _scaled_amount(salt, v1, 1000) == '5'
        assert float(vinegar['amount']) == 15
        assert conn.execute('SELECT COUNT(*) n FROM recipe_steps WHERE version_id=?', (v1['id'],)).fetchone()['n'] == 5

        new_id, new_no = _clone_version(conn, recipe['id'], v1['id'], '测试新标准')
        assert new_no == 2 and new_id != v1['id']
        current = conn.execute('SELECT current_version_id FROM recipes WHERE id=?', (recipe['id'],)).fetchone()['current_version_id']
        assert current == new_id
        # Historical V1 is immutable and still present.
        assert conn.execute('SELECT COUNT(*) n FROM recipe_versions WHERE recipe_id=?', (recipe['id'],)).fetchone()['n'] == 2
        old_vinegar = conn.execute("SELECT amount FROM recipe_ingredients WHERE version_id=? AND name='6度白醋'", (v1['id'],)).fetchone()['amount']
        assert float(old_vinegar) == 15

    base = (ROOT / 'app/templates/base.html').read_text(encoding='utf-8')
    for token in ('v1.0', 'href="/work"', 'href="/life"', '/static/v10.css?v=1000', '/static/v10.js?v=1000'):
        assert token in base, token
    js = (ROOT / 'app/static/v10.js').read_text(encoding='utf-8')
    assert "mode === 'proportional'" in js
    assert 'data-add-ingredient' in js and 'data-add-step' in js
    print('v1.0 work/life + evolving recipe standard contract passed')


if __name__ == '__main__':
    main()
