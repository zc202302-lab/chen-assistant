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

# 最新核心展示路由唯一；旧路由只保留当前仍在使用的 POST/action 能力。
_ordered = (
    _v029_routes + _v028_routes +
    _v027_home_routes + _v027_routes +
    _v026_home_routes + _v026_routes +
    _v025_home_routes + _v025_routes +
    _v024_routes + _v023_routes + _v022_routes + _v021_routes + _v02_routes +
    _legacy_routes
)
_unique_paths = {'/', '/customers/{customer_id}', '/health'}
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

app.title = '晨的助手 v0.2.10'
app.version = '0.2.10'


@app.middleware('http')
async def current_asset_cache_policy(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith('/static/') and path.endswith(('.js', '.css')):
        response.headers['Cache-Control'] = 'no-store, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'

    if 'Content-Security-Policy' in response.headers:
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "style-src 'self'; style-src-elem 'self'; style-src-attr 'unsafe-inline'; "
            "script-src 'self'; img-src 'self' data:; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
    return response
