from .legacy_main import app
from .v02_routes import router as v02_router

# v0.2 uses a small compatibility wrapper: keep all legacy routes/features,
# then place the payment-first v0.2 overrides before duplicate legacy routes.
_before = len(app.router.routes)
app.include_router(v02_router)
_v02_routes = app.router.routes[_before:]
_legacy_routes = app.router.routes[:_before]
app.router.routes[:] = _v02_routes + _legacy_routes

app.title = '晨的助手 v0.2'
app.version = '0.2'
