"""Application lifecycle and HTTP policy. Runtime routes live in app.routing."""
import asyncio
import logging
from . import config
from .legacy_main import app
from .reminders import ensure_reminder_schema, worker as reminder_worker
from .security import configured
from .routing import configure_routes
from .v10_routes import ensure_v10_schema
from .work_list_import import ensure_work_list_import_schema
from .work_lists import ensure_work_lists_schema
from .v160_information_center import ensure_v160_schema

configure_routes(app)


@app.on_event('startup')
def startup_v10():
    from .schema import initialize_schema
    initialize_schema("runtime")


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
            "connect-src 'self' http://127.0.0.1:18763 http://localhost:18763 http://127.0.0.1:18764; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
    return response




@app.on_event('startup')
async def start_reminder_worker():
    app.state.reminder_error = None
    if not configured():
        app.state.reminder_error = '请先完成应用安全配置'
        return
    try:
        ensure_reminder_schema()
    except Exception:
        # An optional notification feature must not stop the existing website.
        # Keep encrypted secrets protected; report unavailable instead of falling
        # back to plaintext or replacing an existing key.
        app.state.reminder_error = '手机推送初始化失败，请检查服务器安全配置与数据库'
        logging.getLogger(__name__).exception('Reminder initialization failed; existing site remains available')
        return
    app.state.reminder_stop = asyncio.Event()
    app.state.reminder_worker = asyncio.create_task(reminder_worker(app.state.reminder_stop))


@app.on_event('shutdown')
async def stop_reminder_worker():
    if hasattr(app.state, 'reminder_worker'):
        app.state.reminder_stop.set()
        await app.state.reminder_worker

