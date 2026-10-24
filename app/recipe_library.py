"""One visibility policy for imported standards and user-created recipes."""
from .v101_recipe_template_data import TEMPLATE_IMPORT_MARKER


VISIBLE_RECIPES = '''r.archived=0 AND (
    r.source='manual' OR EXISTS (
        SELECT 1 FROM recipe_versions imported
        WHERE imported.recipe_id=r.id AND imported.change_summary LIKE ?
    )
)'''
PARAMETERS = (f'{TEMPLATE_IMPORT_MARKER}%',)


def recipe_count(conn):
    return int(conn.execute('SELECT COUNT(*) n FROM recipes r WHERE ' + VISIBLE_RECIPES, PARAMETERS).fetchone()['n'])


def recipe_rows(conn, q='', category='', recent=False):
    sql = '''SELECT r.*,current.version_no FROM recipes r
             LEFT JOIN recipe_versions current ON current.id=r.current_version_id
             WHERE ''' + VISIBLE_RECIPES
    args = list(PARAMETERS)
    if q.strip():
        sql += ' AND (r.name LIKE ? OR r.tags LIKE ? OR r.description LIKE ?)'
        args.extend([f'%{q.strip()}%'] * 3)
    if category.strip():
        sql += ' AND r.category=?'
        args.append(category.strip())
    sql += ' ORDER BY r.updated_at DESC,r.name LIMIT 8' if recent else ' ORDER BY r.category,r.name'
    return conn.execute(sql, args).fetchall()


def recipe_categories(conn):
    return [row['category'] for row in conn.execute(
        'SELECT DISTINCT r.category FROM recipes r WHERE ' + VISIBLE_RECIPES + " AND r.category<>'' ORDER BY r.category",
        PARAMETERS).fetchall()]
