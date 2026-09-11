from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.main import app  # noqa: E402


def first_route(path, method=None):
    matches = [r for r in app.router.routes if getattr(r, 'path', '') == path]
    if method:
        matches = [r for r in matches if method in getattr(r, 'methods', set())]
    assert matches, path
    return matches[0]


def main():
    assert app.version == config.APP_VERSION
    assert first_route('/customers/{customer_id}/workflow-state-v03', 'GET').endpoint.__module__ == 'app.v031_runtime_routes'
    assert first_route('/services/{service_id}/payment-status-v03', 'POST').endpoint.__module__ == 'app.v03_mail_draft_routes'
    assert first_route('/customers/{customer_id}/payment-workflow-v031', 'GET').endpoint.__module__ == 'app.v031_payment_workflow_routes'
    assert first_route('/customers/{customer_id}/payment.txt', 'GET').endpoint.__module__ == 'app.v033_payment_flow_patch'

    base = (ROOT / 'app/templates/base.html').read_text(encoding='utf-8')
    js = (ROOT / 'app/static/v03_runtime_fix.js').read_text(encoding='utf-8')
    v031_js = (ROOT / 'app/static/v031_payment_workflow.js').read_text(encoding='utf-8')
    owner = (ROOT / 'app/static/v031_workflow_runtime_fix.js').read_text(encoding='utf-8')
    routes = (ROOT / 'app/v031_runtime_routes.py').read_text(encoding='utf-8')
    scoped_routes = (ROOT / 'app/v03_mail_draft_routes.py').read_text(encoding='utf-8')
    payment_patch = (ROOT / 'app/v033_payment_flow_patch.py').read_text(encoding='utf-8')

    assert base.count('/static/v03_runtime_fix.js') == 1
    assert base.count('/static/v031_payment_workflow.js') == 1
    assert base.count('/static/v031_workflow_runtime_fix.js') == 1
    assert base.count('/static/v033_payment_flow_patch.js') == 1
    assert base.count('/static/v10.js') == 1

    # Mature work/payment compatibility remains unchanged under the current app shell.
    assert 'workflow-state-v03' not in js
    assert 'payment-run-v03' not in js
    assert 'data-v03-flow-action' not in js
    assert 'flowState' not in js
    assert 'data-v031-payment-mode' in js
    assert '恢复正常缴费周期' in js
    assert 'payment-status-v03' in js

    assert '已通知客户' in v031_js and '发起缴费' in v031_js
    assert 'window.ChenPaymentWorkflowRuntimeV031' in owner
    assert 'payment-workflow-v031' in owner
    assert 'data-v031-flow-action' in owner

    assert "deferred_until_period=''" in routes
    assert "mode != 'normal'" in routes
    assert "business_display._ordered_keys(conn, template, customer_id)" in scoped_routes
    assert 'payment_txt_current_workflow_v033' in payment_patch
    print('current app shell + mature payment/business runtime compatibility contract passed')


if __name__ == '__main__':
    main()
