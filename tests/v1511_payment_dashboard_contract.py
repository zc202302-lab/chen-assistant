from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def main():
    routes = (ROOT / 'app' / 'v027_home.py').read_text(encoding='utf-8')
    dashboard = (ROOT / 'app' / 'templates' / 'dashboard_v027.html').read_text(encoding='utf-8')
    css = (ROOT / 'app' / 'static' / 'work-home-polish-v121.css').read_text(encoding='utf-8')
    base = (ROOT / 'app' / 'templates' / 'base.html').read_text(encoding='utf-8')
    config = (ROOT / 'app' / 'config.py').read_text(encoding='utf-8')
    assert 'wait_notice, wait_initiate, wait_payment, done_payment = [], [], [], []' in routes
    assert "run_initiated = bool(run and (run['initiated_at'] or '').strip())" in routes
    assert "elif run_initiated:" in routes and "wait_payment.append(item)" in routes
    assert "elif s['notified'] or run_notified:" in routes and "wait_initiate.append(item)" in routes
    labels = ['未通知', '已通知', '待缴费']
    positions = [dashboard.index(f'>{label} <span class="count">') for label in labels]
    assert positions == sorted(positions)
    assert 'wait_notice|length + wait_initiate|length + wait_payment|length' in dashboard
    assert '还没通知客户' in dashboard
    assert '已通知客户，尚未发起缴费' in dashboard
    assert '已发起缴费，等待完成缴费' in dashboard
    assert '已通知未缴费' not in dashboard
    assert 'grid-template-columns:repeat(3,minmax(0,1fr))' in css
    assert '.state-notified' in css and '.state-initiated' in css
    assert 'work-home-polish-v121.css?v=15110' in base
    match = re.search(r'APP_VERSION = "(\\d+)\\.(\\d+)\\.(\\d+)"', config)
    assert match and tuple(map(int, match.groups())) >= (1, 5, 11)
    print('v1.5.11 three-stage payment dashboard contract passed')

if __name__ == '__main__':
    main()
