from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = tempfile.TemporaryDirectory(prefix='chen-v143-contract-')
os.environ.setdefault('APP_DB_PATH', str(Path(TMP.name) / 'app.db'))
os.environ.setdefault('APP_USERNAME', 'contract')
os.environ.setdefault('APP_PASSWORD_SALT', 'dGVzdHNhbHQ=')
os.environ.setdefault('APP_PASSWORD_HASH', 'x')
os.environ.setdefault('APP_SESSION_SECRET', 'v143-contract-session')
os.environ.setdefault('APP_ENCRYPTION_KEY', 'x')
os.environ.setdefault('APP_SECURE_COOKIE', '0')

from app.main import app  # noqa: E402


def first_owner(method: str, path: str):
    matches = [
        route for route in app.router.routes
        if getattr(route, 'path', '') == path and method in getattr(route, 'methods', set())
    ]
    assert matches, f'missing route {method} {path}'
    endpoint = matches[0].endpoint
    return getattr(endpoint, '__module__', ''), getattr(endpoint, '__name__', '')


def main():
    assert first_owner('POST', '/services/{service_id}/payment-current') == (
        'app.v031_fixed_review_patch', 'payment_save_preserve_reviews_v032'
    )
    assert first_owner('POST', '/services/{service_id}/payment-review-toggle') == (
        'app.v031_fixed_review_patch', 'payment_review_toggle_preserve_reviews_v032'
    )
    assert first_owner('POST', '/services/{service_id}/toggle-fixed') == (
        'app.v143_payment_controls_patch', 'toggle_fixed_v143_compat'
    )
    assert first_owner('POST', '/customers/{customer_id}/payment-workflow-v031') == (
        'app.v143_payment_controls_patch', 'payment_workflow_v143_compat'
    )
    assert first_owner('POST', '/customers/{customer_id}/documents-v13') == (
        'app.v143_customer_resources', 'upload_document_free_category_v143'
    )
    assert first_owner('GET', '/customers/{customer_id}/resource-items-v143') == (
        'app.v143_customer_resources', 'list_customer_resources_v143'
    )

    base = (ROOT / 'app/templates/base.html').read_text(encoding='utf-8')
    assert '/static/v143_customer_resources.css?v=1431' in base
    assert '/static/v143_customer_resources.js?v=1431' in base

    guard = (ROOT / 'app/static/v031_workflow_dom_guard.js').read_text(encoding='utf-8')
    assert 'if (fixedToggle.disabled) fixedToggle.disabled = false;' in guard
    assert "attributeFilter: ['readonly', 'disabled', 'data-confirmed', 'data-mode']" in guard

    print('v1.4.3 extended compatibility contract passed')


if __name__ == '__main__':
    main()
