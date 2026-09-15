from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = tempfile.TemporaryDirectory(prefix='chen-v144-http-')
os.environ.update({
    'APP_DB_PATH': str(Path(TMP.name) / 'app.db'),
    'APP_USERNAME': 'audit-http',
    'APP_PASSWORD_SALT': 'dGVzdHNhbHQ=',
    'APP_PASSWORD_HASH': 'x',
    'APP_SESSION_SECRET': 'v144-http-session',
    'APP_ENCRYPTION_KEY': 'x',
    'APP_SECURE_COOKIE': '0',
})

from app.db import db, init_db  # noqa: E402
from app.main import app  # noqa: F401,E402
from app.security import create_session  # noqa: E402
from app.v10_routes import ensure_v10_schema  # noqa: E402


def wait_http(url: str):
    for _ in range(100):
        try:
            if urllib.request.urlopen(url, timeout=1).status == 200:
                return
        except Exception:
            pass
        time.sleep(.2)
    raise RuntimeError('server start failed')


def main():
    init_db()
    ensure_v10_schema()
    with db() as conn:
        recipes = conn.execute(
            'SELECT id,name,current_version_id FROM recipes WHERE archived=0 ORDER BY id LIMIT 2'
        ).fetchall()
        knowledge = conn.execute('SELECT id,title FROM cooking_knowledge ORDER BY id LIMIT 2').fetchall()
        assert len(recipes) >= 2 and len(knowledge) >= 2
        recipe_id = int(recipes[0]['id'])
        recipe_original_name = recipes[0]['name']
        duplicate_recipe_name = recipes[1]['name']
        original_version_count = int(conn.execute(
            'SELECT COUNT(*) n FROM recipe_versions WHERE recipe_id=?', (recipe_id,)
        ).fetchone()['n'])
        knowledge_id = int(knowledge[0]['id'])
        original_knowledge_title = knowledge[0]['title']
        duplicate_knowledge_title = knowledge[1]['title']

    token, csrf, _ = create_session()
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8160'],
        cwd=ROOT,
        env=os.environ.copy(),
    )
    try:
        wait_http('http://127.0.0.1:8160/health')
        with httpx.Client(
            base_url='http://127.0.0.1:8160',
            cookies={'session_token': token},
            follow_redirects=False,
            timeout=10,
        ) as client:
            for bad in ('nan', 'inf', '-inf', '0', '-1'):
                response = client.post('/life/recipes/new', data={
                    'csrf': csrf,
                    'name': f'非法重量-{bad}',
                    'base_amount': bad,
                    'base_unit': 'g',
                })
                assert response.status_code == 400, (bad, response.status_code, response.text)

            response = client.post(f'/life/recipes/{recipe_id}/edit', data={
                'csrf': csrf,
                'name': duplicate_recipe_name,
                'base_amount': '500',
                'base_unit': 'g',
                'change_summary': 'duplicate-name-audit',
            })
            assert response.status_code == 409, (response.status_code, response.text)

            response = client.post(f'/life/recipes/{recipe_id}/edit', data={
                'csrf': csrf,
                'name': recipe_original_name,
                'base_amount': '500',
                'base_unit': 'g',
                'ingredient_name': ['测试配料'],
                'ingredient_amount': ['inf'],
                'ingredient_unit': ['g'],
            })
            assert response.status_code == 400, (response.status_code, response.text)

            response = client.post('/life/knowledge/new', data={
                'csrf': csrf,
                'title': duplicate_knowledge_title,
                'category': '审计',
                'content': 'duplicate-title-audit',
            })
            assert response.status_code == 409, (response.status_code, response.text)

            response = client.post(f'/life/knowledge/{knowledge_id}/edit', data={
                'csrf': csrf,
                'title': duplicate_knowledge_title,
                'category': '审计',
                'content': 'duplicate-title-audit',
            })
            assert response.status_code == 409, (response.status_code, response.text)

        with db() as conn:
            recipe = conn.execute('SELECT name FROM recipes WHERE id=?', (recipe_id,)).fetchone()
            assert recipe and recipe['name'] == recipe_original_name
            version_count = int(conn.execute(
                'SELECT COUNT(*) n FROM recipe_versions WHERE recipe_id=?', (recipe_id,)
            ).fetchone()['n'])
            assert version_count == original_version_count
            item = conn.execute('SELECT title FROM cooking_knowledge WHERE id=?', (knowledge_id,)).fetchone()
            assert item and item['title'] == original_knowledge_title
            assert conn.execute('SELECT COUNT(*) n FROM recipes WHERE name LIKE ?', ('非法重量-%',)).fetchone()['n'] == 0

        print('v1.4.4 audit HTTP acceptance passed: invalid numbers and duplicate names are rejected without mutation')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
