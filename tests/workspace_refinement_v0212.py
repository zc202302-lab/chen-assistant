from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402
from app.v0212_business_display_routes import (  # noqa: E402
    SYSTEM_PAYMENT_STATE_KEY,
    _normalize_requested,
)


def first_route(path: str, method: str):
    matches = [
        route for route in app.router.routes
        if getattr(route, 'path', '') == path and method in getattr(route, 'methods', set())
    ]
    assert matches, f'{method} {path} missing'
    return matches[0]


def test_business_display_api_owned_by_current_module():
    module = 'app.v0212_business_display_routes'
    assert first_route('/customers/{customer_id}/business-columns-v0212', 'GET').endpoint.__module__ == module
    assert first_route('/customers/{customer_id}/business-columns-v0212', 'POST').endpoint.__module__ == module


def test_business_display_normalization_keeps_order_and_system_state():
    template = [
        {'key': 'service_type', 'label': '类型'},
        {'key': 'number', 'label': '号码'},
        {'key': 'account', 'label': '账号'},
    ]
    requested = ['account', SYSTEM_PAYMENT_STATE_KEY, 'number', 'account', 'missing']
    assert _normalize_requested(template, requested) == ['account', SYSTEM_PAYMENT_STATE_KEY, 'number']


def test_frontend_contracts():
    js = (ROOT / 'app/static/workspace-refinement-v0212.js').read_text(encoding='utf-8')
    css = (ROOT / 'app/static/workspace-refinement-v0212.css').read_text(encoding='utf-8')
    base = (ROOT / 'app/templates/base.html').read_text(encoding='utf-8')

    assert "payment-auto-fit-v0212" in js
    assert "--payment-column-count" in js
    assert "document.addEventListener('dblclick'" in js
    assert "[data-business-row] .business-attribute" in js
    assert "business-columns-v0212" in js
    assert "显示属性" in js
    assert "payment-edit-v0211" in css and "business-edit-v029" in css
    assert "repeat(var(--payment-column-count,1),minmax(0,1fr))" in css
    assert "overflow-x:hidden" in css
    assert base.count('/static/workspace-refinement-v0212.js') == 1
    assert base.count('/static/workspace-refinement-v0212.css') == 1


if __name__ == '__main__':
    test_business_display_api_owned_by_current_module()
    test_business_display_normalization_keeps_order_and_system_state()
    test_frontend_contracts()
    print('workspace refinement v0.2.12 checks passed')
