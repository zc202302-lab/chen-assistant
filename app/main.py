from .legacy_main import app
from .v02_routes import router as v02_router
from .v021_routes import router as v021_router

# Keep legacy features, layer v0.2, then put v0.2.1 bugfix/UX routes first
# so duplicate paths resolve to the newest implementation.
_legacy_routes = list(app.router.routes)

_before = len(app.router.routes)
app.include_router(v02_router)
_v02_routes = app.router.routes[_before:]

_before = len(app.router.routes)
app.include_router(v021_router)
_v021_routes = app.router.routes[_before:]

app.router.routes[:] = _v021_routes + _v02_routes + _legacy_routes

app.title = '晨的助手 v0.2.1'
app.version = '0.2.1'
