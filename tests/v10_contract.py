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
from app.v101_recipe_template_data import TEMPLATE_IMPORT_MARKER, TEMPLATE_SHEET_NAMES  # noqa: E402
from app.v101_recipe_template_patch import ensure_v101_recipe_templates  # noqa: E402


def first_route(path: str, method: str = 'GET'):
    rows = [r for r in app.router.routes if getattr(r, 'path', '') == path and method in getattr(r, 'methods', set())]
    assert rows, (path, method)
    return rows[0]


def main():
    assert config.APP_VERSION == '1.0'
    assert app.version == '1.0'
    for path in ('/', '/search', '/work', '/life', '/life/recipes', '/life/records', '/life/knowledge'):
        assert first_route(path), path
    assert first_route('/customers/{customer_id}').endpoint.__module__ == 'app.v0212_routes'
    assert first_route('/customers/{customer_id}/payment.txt').endpoint.__module__ == 'app.v033_payment_flow_patch'
    assert first_route('/life/recipes/{recipe_id}/print').endpoint.__module__ == 'app.v101_recipe_template_patch'
    assert first_route('/life/recipes/{recipe_id}/cook/start', 'POST').endpoint.__name__ == 'recipe_cook_start_disabled_v101'

    init_db()
    ensure_v10_schema()
    ensure_v101_recipe_templates()
    ensure_v101_recipe_templates()  # idempotency
    with db() as conn:
        tables = {r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for table in ('recipes','recipe_versions','recipe_ingredients','recipe_steps','cook_sessions','cook_adjustments','cooking_knowledge'):
            assert table in tables, table
        assert conn.execute('SELECT COUNT(*) n FROM recipes').fetchone()['n'] >= 34
        assert conn.execute('SELECT COUNT(*) n FROM cooking_knowledge').fetchone()['n'] >= 17

        marked = conn.execute(
            'SELECT COUNT(*) n FROM recipe_versions WHERE change_summary LIKE ?',
            (f'{TEMPLATE_IMPORT_MARKER}%',),
        ).fetchone()['n']
        assert marked == len(TEMPLATE_SHEET_NAMES) == 18, (marked, TEMPLATE_SHEET_NAMES)
        for sheet_name in TEMPLATE_SHEET_NAMES:
            assert conn.execute('SELECT id FROM recipes WHERE name=?', (sheet_name,)).fetchone(), sheet_name

        recipe = conn.execute("SELECT * FROM recipes WHERE name='糖醋排骨'").fetchone()
        assert recipe and recipe['current_version_id']
        current = conn.execute('SELECT * FROM recipe_versions WHERE id=?', (recipe['current_version_id'],)).fetchone()
        assert current['change_summary'].startswith(TEMPLATE_IMPORT_MARKER)
        assert float(current['base_amount']) == 500
        salt = conn.execute("SELECT * FROM recipe_ingredients WHERE version_id=? AND name='盐' ORDER BY id LIMIT 1", (current['id'],)).fetchone()
        vinegar = conn.execute("SELECT * FROM recipe_ingredients WHERE version_id=? AND name='6度白醋'", (current['id'],)).fetchone()
        assert float(salt['amount']) == 2.5
        assert _scaled_amount(salt, current, 1000) == '5'
        assert float(vinegar['amount']) == 15
        steps = conn.execute('SELECT * FROM recipe_steps WHERE version_id=? ORDER BY step_no', (current['id'],)).fetchall()
        assert len(steps) == 4
        assert steps[0]['action'] == '1.排骨：500g\n2.焯水：冷水下锅，葱段，姜片，料酒，开锅后2分钟捞出，凉水洗去浮沫\n3.擦干：尽可能擦干水分，晾干'
        assert steps[3]['principle'] == '3.火不要大，容易糊锅'

        new_id, new_no = _clone_version(conn, recipe['id'], current['id'], '测试新标准')
        assert new_no >= 3 and new_id != current['id']
        current_id = conn.execute('SELECT current_version_id FROM recipes WHERE id=?', (recipe['id'],)).fetchone()['current_version_id']
        assert current_id == new_id
        old_vinegar = conn.execute("SELECT amount FROM recipe_ingredients WHERE version_id=? AND name='6度白醋'", (current['id'],)).fetchone()['amount']
        assert float(old_vinegar) == 15

    base = (ROOT / 'app/templates/base.html').read_text(encoding='utf-8')
    for token in (
        'v1.0', 'href="/work"', 'href="/life"', '/static/v10.css?v=1000', '/static/v10.js?v=1000',
        'data-global-back', 'data-back-fallback="{{ _back_fallback }}"', '/static/global-back.css?v=1000',
        '/static/global-back.js?v=1000', 'aria-label="返回上一页"',
    ):
        assert token in base, token
    back_js = (ROOT / 'app/static/global-back.js').read_text(encoding='utf-8')
    assert 'window.history.back()' in back_js
    assert 'window.location.assign(fallback)' in back_js
    assert 'document.referrer' in back_js and 'window.location.origin' in back_js
    back_css = (ROOT / 'app/static/global-back.css').read_text(encoding='utf-8')
    assert '.global-back' in back_css and '.topbar-left' in back_css

    detail = (ROOT / 'app/templates/recipe_detail_v10.html').read_text(encoding='utf-8')
    assert '开始做饭' not in detail
    assert '打印 A4' in detail
    assert '沿用 Excel 原始文本' in detail
    assert 'white-space:pre-wrap' in detail
    print_tpl = (ROOT / 'app/templates/recipe_print_v101.html').read_text(encoding='utf-8')
    print_css = (ROOT / 'app/static/recipe-print-v101.css').read_text(encoding='utf-8')
    assert 'recipe-print-sheet' in print_tpl and 'data-recipe-print' in print_tpl
    assert '@page{size:A4 portrait' in print_css and '@media print' in print_css

    js = (ROOT / 'app/static/v10.js').read_text(encoding='utf-8')
    assert "mode === 'proportional'" in js
    print('v1.0 work/life + Excel template recipes + original text + A4 print + global back contract passed')


if __name__ == '__main__':
    main()
