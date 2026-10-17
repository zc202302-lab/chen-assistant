"""Real desktop/mobile navigation, using isolated data and synthetic authentication."""
from pathlib import Path
import os
import socket
import sys
import tempfile
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI,Request
from fastapi.staticfiles import StaticFiles
from app.templating import Jinja2Templates
from playwright.sync_api import sync_playwright
import uvicorn

ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as tmp:
    os.environ['COOKING_LIBRARY_DIR']=str(Path(tmp)/'library')
    from app.cooking_library.store import database, root
    # Synthetic three-page book: no customer data, no OCR dependency.
    import base64
    jpeg=base64.b64decode('/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAgP/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCdAAf/2Q==')
    with database() as conn:
        conn.execute("INSERT INTO books VALUES(1,'测试样刊','magazines','magazines/test.pdf',?,3)",('a'*64,))
        for n in range(1,4):
            conn.execute("INSERT INTO pages VALUES(1,?,'','image')",(n,))
        conn.execute("INSERT INTO book_contents VALUES(1,1,'P8 测试章节',2,1)")
    folder=root()/'previews'/('a'*64);folder.mkdir(parents=True)
    for n in range(1,4):(folder/f'{n}.jpg').write_bytes(jpeg)
    from app.cooking_library.web import create_app
    app=FastAPI()
    app.state.cooking_library_enabled=True
    templates=Jinja2Templates(directory=ROOT/'app/templates')
    @app.middleware('http')
    async def session(request,call_next):
        request.state.session={'csrf_token':'test-only'}
        response=await call_next(request)
        response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:"
        return response
    @app.get('/')
    def home(request:Request):
        return templates.TemplateResponse('base.html',{'request':request})
    app.mount('/static',StaticFiles(directory=ROOT/'app/static'))
    app.mount('/cooking',create_app())
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.05)
    assert server.started
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True)
            for width in [320,390,768,1440]:
                page=browser.new_page(viewport={'width':width,'height':900})
                page.goto(f'http://127.0.0.1:{port}/')
                nav=page.get_by_role('navigation',name='主区域导航',exact=True)
                assert nav.get_by_role('link').all_text_contents()==['首页','工作','资料']
                boxes=[nav.bounding_box(),page.locator('.topbar-actions').bounding_box(),page.locator('.topbar-left').bounding_box()]
                for box in boxes:
                    assert box and box['x']>=0 and box['x']+box['width']<=width+1,(width,boxes)
                menu=page.get_by_role('dialog',name='侧边导航')
                assert not menu.is_visible()
                page.get_by_role('button',name='打开侧边导航').click()
                cooking=menu.get_by_role('link',name='厨艺资料库')
                assert cooking.is_visible()
                cooking.click()
                page.wait_for_url('**/cooking/')
                assert page.get_by_role('heading',name='厨艺资料库',exact=True).is_visible()
                page.get_by_label('打开菜单').click()
                assert page.get_by_role('navigation',name='其他空间').get_by_role('link',name='厨艺资料库').get_attribute('aria-current')=='page'
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),width
                page.goto(f'http://127.0.0.1:{port}/cooking/?kind=magazines')
                page.get_by_role('link',name='测试样刊',exact=True).click()
                assert page.get_by_role('heading',name='书刊目录').is_visible()
                page.get_by_role('link',name='P8 测试章节 PDF 2').click()
                page.wait_for_url('**/pages/2')
                page.get_by_role('button',name='放大',exact=True).click()
                assert page.locator('#zoom-label').inner_text()=='125%'
                page.get_by_role('button',name='适合宽度').click()
                assert page.locator('#zoom-label').inner_text()=='100%'
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),width
                page.get_by_label('页码',exact=True).fill('3')
                page.get_by_role('button',name='前往',exact=True).click()
                page.wait_for_url('**/pages/3')
                page.reload()
                assert page.get_by_role('link',name='下一页',exact=True).count()==0
                page.get_by_role('link',name='返回书刊详情').click()
                page.get_by_role('link',name='继续阅读',exact=True).click()
                page.wait_for_url('**/pages/3')
                page.close()
            browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=10)
print('cooking navigation desktop/mobile 320/390/768/1440 click-through passed')
