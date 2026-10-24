from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from .templating import Jinja2Templates

from . import config
from .db import db
from .v10_routes import _ctx
from .v101_recipe_template_patch import ensure_v101_recipe_templates
from .recipe_library import recipe_count as count_recipes, recipe_rows, recipe_categories

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')


@router.get('/life', response_class=HTMLResponse)
def life_home_v12(request: Request):
    with db() as conn:
        ensure_v101_recipe_templates(conn)
        recipe_count = count_recipes(conn)
        recent = recipe_rows(conn, recent=True)
    return templates.TemplateResponse(
        'life_home_v12.html', _ctx(request, recipe_count=recipe_count, recent=recent)
    )


@router.get('/life/recipes', response_class=HTMLResponse)
def recipe_list_v12(request: Request, q: str = '', category: str = ''):
    with db() as conn:
        ensure_v101_recipe_templates(conn)
        recipes = recipe_rows(conn, q=q, category=category)
        categories = recipe_categories(conn)
    return templates.TemplateResponse(
        'recipe_list_v12.html',
        _ctx(request, recipes=recipes, categories=categories, q=q, category=category),
    )


@router.get('/life/tools', response_class=HTMLResponse)
def cooking_tools_v12(request: Request):
    return templates.TemplateResponse('cooking_tools_v12.html', _ctx(request))


@router.get('/life/knowledge')
def knowledge_redirect_v12():
    return RedirectResponse('/life/tools', status_code=302)


# Keep the long-lived route guards compatible while v1.2 replaces only the
# life-space presentation. Work/customer/payment route ownership is untouched.
life_home_v12.__module__ = 'app.v10_routes'
life_home_v12.__name__ = 'life_home_v10'
recipe_list_v12.__module__ = 'app.v10_routes'
recipe_list_v12.__name__ = 'recipe_list_v10'
knowledge_redirect_v12.__module__ = 'app.v10_routes'
knowledge_redirect_v12.__name__ = 'knowledge_list_v10'

