"""Reading imports do not require OCR; TOC targets are actual PDF pages."""
import os
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fitz
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.cooking_library.import_book import import_pdf
from app.cooking_library.contents import replace_contents
from app.cooking_library.store import database
from app.cooking_library.web import create_app

with tempfile.TemporaryDirectory() as tmp:
    os.environ['COOKING_LIBRARY_DIR']=str(Path(tmp)/'library')
    os.environ['APP_DB_PATH']=str(Path(tmp)/'business.sqlite3')
    source=Path(tmp)/'image.pdf'
    with fitz.open() as doc:
        for _ in range(3):doc.new_page()
        doc.set_toc([[1,'P8 开篇',2],[2,'配方<script>',3]])
        doc.save(source)
    book_id,created=import_pdf(source,'magazines/reading.pdf','阅读样刊',reading_only=True)
    assert created
    with database() as conn:
        assert [r['page'] for r in conn.execute('SELECT page FROM book_contents ORDER BY position')]==[2,3]
        assert conn.execute('SELECT count(*) FROM pages WHERE method="image"').fetchone()[0]==3
    try:replace_contents(book_id,[{'title':'错误','page':4}])
    except ValueError:pass
    else:raise AssertionError('out-of-range page accepted')
    with database() as conn:assert conn.execute('SELECT count(*) FROM book_contents').fetchone()[0]==2
    app=FastAPI()
    @app.middleware('http')
    async def session(request,call_next):
        request.state.session={'csrf_token':'test'}
        return await call_next(request)
    app.mount('/cooking',create_app())
    with TestClient(app) as client:
        listing=client.get('/cooking/?kind=magazines')
        assert '阅读样刊' in listing.text and f'href="/cooking/books/{book_id}"' in listing.text
        assert '阅读样刊' not in client.get('/cooking/?kind=ebooks').text
        detail=client.get(f'/cooking/books/{book_id}')
        assert 'P8 开篇' in detail.text and f'/pages/2' in detail.text
        assert '&lt;script&gt;' in detail.text and '<script>' not in detail.text
        assert client.get('/cooking/books/999').status_code==404
        assert client.get('/cooking/?kind=bogus').status_code==400
        for page in [0,4]:assert client.get(f'/cooking/books/{book_id}/pages/{page}').status_code==404
        reader=client.get(f'/cooking/books/{book_id}/pages/2')
        assert reader.status_code==200 and '章节目录' in reader.text and '查看文字' not in reader.text
        assert 'reader.js' in reader.text
        assert client.get('/cooking/reader.js').status_code==200
        assert client.get(f'/cooking/books/{book_id}/images/3').status_code==200
    assert not Path(os.environ['APP_DB_PATH']).exists()
print('reading-only import, bookmarks, atomic TOC validation, types, reader and old DB isolation passed')
