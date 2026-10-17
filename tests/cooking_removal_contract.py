"""Removed book library must not mount, even with stale production settings."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient

with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)/'retained-library'
    root.mkdir()
    sentinel=root/'catalogue.sqlite3'
    sentinel.write_bytes(b'existing-private-library-data')
    preview=root/'previews'/'existing.jpg';preview.parent.mkdir();preview.write_bytes(b'private-preview')
    before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    os.environ['APP_DB_PATH']=str(Path(tmp)/'business.sqlite3')
    os.environ['COOKING_LIBRARY_ENABLED']='1'
    os.environ['COOKING_LIBRARY_DIR']=str(root)
    from app.main import app
    assert not any(getattr(route,'path','').startswith('/cooking') for route in app.routes)
    assert not any(name.startswith('app.cooking_library') for name in sys.modules)
    # No module may initialize or delete the retained private library.
    with TestClient(app) as client:
        assert client.get('/health').status_code==200
        assert client.get('/cooking/',follow_redirects=False).status_code==303
        with patch('app.legacy_main.get_session',return_value={'csrf_token':'test'}):
            for path in ['/cooking/','/cooking/books/1','/cooking/books/1/images/1','/cooking/reader.js']:
                assert client.get(path).status_code==404,path
            response=client.get('/')
            assert response.status_code==200
            assert 'href="/cooking/' not in response.text
            assert '厨艺资料库' not in response.text
    assert {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}==before
    from app.templating import Jinja2Templates
    from starlette.requests import Request
    app.state.cooking_library_enabled=True
    request=Request({'type':'http','path':'/','app':app,'headers':[]})
    body=Jinja2Templates(directory=Path(__file__).resolve().parents[1]/'app/templates').TemplateResponse('base.html',{'request':request}).body.decode()
    assert '/cooking/' not in body and '厨艺资料库' not in body
    assert all(label in body for label in ['>首页</a>','>工作</a>','>资料</a>','>生活</a>'])
print('removed library: no route/menu/import; stale flag harmless; private files byte-identical; old navigation/health remain')
