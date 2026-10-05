"""Single runtime routing registry. Import order and priority preserve existing owners.

Historical imports may install compatibility patches; they are intentionally retained.
Use route_inventory() to inspect the actual runtime instead of inferring from filenames.
"""
import re
from starlette.routing import Match
from .reminders import router as reminders_router
from .v02_routes import router as v02_router
from .v021_routes import router as v021_router
from .v023_routes import router as v023_router
from .v025_routes import router as v025_router
from .v026_routes import router as v026_router
from .v027_routes import router as v027_router
from .v028_routes import router as v028_router
from .v0211_routes import router as v0211_router
from .v0211_promotion_routes import router as v0211_promotion_router
from .v0212_routes import router as v0212_router
from .v0212_business_display_routes import router as v0212_business_display_router
from .v03_routes import router as v03_router
from .v03_payment_routes import router as v03_payment_router
from .v031_runtime_routes import router as v031_runtime_router
from .v03_mail_draft_routes import router as v03_mail_draft_router
from .v031_payment_workflow_routes import router as v031_payment_workflow_router
from .v032_customer_import_routes import router as v032_customer_import_router
from .v032_customer_exchange_routes import router as v032_customer_exchange_router
from .v031_fixed_review_patch import router as v031_review_sync_router
from . import v031_fixed_review_patch as _v031_fixed_review_patch  # noqa: F401
from .v033_payment_flow_patch import router as v033_payment_flow_patch_router
from .v10_routes import router as v10_router, ensure_v10_schema
from .v101_workspace_routes import router as v101_workspace_router
from .work_list_import import router as work_list_import_router, ensure_work_list_import_schema
from .work_lists import router as work_lists_router, ensure_work_lists_schema
from .v160_information_center import router as v160_information_center_router, ensure_v160_schema

ROUTER_REGISTRATION = (
    ('_reminder_routes', reminders_router),
    ('_v02_routes', v02_router),
    ('_v021_routes', v021_router),
    ('_v023_routes', v023_router),
    ('_v025_routes', v025_router),
    ('_v026_routes', v026_router),
    ('_v027_routes', v027_router),
    ('_v028_routes', v028_router),
    ('_v0211_routes', v0211_router),
    ('_v0211_promotion_routes', v0211_promotion_router),
    ('_v0212_routes', v0212_router),
    ('_v0212_business_display_routes', v0212_business_display_router),
    ('_v03_routes', v03_router),
    ('_v03_payment_routes', v03_payment_router),
    ('_v031_runtime_routes', v031_runtime_router),
    ('_v03_mail_draft_routes', v03_mail_draft_router),
    ('_v031_payment_workflow_routes', v031_payment_workflow_router),
    ('_v031_review_sync_routes', v031_review_sync_router),
    ('_v032_customer_import_routes', v032_customer_import_router),
    ('_v032_customer_exchange_routes', v032_customer_exchange_router),
    ('_v033_payment_flow_patch_routes', v033_payment_flow_patch_router),
    ('_v10_routes', v10_router),
    ('_v101_workspace_routes', v101_workspace_router),
    ('_v160_information_center_routes', v160_information_center_router),
    ('_work_lists_routes', work_lists_router),
    ('_work_list_import_routes', work_list_import_router),
)
ROUTER_PRIORITY = (
    '_reminder_routes',
    '_work_list_import_routes',
    '_work_lists_routes',
    '_v160_information_center_routes',
    '_v101_workspace_routes',
    '_v10_routes',
    '_v033_payment_flow_patch_routes',
    '_v032_customer_exchange_routes',
    '_v032_customer_import_routes',
    '_v031_review_sync_routes',
    '_v031_payment_workflow_routes',
    '_v03_mail_draft_routes',
    '_v031_runtime_routes',
    '_v03_payment_routes',
    '_v03_routes',
    '_v0212_business_display_routes',
    '_v0212_routes',
    '_v0211_promotion_routes',
    '_v0211_routes',
    '_v028_routes',
    '_v027_routes',
    '_v026_routes',
    '_v025_routes',
    '_v023_routes',
    '_v021_routes',
    '_v02_routes',
    '_legacy_routes',
)

def configure_routes(app):
    if getattr(app.state, "routes_configured", False):
        raise RuntimeError("Runtime routes are already configured")
    legacy = list(app.router.routes)
    owned = {'_legacy_routes': legacy}
    for name, router in ROUTER_REGISTRATION:
        before = len(app.router.routes)
        app.include_router(router)
        owned[name] = app.router.routes[before:]
    seen = set()
    final = []
    for name in ROUTER_PRIORITY:
        for route in owned[name]:
            key = (getattr(route, 'path', None), tuple(sorted(getattr(route, 'methods', set()))))
            if key not in seen:
                seen.add(key)
                final.append(route)
    app.state.route_source_groups = owned
    app.router.routes[:] = final
    for route in final:
        if (getattr(route, 'path', '') == '/customers/{customer_id}'
                and getattr(getattr(route, 'endpoint', None), '__module__', '') == 'app.v0212_routes'):
            route.path_regex = re.compile(r'^/customers/(?P<customer_id>[0-9]+)$')
            break
    assert_route_owners(app)
    app.state.routes_configured = True


def route_inventory(app):
    """Return ordered, serializable runtime owners; no database or customer data."""
    return [{
        'path': getattr(route, 'path', None),
        'methods': sorted(getattr(route, 'methods', [])),
        'module': getattr(getattr(route, 'endpoint', None), '__module__', ''),
        'name': getattr(getattr(route, 'endpoint', None), '__name__', ''),
    } for route in app.router.routes]

def _assert_customer_new_route_guard(app):
    new_scope = {'type': 'http', 'path': '/customers/new', 'method': 'GET'}
    id_scope = {'type': 'http', 'path': '/customers/123', 'method': 'GET'}
    full_new = [route for route in app.router.routes if hasattr(route, 'matches') and route.matches(new_scope)[0] == Match.FULL]
    if not full_new:
        raise RuntimeError('v1.0 路由自检失败：/customers/new 没有可用 GET 路由')
    owner = getattr(getattr(full_new[0], 'endpoint', None), '__module__', '')
    if getattr(full_new[0], 'path', '') != '/customers/new' or owner != 'app.v032_customer_import_routes':
        raise RuntimeError('v1.0 路由自检失败：/customers/new 被其他客户路由抢占，已停止启动')
    detail = next((route for route in app.router.routes if getattr(route, 'path', '') == '/customers/{customer_id}' and getattr(getattr(route, 'endpoint', None), '__module__', '') == 'app.v0212_routes'), None)
    if detail is None or detail.matches(new_scope)[0] != Match.NONE or detail.matches(id_scope)[0] != Match.FULL:
        raise RuntimeError('v1.0 路由自检失败：客户详情路由没有被限制为数字 customer_id')

def _assert_payment_review_route_guard(app):
    expected = {
        '/services/{service_id}/payment-current': 'payment_save_preserve_reviews_v032',
        '/services/{service_id}/payment-review-toggle': 'payment_review_toggle_preserve_reviews_v032',
    }
    for path, endpoint_name in expected.items():
        matches = [route for route in app.router.routes if getattr(route, 'path', '') == path and 'POST' in getattr(route, 'methods', set())]
        if not matches or getattr(getattr(matches[0], 'endpoint', None), '__name__', '') != endpoint_name:
            raise RuntimeError(f'v1.0 缴费路由自检失败：{path} 未由行级核对逻辑接管')

def _assert_payment_flow_v033_guard(app):
    expected = {
        ('GET', '/customers/{customer_id}/payment.txt'): 'payment_txt_current_workflow_v033',
        ('GET', '/customers/{customer_id}/mail-template-v03'): 'get_customer_payment_template_v033',
        ('POST', '/customers/{customer_id}/mail-template-v03'): 'save_customer_payment_template_v033',
        ('GET', '/customers/{customer_id}/payment-mail-compose-v031'): 'payment_mail_compose_customer_scoped_v033',
        ('GET', '/customers/{customer_id}/payment-mail-draft-v03'): 'payment_mail_draft_customer_scoped_v033',
    }
    for (method, path), endpoint_name in expected.items():
        matches = [route for route in app.router.routes if getattr(route, 'path', '') == path and method in getattr(route, 'methods', set())]
        if not matches or getattr(getattr(matches[0], 'endpoint', None), '__name__', '') != endpoint_name:
            raise RuntimeError(f'v1.0 缴费路由自检失败：{method} {path} 未由当前实现接管')

def _assert_v10_route_guard(app):
    v10_expected = {
        ('GET', '/'): 'home_v10',
        ('GET', '/life'): 'life_home_v10',
        ('GET', '/life/recipes'): 'recipe_list_v10',
        ('GET', '/life/records'): 'cook_records_v10',
        ('GET', '/life/knowledge'): 'knowledge_list_v10',
    }
    for (method, path), endpoint_name in v10_expected.items():
        matches = [r for r in app.router.routes if getattr(r, 'path', '') == path and method in getattr(r, 'methods', set())]
        if not matches or getattr(matches[0].endpoint, '__module__', '') != 'app.v10_routes' or getattr(matches[0].endpoint, '__name__', '') != endpoint_name:
            raise RuntimeError(f'v1.0 路由自检失败：{method} {path} 未由 v1.0 接管')

    workspace_expected = {
        ('GET', '/work'): ('work_home_v101', 'app.v10_routes'),
        ('GET', '/search'): ('work_search_v101', 'app.v10_routes'),
        ('GET', '/global-search'): ('global_search_v101', 'app.v101_workspace_routes'),
    }
    for (method, path), (endpoint_name, module_name) in workspace_expected.items():
        matches = [r for r in app.router.routes if getattr(r, 'path', '') == path and method in getattr(r, 'methods', set())]
        if not matches or getattr(matches[0].endpoint, '__module__', '') != module_name or getattr(matches[0].endpoint, '__name__', '') != endpoint_name:
            raise RuntimeError(f'v1.0 工作空间隔离自检失败：{method} {path}')

def assert_route_owners(app):
    _assert_customer_new_route_guard(app)
    _assert_payment_review_route_guard(app)
    _assert_payment_flow_v033_guard(app)
    _assert_v10_route_guard(app)
