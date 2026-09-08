from pathlib import Path

from app.main import app
from app.v0212_routes import _natural_due, _service_due


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


def test_current_route_ownership():
    assert app.version == '0.2.12'
    assert first_route('/customers/{customer_id}').endpoint.__module__ == 'app.v0212_routes'
    assert first_route('/customers/{customer_id}/payment-run', 'POST').endpoint.__module__ == 'app.v0212_routes'
    assert first_route('/customers/{customer_id}/payment.txt', 'GET').endpoint.__module__ == 'app.v0212_routes'
    assert first_route('/services/{service_id}/defer-v0212', 'POST').endpoint.__module__ == 'app.v0212_routes'
    assert first_route('/services/{service_id}/delete-v0212', 'POST').endpoint.__module__ == 'app.v0212_routes'


def test_strict_payment_schedule():
    annual = service(interval=12, next_period='2027-08')
    assert _natural_due(annual, '2026-09') is False
    assert _natural_due(annual, '2027-08') is True

    every_two = service(interval=2, next_period='2026-10')
    assert _natural_due(every_two, '2026-09') is False
    assert _natural_due(every_two, '2026-10') is True

    due_now = service(interval=2, next_period='2026-09')
    assert _service_due(due_now, {'status': 'inactive', 'deferred_until_period': ''}, '2026-09') is False
    assert _service_due(due_now, {'status': 'active', 'deferred_until_period': '2026-10'}, '2026-09') is False
    assert _service_due(due_now, {'status': 'active', 'deferred_until_period': '2026-10'}, '2026-10') is True


def test_ui_contracts():
    root = Path(__file__).resolve().parents[1]
    js = (root / 'app/static/v0212.js').read_text(encoding='utf-8')
    business = (root / 'app/static/business-sync.js').read_text(encoding='utf-8')
    routes = (root / 'app/v0212_routes.py').read_text(encoding='utf-8')

    assert 'defer-v0212' in js and '删除此条数据' in js
    assert 'payment_amount' in js and 'scrubAmountFromAttributeDialog' in js
    assert 'business_visible_json' in js and '业务模块显示' in js
    assert '.slice(0, 5)' not in business
    assert 'index >= 5' not in business
    assert "if not _service_due(service, runtime[service['id']], period):" in routes
    assert "DELETE FROM services WHERE id=?" in routes


if __name__ == '__main__':
    test_current_route_ownership()
    test_strict_payment_schedule()
    test_ui_contracts()
    print('v0.2.12 contract checks passed')
