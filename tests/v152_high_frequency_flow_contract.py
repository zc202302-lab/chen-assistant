from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    workspace_routes = (ROOT / 'app' / 'v101_workspace_routes.py').read_text(encoding='utf-8')
    home_routes = (ROOT / 'app' / 'v027_home.py').read_text(encoding='utf-8')
    dashboard = (ROOT / 'app' / 'templates' / 'dashboard_v027.html').read_text(encoding='utf-8')
    home = (ROOT / 'app' / 'templates' / 'home_v10.html').read_text(encoding='utf-8')
    base = (ROOT / 'app' / 'templates' / 'base.html').read_text(encoding='utf-8')
    js = (ROOT / 'app' / 'static' / 'high-frequency-v152.js').read_text(encoding='utf-8')
    css = (ROOT / 'app' / 'static' / 'high-frequency-v152.css').read_text(encoding='utf-8')

    assert "def work_customer_management_v14(request: Request, home: str = 'payment')" in workspace_routes
    assert "def dashboard_v027(request: Request, home: str = 'payment')" in home_routes
    assert dashboard.index('data-home-tab="payment"') < dashboard.index('data-home-tab="tasks"')
    assert 'href="/work/customers">进入客户管理' in home
    assert 'href="/work/customers" class="nav-item">◎<span>客户</span>' in base
    assert 'high-frequency-v152.css?v=1525' in base
    assert 'high-frequency-v152.js?v=15101' in base
    assert 'payment-total-row-v152' in js
    assert "document.querySelector('[data-payment-workbench]')" in js
    assert "event.target.closest?.('[data-payment-workbench] [data-review-toggle]')" in js
    assert "event.target.closest?.('[data-payment-workbench] .quick-amount')" in js
    assert 'ensurePaymentTotalRow' in js
    assert "window.addEventListener('chen:live-refresh'" in js
    assert 'focusAmountAndCopyAccount' in js
    assert 'currentRowByServiceId' in js
    assert 'waitForReviewedRow' in js
    assert 'nextPendingBelow(pending.serviceId)' in js
    assert '.identifier-copy[data-kind="账号"][data-copy]' in js
    assert 'dataset.paymentAccount' in js
    assert "item.dataset.confirmed === '0'" in js
    assert 'display:flex!important' in css
    assert 'justify-content:center' in css
    assert 'width:100%' in css
    assert 'text-align:center' in css
    print('v1.5.2 high-frequency customer/payment contract passed')


if __name__ == '__main__':
    main()
