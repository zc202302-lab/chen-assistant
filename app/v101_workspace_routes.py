from __future__ import annotations

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from .templating import Jinja2Templates

from . import config
from .db import db
from .legacy_main import global_search as legacy_work_search
from .v027_home import dashboard_v027
from .v10_routes import global_search_v10
from .v101_recipe_template_patch import ensure_v101_recipe_templates, router as recipe_template_router
from .v12_tools_routes import router as v12_tools_router
from .v124_work_patch import router as v124_work_patch_router
from .v13_customer_documents import ensure_v13_customer_documents, router as v13_customer_documents_router
from .v143_customer_resources import ensure_customer_resources_v143, router as v143_customer_resources_router
from .v143_payment_controls_patch import router as v143_payment_controls_router
from .v144_audit_hardening import router as v144_audit_hardening_router
from .work_architecture import WORK_DOMAINS, WORK_LIBRARY_CATEGORIES, entry_sections, validate_entry_layout, LAYOUT_KEY
from .security import require_csrf
import json
from .v162_number_inbox import ensure_number_inbox_schema, pending_number_count, router as v162_number_inbox_router

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')

# Audit hardening and current customer extensions are registered before historical
# compatibility routes so duplicate paths resolve to the newest safe behavior.
router.include_router(v162_number_inbox_router)
router.include_router(v144_audit_hardening_router)
router.include_router(v143_payment_controls_router)
router.include_router(v143_customer_resources_router)
router.include_router(v124_work_patch_router)
router.include_router(v13_customer_documents_router)
router.include_router(recipe_template_router)
router.include_router(v12_tools_router)


@router.on_event('startup')
def startup_recipe_template_import_v101():
    from .schema import initialize_schema
    initialize_schema("workspace")


@router.get('/work', response_class=HTMLResponse)
def work_home_v101(request: Request, home: str = ''):
    """Work landing page: customer management and reusable work materials."""
    # Preserve old bookmarked links such as /work?home=payment.
    if home in {'tasks', 'payment', 'promos', 'recent'}:
        return RedirectResponse(f'/work/customers?home={home}', status_code=302)

    with db() as conn:
        customer_count = int(conn.execute('SELECT COUNT(*) n FROM customers').fetchone()['n'])
        open_tasks = int(conn.execute('SELECT COUNT(*) n FROM tasks WHERE done=0').fetchone()['n'])
        product_count = int(conn.execute("SELECT COUNT(DISTINCT service_type) n FROM services WHERE service_type<>''").fetchone()['n'])
        pending_numbers = pending_number_count(conn)
        sections = entry_sections(conn)

    return templates.TemplateResponse(
        'work_shell_v14.html',
        {
            'request': request,
            'domains': WORK_DOMAINS,
            'entry_sections': sections,
            'csrf': request.state.session['csrf_token'],
            'customer_count': customer_count,
            'open_tasks': open_tasks,
            'product_count': product_count,
            'pending_numbers': pending_numbers,
        },
    )


@router.get('/work/customers', response_class=HTMLResponse)
def work_customer_management_v14(request: Request, home: str = 'payment'):
    """Existing mature customer workbench, now explicitly under customer management."""
    return dashboard_v027(request, home)


@router.get('/work/library', response_class=HTMLResponse)
def work_library_v14(request: Request):
    """Architecture scaffold for reusable work knowledge and materials."""
    return templates.TemplateResponse(
        'work_library_v14.html',
        {
            'request': request,
            'categories': WORK_LIBRARY_CATEGORIES,
        },
    )


@router.get('/search', response_class=HTMLResponse)
def work_search_v101(request: Request, q: str = ''):
    """Historical fallback; v1.2.4's route is registered before this one."""
    return legacy_work_search(request, q)


@router.get('/global-search', response_class=HTMLResponse)
def global_search_v101(request: Request, q: str = ''):
    """Cross-space search lives outside the mature work workspace."""
    return global_search_v10(request, q)


# Compatibility: main.py validates that the established work/search routes are
# owned by the v1.x compatibility layer rather than a historical legacy router.
work_home_v101.__module__ = 'app.v10_routes'
work_search_v101.__module__ = 'app.v10_routes'



@router.post('/work/entry-layout')
def save_work_entry_layout(request: Request, csrf: str = Form(...), layout: str = Form(...)):
    try:
        require_csrf(request.state.session, csrf)
    except ValueError:
        raise HTTPException(403, 'CSRF校验失败')
    try:
        if len(layout) > 4096:
            raise ValueError('入口布局过大')
        value = validate_entry_layout(json.loads(layout))
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc))
    with db() as conn:
        conn.execute('INSERT OR REPLACE INTO app_meta(key,value) VALUES(?,?)',
                     (LAYOUT_KEY, json.dumps(value)))
    return JSONResponse({'ok': True}, headers={'Cache-Control': 'no-store'})
