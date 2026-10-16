"""Exercise isolated import, Chinese retrieval, auth and failure boundaries."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fitz
from fastapi.testclient import TestClient
from fastapi import FastAPI

with tempfile.TemporaryDirectory() as tmp:
    os.environ['APP_DB_PATH'] = str(Path(tmp)/'business.db')
    os.environ['COOKING_LIBRARY_DIR'] = str(Path(tmp)/'library')
    from app.cooking_library.store import database, search, root
    from app.cooking_library.import_book import import_pdf
    from app.cooking_library.web import create_app
    pdf = Path(tmp)/'book.pdf'
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((40,60),'Fish soup recipe: use fish, ginger, water. Simmer gently.')
        doc.save(pdf)
    book_id,created = import_pdf(pdf,'ebooks/book.pdf','测试<script>书')
    assert created
    assert import_pdf(pdf,'ebooks/book.pdf','重复') == (book_id,False)
    with database() as conn:
        conn.execute('UPDATE pages SET text=? WHERE book_id=?',('鱼锅泡饼：姜片去腥，用盐2克。',book_id))
        conn.execute('UPDATE page_search SET text=? WHERE book_id=?',('鱼锅泡饼：姜片去腥，用盐2克。',book_id))
    with database() as conn:
        assert search(conn,'鱼锅泡饼')[0]['page']==1
        assert search(conn,'去腥')[0]['id']==book_id
        assert search(conn,'" OR "') == []
    client = TestClient(create_app())
    assert client.get('/').status_code==401
    outer = FastAPI()
    @outer.middleware('http')
    async def session(request,call_next):
        request.state.session={'csrf_token':'test'}
        return await call_next(request)
    outer.mount('/cooking',create_app())
    with TestClient(outer) as client:
        response=client.get('/cooking/?q=鱼锅泡饼')
        assert response.status_code==200 and 'PDF第1页' in response.text
        assert '<script>书' not in response.text and '&lt;script&gt;' in response.text
        assert client.get(f'/cooking/books/{book_id}/pages/1').status_code==200
        assert client.get(f'/cooking/books/{book_id}/images/1').headers['content-type']=='image/jpeg'
        assert client.get('/cooking/books/999/images/1').status_code==404
        assert client.get('/cooking/?q='+'鱼'*101).status_code==400
        assert client.get('/cooking/style.css').status_code==200
        with patch('app.cooking_library.web.database',side_effect=OSError('unavailable')):
            assert client.get('/cooking/').status_code==503
    blank = Path(tmp)/'blank.pdf'
    with fitz.open() as doc:
        doc.new_page();doc.save(blank)
    try:
        import_pdf(blank,'magazines/blank.pdf','blank')
    except ValueError as error:
        assert 'OCR' in str(error)
    else:
        raise AssertionError('image-only input must not silently enter catalogue')
    with database() as conn:
        assert conn.execute('SELECT count(*) FROM books').fetchone()[0]==1
    assert not Path(os.environ['APP_DB_PATH']).exists(), 'import must not touch business DB'
print('cooking library isolation/import/search/auth/preview contract passed')

# Real assistant integration: only one additive mount, all old owners stay intact.
with tempfile.TemporaryDirectory() as tmp:
    os.environ['APP_DB_PATH'] = str(Path(tmp)/'business.db')
    os.environ['COOKING_LIBRARY_DIR'] = str(Path(tmp)/'library')
    os.environ['COOKING_LIBRARY_ENABLED'] = '1'
    from app.main import app
    from app.routing import route_inventory, route_source_inventory
    import json
    mount = app.routes[-1]
    assert mount.path == '/cooking' and mount.name == 'cooking_library'
    assert route_inventory(app)[-1] == {'path':'/cooking','methods':[],'module':'','name':''}
    assert route_source_inventory(app)[-1] == {'path':'/cooking','methods':[],'source':None,'qualname':None}
    original_inventory = json.loads((Path(__file__).resolve().parents[1]/'docs/RUNTIME_ROUTES.json').read_text())
    actual = route_inventory(app)[:-1]
    known = {(r['path'],tuple(r['methods'])) for r in original_inventory}
    assert [r for r in actual if (r['path'],tuple(r['methods'])) in known] == original_inventory
    client = TestClient(app)
    assert client.get('/cooking/',follow_redirects=False).status_code == 303
    with patch('app.legacy_main.get_session',return_value={'csrf_token':'test'}):
        assert client.get('/cooking/').status_code==200
        with patch('app.cooking_library.web.database',side_effect=OSError('unavailable')), patch('app.cooking_library.web.logging.getLogger'):
            assert client.get('/cooking/').status_code==503
            assert client.get('/health').status_code==200
    assert not Path(os.environ['COOKING_LIBRARY_DIR']).joinpath('business.db').exists()
print('real assistant mount/auth/failure boundary passed')
