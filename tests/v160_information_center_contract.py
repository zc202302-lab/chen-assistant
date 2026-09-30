from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    routes = (ROOT / 'app' / 'v160_information_center.py').read_text(encoding='utf-8')
    main_py = (ROOT / 'app' / 'main.py').read_text(encoding='utf-8')
    base = (ROOT / 'app' / 'templates' / 'base.html').read_text(encoding='utf-8')
    work = (ROOT / 'app' / 'templates' / 'work_shell_v14.html').read_text(encoding='utf-8')
    center = (ROOT / 'app' / 'templates' / 'information_center_v160.html').read_text(encoding='utf-8')
    search = (ROOT / 'app' / 'templates' / 'search_v10.html').read_text(encoding='utf-8')
    work_search = (ROOT / 'app' / 'templates' / 'search.html').read_text(encoding='utf-8')
    work_patch = (ROOT / 'app' / 'v124_work_patch.py').read_text(encoding='utf-8')
    config = (ROOT / 'app' / 'config.py').read_text(encoding='utf-8')

    assert 'CREATE TABLE IF NOT EXISTS information_records' in routes
    assert 'body_enc TEXT NOT NULL' in routes
    assert 'encrypt_secret(' in routes
    assert 'decrypt_secret(' in routes
    assert "@router.get('/info'" in routes
    assert "@router.get('/info/new'" in routes
    assert "@router.post('/info/new')" in routes
    assert "@router.get('/info/{record_id}'" in routes
    assert "@router.post('/info/{record_id}/edit')" in routes
    assert "@router.post('/info/{record_id}/archive')" in routes
    assert '_v160_information_center_routes +' in main_py

    assert "{% set _is_info" in base
    assert 'href="/info"' in base and '>资料</a>' in base
    assert "_path.startswith('/accounts')" in base
    assert 'information-center-v160.css?v=1600' in base
    assert 'work-architecture-v14.css?v=1400">\\n' not in base, 'literal newline must not render above the header'
    assert '网站 / 平台账户' not in work
    assert '账户密码仍保留为专用子功能，不再属于工作模块。' in center
    assert 'href="/accounts"' in center
    assert '<h2>资料 <small>{{ information|length }}</small></h2>' in search
    assert '网址账户' not in work_search
    assert '网站账户' not in work_search
    assert "if scope == 'global':" in work_patch
    css = (ROOT / 'app' / 'static' / 'information-center-v160.css').read_text(encoding='utf-8')
    assert 'position:fixed' in css and 'bottom:calc(58px + env(safe-area-inset-bottom))' in css
    assert '.info-edit-v160 textarea{height:42vh;min-height:260px;max-height:460px}' in css
    assert 'APP_VERSION = "1.6.0"' in config or 'APP_VERSION = "1.6.1"' in config or 'APP_VERSION = "1.6.3"' in config or 'APP_VERSION = "1.6.5"' in config or 'APP_VERSION = "1.6.6"' in config or 'APP_VERSION = "1.6.7"' in config or 'APP_VERSION = "1.6.8"' in config

    print('v1.6.0 information center contract passed')


if __name__ == '__main__':
    main()

