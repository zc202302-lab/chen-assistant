from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
base = (ROOT / 'app/templates/base.html').read_text(encoding='utf-8')
js = (ROOT / 'app/static/v125_excel_review.js').read_text(encoding='utf-8')
css = (ROOT / 'app/static/v125_excel_review.css').read_text(encoding='utf-8')
patch = (ROOT / 'app/v031_fixed_review_patch.py').read_text(encoding='utf-8')
workspace = (ROOT / 'app/templates/customer_workspace_v0211.html').read_text(encoding='utf-8')

assert '/static/v125_excel_review.css?v=1250' in base
assert '/static/v125_excel_review.js?v=1250' in base
assert base.index('/static/v125_excel_review.js?v=1250') > base.index('/static/v124_work_tables.js?v=1241')

# Stage 1 is computed from row confirmations; it cannot be manually toggled.
assert "rows.every(row => row.dataset.confirmed === '1')" in js
assert "reviewButton.disabled = true" in js
assert "data-v031-flow-action=\"review\"" in js
assert "attributeFilter: ['data-confirmed']" in js
assert "ChenPaymentWorkflowRuntimeV031?.refresh" in js
assert "all_confirmed = due_count > 0 and pending == 0" in patch
assert "SET reviewed_at=CASE" in patch
assert "SET reviewed_at='',notified_at='',initiated_at=''" in patch

# Standalone toolbars are removed and table-header controls replace them.
assert "[data-v124-payment-tools]" in js
assert "[data-business-filters], .business-filters" in js
assert 'data-v125-payment-filter' in js
assert 'data-v125-payment-state' in js
assert 'v125-business-header' in js
assert 'data-v125-business-filter-popover' in js
assert '.v125-head-search' in css
assert '.v125-filter-popover' in css
assert 'data-payment-column-head' in workspace
assert 'data-business-list' in workspace

print('v1.2.5 contract passed: realtime derived review + Excel-style table header filters')
