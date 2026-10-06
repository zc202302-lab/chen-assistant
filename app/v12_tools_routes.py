from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from .templating import Jinja2Templates

from . import config
from .db import db
from .v10_routes import _ctx
from .v101_recipe_template_data import TEMPLATE_IMPORT_MARKER
from .v101_recipe_template_patch import ensure_v101_recipe_templates

router = APIRouter()
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')


@router.get('/life', response_class=HTMLResponse)
def life_home_v12(request: Request):
    with db() as conn:
        ensure_v101_recipe_templates(conn)
        recipe_count = int(conn.execute(
            '''SELECT COUNT(DISTINCT r.id) n
               FROM recipes r JOIN recipe_versions rv ON rv.recipe_id=r.id
               WHERE r.archived=0 AND rv.change_summary LIKE ?''',
            (f'{TEMPLATE_IMPORT_MARKER}%',),
        ).fetchone()['n'])
        recent = conn.execute(
            '''SELECT DISTINCT r.id,r.name,r.category,r.updated_at
               FROM recipes r JOIN recipe_versions rv ON rv.recipe_id=r.id
               WHERE r.archived=0 AND rv.change_summary LIKE ?
               ORDER BY r.updated_at DESC,r.name LIMIT 8''',
            (f'{TEMPLATE_IMPORT_MARKER}%',),
        ).fetchall()
    return templates.TemplateResponse(
        'life_home_v12.html', _ctx(request, recipe_count=recipe_count, recent=recent)
    )


@router.get('/life/recipes', response_class=HTMLResponse)
def recipe_list_v12(request: Request, q: str = '', category: str = ''):
    with db() as conn:
        ensure_v101_recipe_templates(conn)
        sql = '''SELECT DISTINCT r.*, current.version_no
                 FROM recipes r
                 JOIN recipe_versions imported ON imported.recipe_id=r.id
                 LEFT JOIN recipe_versions current ON current.id=r.current_version_id
                 WHERE r.archived=0 AND imported.change_summary LIKE ?'''
        args = [f'{TEMPLATE_IMPORT_MARKER}%']
        if q.strip():
            sql += ' AND r.name LIKE ?'; args.append(f'%{q.strip()}%')
        if category.strip():
            sql += ' AND r.category=?'; args.append(category.strip())
        sql += ' ORDER BY r.category,r.name'
        recipes = conn.execute(sql, args).fetchall()
        categories = [row['category'] for row in conn.execute(
            '''SELECT DISTINCT r.category
               FROM recipes r JOIN recipe_versions rv ON rv.recipe_id=r.id
               WHERE r.archived=0 AND rv.change_summary LIKE ? AND r.category<>''
               ORDER BY r.category''',
            (f'{TEMPLATE_IMPORT_MARKER}%',),
        ).fetchall()]
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

