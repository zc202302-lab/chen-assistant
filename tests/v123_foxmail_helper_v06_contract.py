from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
helper = (ROOT / 'app/static/chen_foxmail_helper_v06.ps1').read_text(encoding='utf-8')
bootstrap = (ROOT / 'app/static/chen_foxmail_bootstrap.ps1').read_text(encoding='utf-8')
js = (ROOT / 'app/static/v123_foxmail_compose_fix.js').read_text(encoding='utf-8')

assert "version='0.6'" in helper
assert 'compose-window-detected' in helper
assert 'MAPI_LOGON_UI|MAPI_DIALOG' in helper
assert 'MAPI_NEW_SESSION' not in helper
assert 'MainWindowHandle' in helper
assert "System32\\mapi32.dll" in helper
assert 'chen_foxmail_helper_v06.ps1' in bootstrap
assert "version='0.6'" in bootstrap
assert 'compose-window-detected' in js
assert 'mapi-accepted-window-unverified' not in js
assert "fallback: 'eml'" not in js

print('Foxmail helper v0.6 verified-compose contract passed')
