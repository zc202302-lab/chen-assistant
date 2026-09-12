#!/usr/bin/env bash
set -Eeuo pipefail
APP_DIR="/opt/chen-assistant"; SERVICE="chen-assistant"; APP_HTTP="http://172.19.0.1:8010"; HEALTH_URL="$APP_HTTP/health"; BACKUP_DIR="$APP_DIR/backups"; EXPECTED_VERSION="1.2.1"
cd "$APP_DIR"
echo "===== 晨的助手 v${EXPECTED_VERSION} 一键更新 ====="
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then echo "✗ 检测到服务器受 Git 管理文件有本地修改，已停止更新。"; git status --short; exit 1; fi
SERVICE_USER="$(systemctl show "$SERVICE" -p User --value)"; [[ -n "$SERVICE_USER" ]] || SERVICE_USER="root"
SERVICE_GROUP="$(systemctl show "$SERVICE" -p Group --value)"; [[ -n "$SERVICE_GROUP" ]] || SERVICE_GROUP="$SERVICE_USER"
mkdir -p "$BACKUP_DIR"; TS="$(date +%Y%m%d-%H%M%S)"; BACKUP_FILE="$BACKUP_DIR/app.db.$TS"
if [[ -f data/app.db ]]; then .venv/bin/python - "$BACKUP_FILE" <<'PY'
import sqlite3,sys
from pathlib import Path
src=Path('data/app.db'); dst=Path(sys.argv[1])
with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d); assert d.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
print(f'✓ 数据库备份完成：{dst}')
PY
fi
echo "当前代码：$(git rev-parse --short HEAD)"; git fetch origin main; git merge --ff-only origin/main; .venv/bin/pip install -q -r requirements.txt
.venv/bin/python -m compileall -q app
if command -v node >/dev/null 2>&1; then for ASSET in app.js v028.js ui-drag.js service-promotions.js business-sync.js v0211.js workspace-refinement-v0212.js v03.js v03_runtime_fix.js v03_business_mail.js v03_payment_template.js v03_foxmail_action_fix.js v03_insert_order.js v03_review_reset.js v031_payment_workflow.js v031_amount_rollback_fix.js v031_workflow_actions.js v031_workflow_runtime_fix.js v031_workflow_dom_guard.js v031_windows_bootstrap.js v033_payment_flow_patch.js v10.js v12.js recipe-print-v101.js; do node --check "app/static/$ASSET"; done; fi
.venv/bin/python - "$EXPECTED_VERSION" <<'PY'
import sys
from pathlib import Path
from app.main import app
from app.v101_recipe_template_data import TEMPLATE_IMPORT_MARKER,TEMPLATE_SHEET_NAMES
from app.v101_recipe_template_patch import ensure_v101_recipe_templates
from app.db import db
expected=sys.argv[1]; assert app.version==expected,(app.version,expected)
ensure_v101_recipe_templates()
for method,path in [('GET','/life'),('GET','/life/recipes'),('GET','/life/tools'),('GET','/life/recipes/{recipe_id}/print'),('GET','/work'),('GET','/search')]:
    assert any(getattr(r,'path','')==path and method in getattr(r,'methods',set()) for r in app.router.routes),(method,path)
with db() as conn:
    n=conn.execute('SELECT COUNT(*) n FROM recipe_versions WHERE change_summary LIKE ?',(f'{TEMPLATE_IMPORT_MARKER}%',)).fetchone()['n']; assert n==len(TEMPLATE_SHEET_NAMES)==18,n
for path in ['app/templates/cooking_tools_v12.html','app/templates/recipe_print_v101.html','app/static/v12.js','app/static/v12.css','app/static/recipe-print-v101.css','app/static/work-home-polish-v121.css']:
    assert Path(path).is_file(),path
print('✓ v1.2.1 路由 / 18个标准模板 / 烹饪工具 / A4打印 / 工作首页视觉资源检查通过')
PY
if [[ -d data ]]; then chown "$SERVICE_USER:$SERVICE_GROUP" data; find data -maxdepth 1 -type f \( -name 'app.db' -o -name 'app.db-wal' -o -name 'app.db-shm' \) -exec chown "$SERVICE_USER:$SERVICE_GROUP" {} +; chmod u+rwx data; fi
systemctl restart "$SERVICE"; sleep 3; HEALTH_JSON="$(curl -fsS "$HEALTH_URL")"; echo "$HEALTH_JSON"
.venv/bin/python - "$HEALTH_JSON" "$EXPECTED_VERSION" <<'PY'
import json,sys
p=json.loads(sys.argv[1]); expected=sys.argv[2]; assert p.get('ok') is True and p.get('version')==expected,(p,expected); print(f"✓ 服务版本：{p['version']}")
PY
REV="$(git rev-parse --short HEAD)"
for ASSET in v10.js v12.js v12.css recipe-print-v101.js recipe-print-v101.css work-home-polish-v121.css v033_payment_flow_patch.js app.css; do TMP="$(mktemp)"; curl -fsS "$APP_HTTP/static/$ASSET?deploy=$REV" -o "$TMP"; [[ "$(sha256sum app/static/$ASSET|awk '{print $1}')" == "$(sha256sum "$TMP"|awk '{print $1}')" ]] || { echo "✗ 静态资源不一致：$ASSET"; rm -f "$TMP"; exit 1; }; rm -f "$TMP"; done
echo "✓ 静态资源一致"; echo "===== 晨的助手 v${EXPECTED_VERSION} 更新完成 ====="; echo "代码：$(git rev-parse --short HEAD)"; echo "备份：${BACKUP_FILE:-无}"
