import re

from starlette.routing import Match

from . import config
from .legacy_main import app
from .v02_routes import router as v02_router
from .v021_routes import router as v021_router
from .v022_routes import router as v022_router
from .v023_routes import router as v023_router
from .v024_routes import router as v024_router
from .v025_routes import router as v025_router
from .v025_home import router as v025_home_router
from .v026_routes import router as v026_router
from .v026_home import router as v026_home_router
from .v027_routes import router as v027_router
from .v027_home import router as v027_home_router
from .v028_routes import router as v028_router
from .v029_routes import router as v029_router
from .v0211_routes import router as v0211_router
from .v0211_promotion_routes import router as v0211_promotion_router
from .v0212_routes import router as v0212_router
from .v0212_payment_routes import router as v0212_payment_router
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

_legacy_routes = list(app.router.routes)


def _include(router):
    before = len(app.router.routes)
    app.include_router(router)
    return app.router.routes[before:]


_v02_routes = _include(v02_router)
_v021_routes = _include(v021_router)
_v022_routes = _include(v022_router)
_v023_routes = _include(v023_router)
_v024_routes = _include(v024_router)
_v025_routes = _include(v025_router)
_v025_home_routes = _include(v025_home_router)
_v026_routes = _include(v026_router)
_v026_home_routes = _include(v026_home_router)
_v027_routes = _include(v027_router)
_v027_home_routes = _include(v027_home_router)
_v028_routes = _include(v028_router)
_v029_routes = _include(v029_router)
_v0211_routes = _include(v0211_router)
_v0211_promotion_routes = _include(v0211_promotion_router)
_v0212_routes = _include(v0212_router)
_v0212_payment_routes = _include(v0212_payment_router)
_v0212_business_display_routes = _include(v0212_business_display_router)
_v03_routes = _include(v03_router)
_v03_payment_routes = _include(v03_payment_router)
_v031_runtime_routes = _include(v031_runtime_router)
_v03_mail_draft_routes = _include(v03_mail_draft_router)
_v031_payment_workflow_routes = _include(v031_payment_workflow_router)
_v031_review_sync_routes = _include(v031_review_sync_router)
_v032_customer_import_routes = _include(v032_customer_import_router)
_v032_customer_exchange_routes = _include(v032_customer_exchange_router)
_v033_payment_flow_patch_routes = _include(v033_payment_flow_patch_router)
_v10_routes = _include(v10_router)

# v1.0 owns the global home/search and life workspace. The mature work routes
# continue to own customer/payment behavior exactly as before.
_ordered = (
    _v10_routes +
    _v033_payment_flow_patch_routes +
    _v032_customer_exchange_routes + _v032_customer_import_routes + _v031_review_sync_routes +
    _v031_payment_workflow_routes + _v03_mail_draft_routes + _v031_runtime_routes +
    _v03_payment_routes + _v03_routes + _v0212_business_display_routes +
    _v0212_payment_routes + _v0212_routes + _v0211_promotion_routes + _v0211_routes +
    _v029_routes + _v028_routes + _v027_home_routes + _v027_routes +
    _v026_home_routes + _v026_routes + _v025_home_routes + _v025_routes +
    _v024_routes + _v023_routes + _v022_routes + _v021_routes + _v02_routes +
    _legacy_routes
)
_unique_paths = {
    '/',
    '/search',
    '/customers/{customer_id}',
    '/health',
    '/customers/{customer_id}/payment-run',
    '/customers/{customer_id}/payment.txt',
    '/customers/{customer_id}/mail-template-v03',
    '/customers/{customer_id}/payment-mail-compose-v031',
    '/customers/{customer_id}/payment-mail-draft-v03',
}
_seen = set()
_final = []
for route in _ordered:
    path = getattr(route, 'path', None)
    if path in _unique_paths:
        key = (path, tuple(sorted(getattr(route, 'methods', set()))))
        if key in _seen:
            continue
        _seen.add(key)
    _final.append(route)
app.router.routes[:] = _final

# FastAPI validates ``customer_id: int`` only after a route has matched. A plain
# /customers/{customer_id} route can therefore capture the literal path
# /customers/new and return a 422 int_parsing error. Keep the public path name
# unchanged for compatibility, but constrain the active detail route at the
# Starlette matching layer so only decimal customer IDs can ever match it.
for _route in app.router.routes:
    if (
        getattr(_route, 'path', '') == '/customers/{customer_id}'
        and getattr(getattr(_route, 'endpoint', None), '__module__', '') == 'app.v0212_routes'
    ):
        _route.path_regex = re.compile(r'^/customers/(?P<customer_id>[0-9]+)$')
        break


def _assert_customer_new_route_guard():
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


def _assert_payment_review_route_guard():
    expected = {
        '/services/{service_id}/payment-current': 'payment_save_preserve_reviews_v032',
        '/services/{service_id}/payment-review-toggle': 'payment_review_toggle_preserve_reviews_v032',
    }
    for path, endpoint_name in expected.items():
        matches = [route for route in app.router.routes if getattr(route, 'path', '') == path and 'POST' in getattr(route, 'methods', set())]
        if not matches or getattr(getattr(matches[0], 'endpoint', None), '__name__', '') != endpoint_name:
            raise RuntimeError(f'v1.0 缴费路由自检失败：{path} 未由行级核对逻辑接管')


def _assert_payment_flow_v033_guard():
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


def _assert_v10_route_guard():
    expected = {
        ('GET', '/'): 'home_v10',
        ('GET', '/search'): 'global_search_v10',
        ('GET', '/work'): 'work_home_v10',
        ('GET', '/life'): 'life_home_v10',
        ('GET', '/life/recipes'): 'recipe_list_v10',
        ('GET', '/life/records'): 'cook_records_v10',
        ('GET', '/life/knowledge'): 'knowledge_list_v10',
    }
    for (method, path), endpoint_name in expected.items():
        matches = [r for r in app.router.routes if getattr(r, 'path', '') == path and method in getattr(r, 'methods', set())]
        if not matches or getattr(matches[0].endpoint, '__module__', '') != 'app.v10_routes' or getattr(matches[0].endpoint, '__name__', '') != endpoint_name:
            raise RuntimeError(f'v1.0 路由自检失败：{method} {path} 未由 v1.0 接管')


_assert_customer_new_route_guard()
_assert_payment_review_route_guard()
_assert_payment_flow_v033_guard()
_assert_v10_route_guard()


@app.on_event('startup')
def startup_v10():
    ensure_v10_schema()


app.title = f'晨的助手 v{config.APP_VERSION}'
app.version = config.APP_VERSION


@app.middleware('http')
async def current_asset_cache_policy(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith('/static/') and path.endswith(('.js', '.css', '.ps1')):
        response.headers['Cache-Control'] = 'no-store, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'

    if 'Content-Security-Policy' in response.headers:
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "style-src 'self'; style-src-elem 'self'; style-src-attr 'unsafe-inline'; "
            "script-src 'self'; img-src 'self' data: blob:; "
            "connect-src 'self' http://127.0.0.1:18763 http://localhost:18763; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
    return response
