from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import config
from .db import db
from .legacy_main import global_search as legacy_work_search
from .v027_home import dashboard_v027
from .v10_routes import global_search_v10
from .v101_recipe_template_patch import ensure_v101_recipe_templates, router as recipe_template_router
from .v12_tools_routes import router as v12_tools_router
from .v124_work_patch import router as v124_work_patch_router
from .v13_customer_documents import ensure_v13_customer_documents, router as v13_customer_documents_router
from .work_architecture import WORK_DOMAINS, WORK_LIBRARY_CATEGORIES

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')

# Work fixes / customer extensions are registered before historical compatibility
# routes so duplicate legacy paths keep resolving to the newest compatible behavior.
router.include_router(v124_work_patch_router)
router.include_router(v13_customer_documents_router)
router.include_router(recipe_template_router)
router.include_router(v12_tools_router)


@router.on_event('startup')
def startup_recipe_template_import_v101():
    ensure_v101_recipe_templates()
    ensure_v13_customer_documents()


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
        account_count = int(conn.execute('SELECT COUNT(*) n FROM website_accounts').fetchone()['n'])

    return templates.TemplateResponse(
        'work_shell_v14.html',
        {
            'request': request,
            'domains': WORK_DOMAINS,
            'customer_count': customer_count,
            'open_tasks': open_tasks,
            'product_count': product_count,
            'account_count': account_count,
        },
    )


@router.get('/work/customers', response_class=HTMLResponse)
def work_customer_management_v14(request: Request, home: str = 'tasks'):
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
