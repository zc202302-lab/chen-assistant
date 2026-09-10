import re

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
from . import v031_fixed_review_patch as _v031_fixed_review_patch  # noqa: F401

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
_v032_customer_import_routes = _include(v032_customer_import_router)

# v0.3.2 owns customer creation/import. v0.3.1 continues to own the mature
# four-stage payment workflow while the stable v0.2.12 customer workspace
# remains the renderer.
_ordered = (
    _v032_customer_import_routes + _v031_payment_workflow_routes +
    _v03_mail_draft_routes + _v031_runtime_routes + _v03_payment_routes + _v03_routes +
    _v0212_business_display_routes + _v0212_payment_routes + _v0212_routes +
    _v0211_promotion_routes + _v0211_routes + _v029_routes + _v028_routes +
    _v027_home_routes + _v027_routes +
    _v026_home_routes + _v026_routes +
    _v025_home_routes + _v025_routes +
    _v024_routes + _v023_routes + _v022_routes + _v021_routes + _v02_routes +
    _legacy_routes
)
_unique_paths = {'/', '/customers/{customer_id}', '/health', '/customers/{customer_id}/payment-run'}
_seen = set()
_final = []
for route in _ordered:
    path = getattr(route, 'path', None)
    if path in _unique_paths:
        if path in _seen:
            continue
        _seen.add(path)
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

app.title = '晨的助手 v0.3.2'
app.version = '0.3.2'


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
