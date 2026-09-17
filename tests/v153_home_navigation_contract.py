from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    home = (ROOT / 'app' / 'templates' / 'home_v10.html').read_text(encoding='utf-8')
    css = (ROOT / 'app' / 'static' / 'home-top-nav-v153.css').read_text(encoding='utf-8')
    config = (ROOT / 'app' / 'config.py').read_text(encoding='utf-8')

    assert 'home-top-nav-v153' in home
    assert 'href="/" aria-current="page">首页</a>' in home
    assert 'href="/work">工作</a>' in home
    assert 'href="/life">生活</a>' in home
    assert 'v10-space-grid v152-space-grid' not in home
    assert 'v152-customer-space' not in home
    assert 'v152-life-space' not in home
    assert 'position:sticky' in css
    assert 'justify-content:center' in css
    assert 'APP_VERSION = "1.5.3"' in config
    print('v1.5.3 home top navigation contract passed')


if __name__ == '__main__':
    main()
