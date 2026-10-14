from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
app_js = (ROOT / 'app' / 'static' / 'app.js').read_text(encoding='utf-8')

# Copy feedback must exist for both global copy buttons and current workspace copies.
assert "toast(ok ? '已复制' : '复制失败')" in app_js
assert "[data-copy-silent],[data-business-row] .business-attribute" in app_js
assert "const ok = await copyText(value)" in app_js
assert "['number', 'account'].includes(attribute.dataset.attrKey || attribute.dataset.paymentAttrKey)" in app_js
assert "toast(ok ? '已复制' : '复制失败，请重试')" in app_js
assert "setTimeout(() => toast('已复制'), 0)" not in app_js
# Identifier copies retain their payment focus owner, using the shared helper
# and actual result feedback rather than an unrelated capture-phase toast.
payment_js = (ROOT / 'app/static/v028.js').read_text(encoding='utf-8')
assert "e.target.closest('.identifier-copy')" in payment_js
assert "return window.ChenCopyText(value)" in payment_js
assert "const ok = await copyText(id.dataset.copy || '')" in payment_js
assert "window.ChenToast?.(ok ? '已复制' : '复制失败，请重试')" in payment_js

# Payment header must be forced back into normal flow at runtime so the horizontal
# scroll container cannot push it down over payment rows.
assert "document.querySelectorAll('.v028-payment-header')" in app_js
assert "header.style.position = 'relative'" in app_js
assert "header.style.top = 'auto'" in app_js

print('production experience regression passed')
