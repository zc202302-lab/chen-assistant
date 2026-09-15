from __future__ import annotations

import inspect
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = tempfile.TemporaryDirectory(prefix='chen-v144-audit-')
os.environ.update({
    'APP_DB_PATH': str(Path(TMP.name) / 'app.db'),
    'APP_USERNAME': 'audit',
    'APP_PASSWORD_SALT': 'dGVzdHNhbHQ=',
    'APP_PASSWORD_HASH': 'x',
    'APP_SESSION_SECRET': 'v144-audit-session',
    'APP_ENCRYPTION_KEY': 'x',
    'APP_SECURE_COOKIE': '0',
})

from app.db import db, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app import v10_routes as v10  # noqa: E402
from app import v101_recipe_template_patch as v101  # noqa: E402


STATIC_REF_RE = re.compile(r'''(?:src|href)=["'](/static/[^"'?]+)(?:\?[^"']*)?["']''')


def first_owner(method: str, path: str):
    matches = [
        route for route in app.router.routes
        if getattr(route, 'path', '') == path and method in getattr(route, 'methods', set())
    ]
    assert matches, f'missing route {method} {path}'
    endpoint = matches[0].endpoint
    return getattr(endpoint, '__module__', ''), getattr(endpoint, '__name__', '')


def audit_static_references():
    missing = []
    referenced_js = set()
    for template in (ROOT / 'app' / 'templates').glob('*.html'):
        text = template.read_text(encoding='utf-8')
        for match in STATIC_REF_RE.finditer(text):
            url_path = match.group(1)
            relative = url_path.removeprefix('/static/')
            target = ROOT / 'app' / 'static' / relative
            if not target.is_file():
                missing.append(f'{template.name}: {url_path}')
            if relative.endswith('.js'):
                referenced_js.add(relative)
    assert not missing, 'missing template static assets:\n' + '\n'.join(missing)
    assert 'v123_foxmail_compose_fix.js' in referenced_js

    workflow = (ROOT / '.github/workflows/rebuild-check.yml').read_text(encoding='utf-8')
    deploy = (ROOT / 'deploy.sh').read_text(encoding='utf-8')
    assert "find app/static -maxdepth 1 -type f -name '*.js'" in workflow, 'CI must syntax-check every JS asset'
    assert "find app/static -maxdepth 1 -type f -name '*.js'" in deploy, 'deploy must syntax-check every JS asset'
    assert "find app/static -maxdepth 1 -type f \\( -name '*.js' -o -name '*.css' \\)" in deploy, 'deploy must hash-check every JS/CSS asset'
    assert 'CHEN_DEPLOY_REEXEC' in deploy and 'exec env CHEN_DEPLOY_REEXEC=1' in deploy, 'deploy must re-exec after self-update'
    assert deploy.index('git merge --ff-only origin/main') < deploy.index('BACKUP_FILE='), 'updated deploy script must re-exec before DB backup/migrations'


def audit_transaction_guards():
    assert getattr(v10.ensure_v10_schema, '__v144_transaction_safe__', False)
    assert getattr(v101.ensure_v101_recipe_templates, '__v144_transaction_safe__', False)

    init_db()
    original_seed = v10._seed_recipe

    def fail_after_write(conn, name, category, tags):
        conn.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('v144_partial_seed','must_rollback')")
        raise RuntimeError('synthetic seed failure')

    v10._seed_recipe = fail_after_write
    try:
        try:
            v10.ensure_v10_schema()
        except RuntimeError as exc:
            assert str(exc) == 'synthetic seed failure'
        else:
            raise AssertionError('synthetic seed failure did not propagate')
    finally:
        v10._seed_recipe = original_seed

    with db() as conn:
        row = conn.execute("SELECT value FROM app_meta WHERE key='v144_partial_seed'").fetchone()
        assert row is None, 'schema seeding committed partial data after an exception'


def audit_remote_storage_integrity_guards():
    documents = (ROOT / 'app/v13_customer_documents.py').read_text(encoding='utf-8')
    storage = (ROOT / 'storage_node/app.py').read_text(encoding='utf-8')
    for token in (
        "remote_size = int(remote_meta.get('size', -1))",
        "remote_hash = str(remote_meta.get('sha256', '')).lower()",
        'if remote_size != sent or remote_hash != local_hash:',
        'await _best_effort_remote_delete(storage_key)',
        "_CONTROL_RE = re.compile(r'[\\x00-\\x1f\\x7f]+')",
    ):
        assert token in documents, token
    assert "except (TypeError, ValueError):\n    MAX_FILE_MB = 50" in storage


def audit_route_ownership():
    expected = {
        ('POST', '/life/recipes/new'): ('app.v144_audit_hardening', 'recipe_new_validation_v144'),
        ('POST', '/life/recipes/{recipe_id}/edit'): ('app.v144_audit_hardening', 'recipe_edit_validation_v144'),
        ('POST', '/life/knowledge/new'): ('app.v144_audit_hardening', 'knowledge_new_validation_v144'),
        ('POST', '/life/knowledge/{item_id}/edit'): ('app.v144_audit_hardening', 'knowledge_edit_validation_v144'),
        ('POST', '/services/{service_id}/toggle-fixed'): ('app.v143_payment_controls_patch', 'toggle_fixed_v143_compat'),
        ('POST', '/customers/{customer_id}/documents-v13'): ('app.v143_customer_resources', 'upload_document_free_category_v143'),
    }
    for (method, path), owner in expected.items():
        assert first_owner(method, path) == owner, (method, path, first_owner(method, path), owner)


def audit_csrf_first_winners():
    """Every state-changing winning POST route must visibly enforce/delegate CSRF.

    Historical edit form routes v0.2.5/v0.2.6 intentionally delegate to their
    JSON attribute-edit handlers. Those handlers call ``check_csrf`` before any DB
    write, so the wrapper source is accepted only when the exact verified delegate
    call remains present. The one allowlisted POST is intentionally non-mutating:
    v1.0.1 removed cooking mode and the endpoint only redirects an old form action.
    """
    markers = (
        'check_csrf(', '_csrf(', 'require_csrf(', 'csrf=csrf',
        'edit_service_attributes_v025(', 'edit_service_attributes_v026(',
    )
    allow = {
        ('/life/recipes/{recipe_id}/cook/start', 'app.v101_recipe_template_patch', 'recipe_cook_start_disabled_v101'),
    }
    seen = set()
    uncovered = []
    for route in app.router.routes:
        if 'POST' not in getattr(route, 'methods', set()):
            continue
        path = getattr(route, 'path', '')
        key = ('POST', path)
        if key in seen:
            continue
        seen.add(key)
        endpoint = route.endpoint
        module = getattr(endpoint, '__module__', '')
        name = getattr(endpoint, '__name__', '')
        if path == '/login' or (path, module, name) in allow:
            continue
        try:
            source = inspect.getsource(endpoint)
        except (OSError, TypeError):
            uncovered.append((path, module, name, 'source unavailable'))
            continue
        if not any(marker in source for marker in markers):
            uncovered.append((path, module, name, 'no CSRF marker/delegate'))
    assert not uncovered, 'winning POST routes without visible CSRF protection/delegation:\n' + '\n'.join(map(str, uncovered))


def main():
    audit_static_references()
    audit_transaction_guards()
    audit_remote_storage_integrity_guards()
    audit_route_ownership()
    audit_csrf_first_winners()
    print('v1.4.4 full-code audit contract passed: assets + transactions + deployment + remote storage + routes + CSRF')


if __name__ == '__main__':
    main()
