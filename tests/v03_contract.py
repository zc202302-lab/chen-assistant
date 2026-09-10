from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Database-mutating contract checks must never run against production data/app.db.
# Patch app.db's module-level paths before importing app.main or route helpers.
import app.db as db_module  # noqa: E402

_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v03-contract-')
TEST_DATA_DIR = Path(_TMPDIR.name)
TEST_DB = TEST_DATA_DIR / 'app.db'
db_module.DATA_DIR = TEST_DATA_DIR
db_module.DB_PATH = TEST_DB

from app.db import db, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.v03_routes import _ensure_v03  # noqa: E402
from app.v0212_routes import _natural_due, _service_due  # noqa: E402


class Row(dict):
    pass


def service(*, interval=1, next_period='', last='2026-01-01', start='', stop=''):
    return Row(
        payment_interval_months=interval,
        payment_cycle=f'{interval}个月',
        next_payment_period=next_period,
        last_payment_date=last,
        active_from_period=start,
        inactive_from_period=stop,
    )


def first_route(path, method=None):
    matches = [r for r in app.router.routes if getattr(r, 'path', '') == path]
    if method:
        matches = [r for r in matches if method in getattr(r, 'methods', set())]
    assert matches, path
    return matches[0]


def test_route_ownership():
    assert app.version == '0.3.2'
    assert first_route('/health', 'GET').endpoint.__module__ == 'app.v031_payment_workflow_routes'
    assert first_route('/customers/{customer_id}').endpoint.__module__ == 'app.v0212_routes'
    assert first_route('/customers/{customer_id}/payment-workflow-v031', 'GET').endpoint.__module__ == 'app.v031_payment_workflow_routes'
    assert first_route('/customers/{customer_id}/payment-workflow-v031', 'POST').endpoint.__module__ == 'app.v031_payment_workflow_routes'
    assert first_route('/customers/{customer_id}/payment-mail-compose-v031', 'GET').endpoint.__module__ == 'app.v031_payment_workflow_routes'
    assert first_route('/customers/{customer_id}/payment-run', 'POST').endpoint.__module__ == 'app.v03_payment_routes'
    assert first_route('/customers/{customer_id}/payment-run-v03', 'GET').endpoint.__module__ == 'app.v03_routes'
    assert first_route('/customers/{customer_id}/payment-email-v03', 'POST').endpoint.__module__ == 'app.v03_routes'
    assert first_route('/services/{service_id}/status-v03', 'POST').endpoint.__module__ == 'app.v03_mail_draft_routes'
    assert first_route('/services/{service_id}/payment-status-v03', 'POST').endpoint.__module__ == 'app.v03_mail_draft_routes'
    assert first_route('/customers/{customer_id}/mail-template-v03', 'GET').endpoint.__module__ == 'app.v03_mail_draft_routes'
    assert first_route('/customers/{customer_id}/mail-template-v03', 'POST').endpoint.__module__ == 'app.v03_mail_draft_routes'
    assert first_route('/customers/{customer_id}/payment-mail-draft-v03', 'GET').endpoint.__module__ == 'app.v03_mail_draft_routes'
    assert first_route('/customers/{customer_id}/payment.txt', 'GET').endpoint.__module__ == 'app.v0212_routes'
    assert first_route('/customers/{customer_id}/business-columns-v0212', 'POST').endpoint.__module__ == 'app.v0212_business_display_routes'


def test_v03_migration_is_safe_and_idempotent():
    init_db()
    with db() as conn:
        _ensure_v03(conn)
        _ensure_v03(conn)
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(customer_payment_runs)').fetchall()}
        for key in ('reviewed_at', 'emailed_at', 'email_to', 'email_subject'):
            assert key in columns, key
        tables = {row['name'] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert 'payment_run_service_snapshots_v03' in tables
        assert 'payment_email_logs_v03' in tables
    assert TEST_DB.resolve() != (ROOT / 'data' / 'app.db').resolve()


def test_schedule_regression():
    annual = service(interval=12, next_period='2027-08')
    assert _natural_due(annual, '2026-09') is False
    assert _natural_due(annual, '2027-08') is True
    every_two = service(interval=2, next_period='2026-10')
    assert _natural_due(every_two, '2026-09') is False
    assert _natural_due(every_two, '2026-10') is True
    due_now = service(interval=2, next_period='2026-09')
    assert _service_due(due_now, {'status': 'inactive', 'deferred_until_period': ''}, '2026-09') is False
    assert _service_due(due_now, {'status': 'active', 'deferred_until_period': '2026-10'}, '2026-09') is False


def test_ui_contracts():
    base = (ROOT / 'app/templates/base.html').read_text(encoding='utf-8')
    js = (ROOT / 'app/static/v03.js').read_text(encoding='utf-8')
    css = (ROOT / 'app/static/v03.css').read_text(encoding='utf-8')
    drag = (ROOT / 'app/static/ui-drag.js').read_text(encoding='utf-8')
    routes = (ROOT / 'app/v03_routes.py').read_text(encoding='utf-8')
    safe_routes = (ROOT / 'app/v03_payment_routes.py').read_text(encoding='utf-8')
    local_mail_js = (ROOT / 'app/static/v03_business_mail.js').read_text(encoding='utf-8')
    local_mail_css = (ROOT / 'app/static/v03_business_mail.css').read_text(encoding='utf-8')
    local_mail_routes = (ROOT / 'app/v03_mail_draft_routes.py').read_text(encoding='utf-8')
    v031_js = (ROOT / 'app/static/v031_payment_workflow.js').read_text(encoding='utf-8')
    v031_routes = (ROOT / 'app/v031_payment_workflow_routes.py').read_text(encoding='utf-8')

    assert 'v0.3.2' in base
    assert '/static/v03.js' in base and '/static/v03.css' in base
    assert '/static/v03_business_mail.js' in base and '/static/v03_business_mail.css' in base
    assert '/static/v031_payment_workflow.js' in base and '/static/v031_payment_workflow.css' in base
    assert '/static/v0212.js' not in base
    assert '/static/business-editor-hotfix.js' not in base

    assert 'data-v03-business-status-panel' in js
    assert '开停状态' in js and '缴费状态' in js
    assert 'data-v03-payment-order' in js and '缴费金额必须填写显示序号' in js
    assert 'data-v03-flow-action' in js and "['review', 'notify', 'paid']" in js
    assert '/api/v03/customers/search' in js

    assert '生成缴费图片' in v031_js
    assert '已通知客户' in v031_js and '发起缴费' in v031_js and '完成缴费' in v031_js
    assert 'navigator.clipboard.write' in v031_js and 'ClipboardItem' in v031_js
    assert 'payment-workflow-v031' in v031_js and 'payment-mail-compose-v031' in v031_js
    assert "action == 'initiate'" in v031_routes and "action == 'invalidate'" in v031_routes

    assert 'repeat(var(--v03-payment-count,1),minmax(0,1fr))' in css
    assert 'repeat(var(--business-visible-count,var(--v03-business-count,1)),minmax(0,1fr))' in css
    assert 'text-align:center' in css
    assert 'v03-home-search' in css

    assert 'v03-readable-filters' in local_mail_js
    assert '更多筛选' in local_mail_js
    assert 'mail-template-v03' in local_mail_js
    assert 'payment-mail-draft-v03' in local_mail_js
    assert 'v03-mail-template-dialog' in local_mail_css
    assert 'customer_mail_templates_v03' in local_mail_routes
    assert "msg['X-Unsent'] = '1'" in local_mail_routes
    assert 'business_display' in local_mail_routes

    assert 'bindFastBusinessSort' in drag
    assert "bindPointerSort(paymentList, '.drag-handle'" not in drag
    assert 'payment_run_service_snapshots_v03' in routes
    assert "action == 'review'" in routes and "action == 'paid'" in routes
    assert 'snapshot_count' in safe_routes
    assert '旧版本' in safe_routes and '不允许自动撤回' in safe_routes


if __name__ == '__main__':
    test_route_ownership()
    test_v03_migration_is_safe_and_idempotent()
    test_schedule_regression()
    test_ui_contracts()
    print('v0.3.2 contract checks passed (isolated test database)')
