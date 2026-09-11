from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .legacy_main import global_search as legacy_work_search
from .v027_home import dashboard_v027
from .v10_routes import global_search_v10

router = APIRouter()


@router.get('/work', response_class=HTMLResponse)
def work_home_v101(request: Request, home: str = 'tasks'):
    """The work workspace is the mature pre-v1.0 dashboard, unchanged in behavior."""
    return dashboard_v027(request, home)


@router.get('/search', response_class=HTMLResponse)
def work_search_v101(request: Request, q: str = ''):
    """Keep the original work-only search at its historical /search path."""
    return legacy_work_search(request, q)


@router.get('/global-search', response_class=HTMLResponse)
def global_search_v101(request: Request, q: str = ''):
    """Cross-space v1.0 search lives outside the mature work workspace."""
    return global_search_v10(request, q)
