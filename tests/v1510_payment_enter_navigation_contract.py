from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    base = (ROOT / 'app/templates/base.html').read_text(encoding='utf-8')
    template = (ROOT / 'app/templates/customer_workspace_v0211.html').read_text(encoding='utf-8')
    v028 = (ROOT / 'app/static/v028.js').read_text(encoding='utf-8')
    high = (ROOT / 'app/static/high-frequency-v152.js').read_text(encoding='utf-8')
    main_py = (ROOT / 'app/main.py').read_text(encoding='utf-8')
    routes = (ROOT / 'app/v0212_routes.py').read_text(encoding='utf-8')

    # All live customer detail pages share one runtime owner/template.
    assert "('GET', '/customers/{customer_id}'): ('app.v0212_routes', 'customer_workspace_v0212')" in (
        ROOT / 'tests/code_governance_inventory.py'
    ).read_text(encoding='utf-8')
    assert "'customer_workspace_v0211.html'" in routes
    assert "getattr(_route, 'path', '') == '/customers/{customer_id}'" in main_py
    assert 'class="customer-workspace v028-workspace' in template
    assert '/static/v028.js?v=15101' in base

    # Account copy is row-authoritative, not dependent on a visible account column.
    assert 'data-payment-account="{{ s.account|e }}"' in template
    assert "next.dataset.paymentAccount" in v028
    assert "String(next.dataset.paymentAccount || '').trim()" in v028

    # Any unreviewed row is a navigation target, including a fixed row manually
    # unchecked by the user. Fixed/variable mode must not filter the target.
    assert "find(r => r.dataset.confirmed === '0')" in v028
    assert "r.dataset.mode === 'variable' && r.dataset.confirmed === '0'" not in v028
    assert "const done = !!data.confirmed;" in v028

    # v028 is the sole owner of amount Enter. The high-frequency helper may still
    # advance after a manual review-button click, but it must not arm Enter again.
    assert "document.addEventListener('keydown'" in v028
    assert "e.target.closest?.('.v028-workspace .quick-amount')" in v028
    assert "arm('amount'" not in high
    assert "event.target.closest?.('[data-payment-workbench] .quick-amount')" not in high
    assert "dataset.paymentAccount" in high

    print('v1.5.10 universal payment Enter navigation contract passed')


if __name__ == '__main__':
    main()
