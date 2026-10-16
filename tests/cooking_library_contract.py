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
    from types import SimpleNamespace
    with patch('app.cooking_library.import_book.subprocess.run',return_value=SimpleNamespace(stdout='eng\nosd\n')):
        try:
            import_pdf(blank,'magazines/blank.pdf','blank',ocr=True,ocr_engine='tesseract')
        except ValueError as error:
            assert 'chi_sim' in str(error)
        else:
            raise AssertionError('Chinese OCR must not silently fall back to English')
    with database() as conn:
        assert conn.execute('SELECT count(*) FROM books').fetchone()[0]==1
    with patch('app.cooking_library.import_book.subprocess.run',side_effect=[SimpleNamespace(stdout='chi_sim\neng\n'),SimpleNamespace(stdout='用盐2克，姜片5克。')]):
        ocr_id, created = import_pdf(blank,'magazines/blank.pdf','OCR样本',ocr=True,ocr_engine='tesseract')
        assert created
    with database() as conn:
        row = conn.execute('SELECT text,method FROM pages WHERE book_id=?',(ocr_id,)).fetchone()
        assert row['text']=='用盐2克，姜片5克。' and row['method']=='ocr:tesseract'
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
module_routes = route_inventory(mount.app)
module_sources = route_source_inventory(mount.app)
for rows in (module_routes,module_sources):
    for row in rows:
        row['path']='/cooking'+row['path']
repo_root=Path(__file__).resolve().parents[1]
assert module_routes == json.loads((repo_root/'docs/COOKING_RUNTIME_ROUTES.json').read_text())
assert module_sources == json.loads((repo_root/'docs/COOKING_RUNTIME_ROUTE_SOURCES.json').read_text())
print('optional module route and source inventories passed')

# Sidebar navigation only exposes the optional module when enabled; old assets unchanged.
from app.templating import Jinja2Templates
from starlette.requests import Request
templates = Jinja2Templates(directory=repo_root/'app/templates')
request=Request({'type':'http','path':'/','app':app,'headers':[]})
enabled=templates.TemplateResponse('base.html',{'request':request}).body.decode()
assert 'href="/cooking/"' in enabled
assert enabled.index('href="/cooking/"') > enabled.index('<dialog id="sidebar-navigation"')
assert enabled.index('href="/cooking/"') < enabled.index('</dialog>')
app.state.cooking_library_enabled=False
disabled=templates.TemplateResponse('base.html',{'request':request}).body.decode()
assert 'href="/cooking/"' not in disabled
app.state.cooking_library_enabled=True
print('optional cooking sidebar-navigation visibility passed')

# OCR preserves every returned line and raw geometry; column layout changes order only.
from app.cooking_library.ocr import reading_order, RapidReader
from types import SimpleNamespace

def box(x,y,text):
    return [[[x,y],[x+100,y],[x+100,y+15],[x,y+15]],text,.99]
lines=[[[[350,0],[650,0],[650,20],[350,20]],'标题',.99]]
for n in range(4):
    lines += [box(50,50+30*n,f'左{n}'),box(600,50+30*n,f'右{n}')]
ordered=reading_order(lines,1000)
assert [lines[i][1] for i in ordered]==['标题','左0','左1','左2','左3','右0','右1','右2','右3']
assert reading_order(lines[:2],1000)==[0,1]
with tempfile.TemporaryDirectory() as tmp:
    fake_engine=lambda *args,**kwargs:(lines,None)
    with patch.dict(sys.modules,{'rapidocr_onnxruntime':SimpleNamespace(RapidOCR=lambda **kwargs:fake_engine)}):
        text=RapidReader().read('unused.png',1000,Path(tmp)/'audit.json')
    payload=json.loads((Path(tmp)/'audit.json').read_text())
    assert payload['lines']==lines and sorted(payload['reading_order'])==list(range(len(lines)))
    assert text.startswith('标题\n左0\n左1')
print('OCR raw geometry and conservative column reading order passed')
