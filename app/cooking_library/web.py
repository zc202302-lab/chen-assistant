"""Read-only UI. All writes and OCR run in an explicit offline import process."""
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from app.templating import Jinja2Templates
from pathlib import Path
from .store import database, root, search

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / 'templates')


def create_app():
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def session_required(request: Request, call_next):
        # Parent middleware owns authentication. Never allow standalone unauthenticated use.
        if not getattr(request.state, 'session', None):
            return HTMLResponse('请先登录晨的小助手', status_code=401)
        try:
            return await call_next(request)
        except Exception:
            logging.getLogger(__name__).exception('Cooking library request failed')
            return HTMLResponse('厨艺资料库暂不可用，其他模块可继续使用。', status_code=503)

    @app.get('/style.css')
    def stylesheet():
        return FileResponse(Path(__file__).parent / 'style.css', media_type='text/css')

    @app.get('/reader.js')
    def reader_script():
        return FileResponse(Path(__file__).parent / 'reader.js', media_type='application/javascript')

    @app.get('/')
    def catalogue(request: Request, q: str = '', kind: str = ''):
        if kind not in {'','ebooks','magazines'}:
            raise HTTPException(400,'未知书刊类型')
        if len(q) > 100:
            raise HTTPException(400, '搜索词最多100字')
        with database() as conn:
            books = conn.execute("SELECT * FROM books WHERE (?='' OR kind=?) ORDER BY id DESC LIMIT 200",(kind,kind)).fetchall()
            hits = search(conn, q)
        return TEMPLATES.TemplateResponse('index.html', {'request': request, 'books': books, 'hits': hits[:100], 'more': len(hits)>100, 'q': q, 'kind':kind})

    @app.get('/books/{book_id}')
    def book_detail(request: Request, book_id: int):
        with database() as conn:
            book=conn.execute('SELECT * FROM books WHERE id=?',(book_id,)).fetchone()
            contents=conn.execute('SELECT * FROM book_contents WHERE book_id=? ORDER BY position',(book_id,)).fetchall()
        if not book:
            raise HTTPException(404,'书刊不存在')
        return TEMPLATES.TemplateResponse('book.html',{'request':request,'book':book,'contents':contents})

    @app.get('/books/{book_id}/pages/{page}')
    def page_view(request: Request, book_id: int, page: int):
        with database() as conn:
            contents=conn.execute('SELECT * FROM book_contents WHERE book_id=? ORDER BY position',(book_id,)).fetchall()
            row = conn.execute('SELECT b.title,b.pages,p.* FROM pages p JOIN books b ON b.id=p.book_id WHERE book_id=? AND page=?', (book_id,page)).fetchone()
        if not row:
            raise HTTPException(404, '未找到页面')
        return TEMPLATES.TemplateResponse('page.html', {'request': request, 'row': row, 'contents':contents})

    @app.get('/books/{book_id}/images/{page}')
    def page_image(book_id: int, page: int):
        if book_id < 1 or page < 1:
            raise HTTPException(404)
        with database() as conn:
            row = conn.execute('SELECT sha256 FROM books WHERE id=? AND pages>=?', (book_id,page)).fetchone()
        path = root() / 'previews' / row['sha256'] / f'{page}.jpg' if row else None
        if not path or not path.is_file():
            raise HTTPException(404, '原页预览尚未生成')
        return FileResponse(path, media_type='image/jpeg')

    return app
