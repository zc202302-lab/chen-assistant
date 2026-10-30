from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]


def main():
    base = (ROOT / 'app' / 'templates' / 'base.html').read_text(encoding='utf-8')
    customers = (ROOT / 'app' / 'templates' / 'customers.html').read_text(encoding='utf-8')
    css = (ROOT / 'app' / 'static' / 'responsive-polish-v161.css').read_text(encoding='utf-8')
    config = (ROOT / 'app' / 'config.py').read_text(encoding='utf-8')
    deploy = (ROOT / 'deploy.sh').read_text(encoding='utf-8')

    assert 'responsive-polish-v161.css?v=1800' in base
    assert 'customer-directory-v161' in customers
    assert 'class="page-head customer-directory-v161"' in customers
    assert 'customer-directory-actions-v161' in customers
    assert 'customer-search-v161' in customers
    assert 'customer-filter-v161' in customers
    assert 'customer-card-v161' in customers
    assert 'customer-card-fee-v161' in customers

    assert '.topbar-actions{\n  display:contents;' in css
    assert '.topbar-left .global-history-nav{position:static;' in css
    assert base.index('data-history-back') < base.index('class="global-primary-nav"') < base.index('data-history-forward')
    assert '.global-navigation-group{display:flex;' in css
    assert '.search-link{\n  grid-column:3;' in css
    assert '.global-primary-nav{\n  grid-column:1/-1;' in css
    assert '@media(max-width:760px)' in css
    assert '.customer-directory-list-v161{\n  display:grid;' in css
    assert 'grid-template-columns:repeat(2,minmax(0,1fr));' in css
    assert '@media(max-width:980px)' in css
    version = next(node.value.value for node in ast.parse(config).body
                   if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'APP_VERSION' for t in node.targets))
    assert tuple(map(int, version.split('.'))) >= (1, 6, 0)
    assert f'EXPECTED_VERSION="{version}"' in deploy

    print('v1.6.1 responsive polish contract passed')


if __name__ == '__main__':
    main()



