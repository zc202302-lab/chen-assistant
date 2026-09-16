from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    route = (ROOT / 'app' / 'v124_work_patch.py').read_text(encoding='utf-8')
    base = (ROOT / 'app' / 'templates' / 'base.html').read_text(encoding='utf-8')
    js = (ROOT / 'app' / 'static' / 'quick-search-v15.js').read_text(encoding='utf-8')
    css = (ROOT / 'app' / 'static' / 'quick-search-v15.css').read_text(encoding='utf-8')

    assert "@router.get('/quick-search-suggest')" in route
    assert "'label': '客户'" in route
    assert "'label': '号码 / 账号'" in route
    assert 'data-quick-search-results' in base
    assert 'data-search-scope' in base
    assert '/quick-search-suggest?scope=' in js
    assert 'setTimeout(() => loadSuggestions(q), 160)' in js
    assert '.quick-search-live-v151' in css
    print('v1.5.1 quick-search live suggestion contract passed')


if __name__ == '__main__':
    main()
