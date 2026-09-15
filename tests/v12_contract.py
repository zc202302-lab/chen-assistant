from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v12-contract-')
os.environ['APP_DB_PATH'] = str(Path(_TMPDIR.name) / 'app.db')
os.environ.setdefault('APP_USERNAME', 'v12-test')
os.environ.setdefault('APP_PASSWORD_SALT', 'dGVzdHNhbHQ=')
os.environ.setdefault('APP_PASSWORD_HASH', 'x')
os.environ.setdefault('APP_SESSION_SECRET', 'v12-contract-session')
os.environ.setdefault('APP_ENCRYPTION_KEY', 'x')
os.environ.setdefault('APP_SECURE_COOKIE', '0')

from app import config  # noqa: E402
from app.db import db, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.v101_recipe_template_data import TEMPLATE_IMPORT_MARKER, TEMPLATE_SHEET_NAMES  # noqa: E402
from app.v101_recipe_template_patch import ensure_v101_recipe_templates  # noqa: E402


def first_route(path: str, method: str = 'GET'):
    rows = [r for r in app.router.routes if getattr(r, 'path', '') == path and method in getattr(r, 'methods', set())]
    assert rows, (path, method)
    return rows[0]


def main():
    version_parts = tuple(int(part) for part in config.APP_VERSION.split('.')[:2])
    assert version_parts >= (1, 2), config.APP_VERSION
    assert app.version == config.APP_VERSION
    assert first_route('/life').endpoint.__name__ == 'life_home_v10'
    assert first_route('/life/recipes').endpoint.__name__ == 'recipe_list_v10'
    assert first_route('/life/tools').endpoint.__module__ == 'app.v12_tools_routes'
    assert first_route('/life/knowledge').endpoint.__name__ == 'knowledge_list_v10'
    assert first_route('/life/recipes/{recipe_id}/print').endpoint.__module__ == 'app.v101_recipe_template_patch'
    assert first_route('/life/recipes/{recipe_id}/cook/start', 'POST').endpoint.__name__ == 'recipe_cook_start_disabled_v101'
    assert first_route('/customers/{customer_id}').endpoint.__module__ == 'app.v0212_routes'
    assert first_route('/customers/{customer_id}/payment.txt').endpoint.__module__ == 'app.v033_payment_flow_patch'

    init_db(); ensure_v101_recipe_templates(); ensure_v101_recipe_templates()
    with db() as conn:
        marked = int(conn.execute(
            'SELECT COUNT(*) n FROM recipe_versions WHERE change_summary LIKE ?',
            (f'{TEMPLATE_IMPORT_MARKER}%',),
        ).fetchone()['n'])
        assert marked == len(TEMPLATE_SHEET_NAMES) == 18
        sugar = conn.execute("SELECT * FROM recipes WHERE name='糖醋排骨'").fetchone()
        version = conn.execute('SELECT * FROM recipe_versions WHERE id=?', (sugar['current_version_id'],)).fetchone()
        steps = conn.execute('SELECT * FROM recipe_steps WHERE version_id=? ORDER BY step_no', (version['id'],)).fetchall()
        assert len(steps) == 4
        assert steps[0]['action'].startswith('1.排骨：500g\n2.焯水：冷水下锅')
        assert steps[3]['principle'] == '3.火不要大，容易糊锅'

    detail = (ROOT / 'app/templates/recipe_detail_v10.html').read_text(encoding='utf-8')
    assert '开始做饭' not in detail
    assert '打印 A4' in detail and '沿用 Excel 原始文本' in detail
    tools = (ROOT / 'app/templates/cooking_tools_v12.html').read_text(encoding='utf-8')
    for token in ('用盐计算器','技法调味分配','料汁比例计算器','调味品含盐换算','重量与尺寸速查'):
        assert token in tools
    js = (ROOT / 'app/static/v12.js').read_text(encoding='utf-8')
    for token in ('coating === 1 ? 1.3','total * .3','weight / 1.15 / 15','techniqueRatios','base * weight / 500'):
        assert token in js
    print_css = (ROOT / 'app/static/recipe-print-v101.css').read_text(encoding='utf-8')
    print_js = (ROOT / 'app/static/recipe-print-v101.js').read_text(encoding='utf-8')
    assert '@page{size:A4 portrait' in print_css and 'targetHeight = 1040' in print_js
    shell_js = (ROOT / 'app/static/v10.js').read_text(encoding='utf-8')
    assert "replaceChildren('v1.2.1')" not in shell_js and '/life/tools' in shell_js
    base = (ROOT / 'app/templates/base.html').read_text(encoding='utf-8')
    assert 'v{{ request.app.version }}' in base
    print('v1.2 feature contract passed on current app version: 18 Excel templates + original steps + A4 print + formula tools + work isolation')


if __name__ == '__main__':
    main()
