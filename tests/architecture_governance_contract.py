"""Enforce the governed boundaries and exercise actual rollback/asset behavior."""
import ast
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
temp = tempfile.TemporaryDirectory()
os.environ['APP_DB_PATH'] = str(Path(temp.name) / 'app.db')
from starlette.templating import Jinja2Templates as NativeTemplates
native_response = NativeTemplates.TemplateResponse
from app.main import app
from app.db import db, init_db, execute_schema
from app.routing import route_source_inventory
from app.v162_number_inbox import ensure_number_inbox_schema
from app.v160_information_center import ensure_v160_schema
from app.schema import SCHEMA_STAGES, initialize_schema


assert NativeTemplates.TemplateResponse is native_response, 'application must not patch third-party classes'
expected_sources = json.loads((ROOT / 'docs/RUNTIME_ROUTE_SOURCES.json').read_text())
actual_sources = route_source_inventory(app)
optional_path = '/work/number-inbox/export-group-batch'
extras = [row for row in actual_sources if row['path'] == optional_path]
assert extras in ([], [{'path': optional_path, 'methods': ['POST'], 'source': 'v162_number_inbox.py', 'qualname': 'number_inbox_export_group_batch'}])
# PR #142: audited home-shortcut routes are the only additional live sources.
home_source_extras = [
    {'path': '/home/shortcuts', 'methods': ['GET'], 'source': 'v101_workspace_routes.py', 'qualname': 'get_home_shortcuts'},
    {'path': '/home/shortcuts', 'methods': ['POST'], 'source': 'v101_workspace_routes.py', 'qualname': 'save_home_shortcuts'},
]
assert [row for row in actual_sources if row['path'] == '/home/shortcuts'] == home_source_extras
assert [row for row in actual_sources if row['path'] not in {optional_path, '/home/shortcuts'}] == expected_sources
legacy = json.loads((ROOT / 'docs/LEGACY_MODULES.json').read_text())
assert sorted(legacy) == sorted(p.name for p in (ROOT / 'app').glob('v[0-9]*.py'))
for path in (ROOT / 'app').glob('*.py'):
    tree = ast.parse(path.read_text())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(item.asname or item.name.split('.')[0] for item in node.names)
        if isinstance(node, ast.ImportFrom) and node.module is None:
            modules.update(item.asname or item.name for item in node.names)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {'__enter__', '__exit__', '__code__'}, (path, node.lineno, node.attr)
            assert node.attr != 'executescript', (path, 'implicit transaction commit')
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                base = target
                while isinstance(base, ast.Attribute):
                    base = base.value
                assert not (isinstance(target, ast.Attribute) and isinstance(base, ast.Name) and base.id in modules), (path, node.lineno, 'cross-module mutation')

init_db()
try:
    with db() as conn:
        conn.execute("INSERT INTO app_meta(key,value) VALUES('governance-rollback','pending')")
        ensure_number_inbox_schema(conn)
        ensure_v160_schema(conn)
        raise RuntimeError('abort caller transaction')
except RuntimeError:
    pass
with db() as conn:
    assert conn.execute("SELECT 1 FROM app_meta WHERE key='governance-rollback'").fetchone() is None
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='number_inbox'").fetchone() is None
try:
    with db() as conn:
        execute_schema(conn, "CREATE TABLE rollback_ddl(x TEXT); INSERT INTO rollback_ddl VALUES('semi;colon'); INVALID SQL;")
except Exception:
    pass
else:
    raise AssertionError('invalid schema must propagate')
with db() as conn:
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='rollback_ddl'").fetchone() is None
    execute_schema(conn, "CREATE TABLE valid_script(x TEXT); INSERT INTO valid_script VALUES('semi;colon');")
    assert conn.execute('SELECT x FROM valid_script').fetchone()[0] == 'semi;colon'

# Startup declarations remain ordered, explicit and idempotent.
for stage in SCHEMA_STAGES:
    initialize_schema(stage)
    initialize_schema(stage)
with db() as conn:
    assert conn.execute('PRAGMA foreign_key_check').fetchall() == []

from app.templating import Jinja2Templates
from starlette.requests import Request
templates = Jinja2Templates(directory=ROOT / 'app/templates')
manifest = json.loads((ROOT / 'docs/FRONTEND_ASSETS.json').read_text())
base = (ROOT / 'app/templates/base.html').read_text()
assert re.findall(r'<script src="/static/([^"?]+)', base) == manifest['scripts']
assert re.findall(r'<link[^>]+href="/static/([^"?]+\.css)', base) == manifest['styles']
for before, after in manifest['dependencies']:
    assert manifest['scripts'].index(before) < manifest['scripts'].index(after)
def scripts_for(path):
    request = Request({'type': 'http', 'path': path, 'app': app, 'headers': []})
    html = templates.get_template('base.html').render(request=request, csrf='test')
    return re.findall(r'<script src="/static/([^"?]+)', html)
customer = scripts_for('/customers/123')
assert [x for x in manifest['scripts'] if x not in {'v10.js', 'v12.js'}] == customer
for path in ['/', '/info', '/work', '/work/lists', '/reminders']:
    assert 'v031_workflow_runtime_fix.js' not in scripts_for(path), path
    assert 'reminders.js' in scripts_for(path) and 'pwa-experience.js' in scripts_for(path), path
# The dashboard has an inline search initializer in v03.js despite living in
# /work. Keep only that necessary extra asset; other customer controllers stay scoped.
for path in ['/work/customers', '/work/customers/']:
    dashboard_scripts = scripts_for(path)
    assert 'v03.js' in dashboard_scripts, path
    assert 'v031_workflow_runtime_fix.js' not in dashboard_scripts, path
for path in ['/', '/info', '/work', '/work/lists', '/work/customers-extra']:
    assert 'v03.js' not in scripts_for(path), path
assert 'v10.js' in scripts_for('/life/recipes/1')
assert 'v12.js' in scripts_for('/life/tools')
print('architecture governance passed: source ownership, no monkey patches, rollback, startup, page assets')
