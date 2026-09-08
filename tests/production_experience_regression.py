from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
app_js = (ROOT / 'app' / 'static' / 'app.js').read_text(encoding='utf-8')

# Copy feedback must exist for both global copy buttons and current workspace copies.
assert "toast(ok ? '已复制' : '复制失败')" in app_js
assert ".identifier-copy,[data-copy-silent]" in app_js
assert "toast('已复制')" in app_js

# Payment header must be forced back into normal flow at runtime so the horizontal
# scroll container cannot push it down over payment rows.
assert "document.querySelectorAll('.v028-payment-header')" in app_js
assert "header.style.position = 'relative'" in app_js
assert "header.style.top = 'auto'" in app_js

print('production experience regression passed')
