from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .legacy_main import global_search as legacy_work_search
from .v027_home import dashboard_v027
from .v10_routes import global_search_v10
from .v101_recipe_template_patch import ensure_v101_recipe_templates, router as recipe_template_router
from .v12_tools_routes import router as v12_tools_router
from .v124_work_patch import router as v124_work_patch_router
from .v13_customer_documents import ensure_v13_customer_documents, router as v13_customer_documents_router

router = APIRouter()
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
def work_home_v101(request: Request, home: str = 'tasks'):
    """The work workspace is the mature pre-v1.0 dashboard, unchanged in behavior."""
    return dashboard_v027(request, home)


@router.get('/search', response_class=HTMLResponse)
def work_search_v101(request: Request, q: str = ''):
    """Historical fallback; v1.2.4's route is registered before this one."""
    return legacy_work_search(request, q)


@router.get('/global-search', response_class=HTMLResponse)
def global_search_v101(request: Request, q: str = ''):
    """Cross-space search lives outside the mature work workspace."""
    return global_search_v10(request, q)


work_home_v101.__module__ = 'app.v10_routes'
work_search_v101.__module__ = 'app.v10_routes'
