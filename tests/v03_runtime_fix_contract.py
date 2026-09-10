from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402


def first_route(path, method=None):
    matches = [r for r in app.router.routes if getattr(r, 'path', '') == path]
    if method:
        matches = [r for r in matches if method in getattr(r, 'methods', set())]
    assert matches, path
    return matches[0]


def main():
    assert app.version == '0.3.2'
    assert first_route('/customers/{customer_id}/workflow-state-v03', 'GET').endpoint.__module__ == 'app.v031_runtime_routes'
    assert first_route('/services/{service_id}/payment-status-v03', 'POST').endpoint.__module__ == 'app.v03_mail_draft_routes'
    assert first_route('/customers/{customer_id}/payment-workflow-v031', 'GET').endpoint.__module__ == 'app.v031_payment_workflow_routes'

    base = (ROOT / 'app/templates/base.html').read_text(encoding='utf-8')
    js = (ROOT / 'app/static/v03_runtime_fix.js').read_text(encoding='utf-8')
    v031_js = (ROOT / 'app/static/v031_payment_workflow.js').read_text(encoding='utf-8')
    routes = (ROOT / 'app/v031_runtime_routes.py').read_text(encoding='utf-8')
    scoped_routes = (ROOT / 'app/v03_mail_draft_routes.py').read_text(encoding='utf-8')

    assert base.count('/static/v03_runtime_fix.js') == 1
    assert base.count('/static/v031_payment_workflow.js') == 1
    assert '金额核对' in js and '通知客户' in js and '完成缴费' in js
    assert '已通知客户' in v031_js and '发起缴费' in v031_js
    assert 'workflow-state-v03' in js
    assert 'data-v031-payment-mode' in js
    assert '恢复正常缴费周期' in js
    assert 'payment-status-v03' in js
    assert "deferred_until_period=''" in routes
    assert "mode != 'normal'" in routes
    assert "business_display._ordered_keys(conn, template, customer_id)" in scoped_routes
    print('v0.3.2 runtime fix contract passed')


if __name__ == '__main__':
    main()
