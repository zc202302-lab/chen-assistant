from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]


def main():
    home = (ROOT / 'app' / 'templates' / 'home_v10.html').read_text(encoding='utf-8')
    base = (ROOT / 'app' / 'templates' / 'base.html').read_text(encoding='utf-8')
    css = (ROOT / 'app' / 'static' / 'global-back.css').read_text(encoding='utf-8')
    config = (ROOT / 'app' / 'config.py').read_text(encoding='utf-8')

    assert 'class="global-primary-nav"' in base
    assert 'href="/"' in base and '>首页</a>' in base
    assert 'href="/work"' in base and '>工作</a>' in base
    assert 'href="/info"' in base and '>资料</a>' in base
    assert 'href="/life"' in base and '>生活</a>' in base
    assert 'home-top-nav-v153' not in home
    assert 'v10-space-grid v152-space-grid' not in home
    assert 'v152-customer-space' not in home
    assert 'v152-life-space' not in home
    assert '@view-transition{navigation:auto}' in css
    assert 'view-transition-name:app-topbar' in css
    assert 'view-transition-name:app-page' in css
    assert '.topbar-actions' in css
    assert 'position:static' in css
    versions = [node.value.value for node in ast.parse(config).body
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'APP_VERSION' for t in node.targets)]
    assert len(versions) == 1 and len(versions[0].split('.')) == 3
    assert 'href="/reminders"' in base
    print('global top navigation contract passed on app v' + versions[0])


if __name__ == '__main__':
    main()


