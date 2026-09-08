from .legacy_main import app
from .v02_routes import router as v02_router
from .v021_routes import router as v021_router
from .v022_routes import router as v022_router
from .v023_routes import router as v023_router
from .v024_routes import router as v024_router
from .v025_routes import router as v025_router

_legacy_routes = list(app.router.routes)

_before = len(app.router.routes)
app.include_router(v02_router)
_v02_routes = app.router.routes[_before:]

_before = len(app.router.routes)
app.include_router(v021_router)
_v021_routes = app.router.routes[_before:]

_before = len(app.router.routes)
app.include_router(v022_router)
_v022_routes = app.router.routes[_before:]

_before = len(app.router.routes)
app.include_router(v023_router)
_v023_routes = app.router.routes[_before:]

_before = len(app.router.routes)
app.include_router(v024_router)
_v024_routes = app.router.routes[_before:]

_before = len(app.router.routes)
app.include_router(v025_router)
_v025_routes = app.router.routes[_before:]

# Newest routes first. v0.2.5 owns the customer workspace, payment lifecycle,
# payment schedule editing, promotions and /health. v0.2.4 still owns the new homepage.
app.router.routes[:] = _v025_routes + _v024_routes + _v023_routes + _v022_routes + _v021_routes + _v02_routes + _legacy_routes

app.title = '晨的助手 v0.2.5'
app.version = '0.2.5'
