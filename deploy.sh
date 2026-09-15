#!/usr/bin/env bash
set -Eeuo pipefail
APP_DIR="/opt/chen-assistant"; SERVICE="chen-assistant"; APP_HTTP="http://172.19.0.1:8010"; HEALTH_URL="$APP_HTTP/health"; BACKUP_DIR="$APP_DIR/backups"; EXPECTED_VERSION="1.4.3"
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
.venv/bin/python -m compileall -q app storage_node
if command -v node >/dev/null 2>&1; then
  find app/static -maxdepth 1 -type f -name '*.js' -print0 | sort -z | while IFS= read -r -d '' ASSET; do
    node --check "$ASSET"
  done
fi
.venv/bin/python - "$EXPECTED_VERSION" <<'PY'
import sys
from pathlib import Path
from app.main import app
from app.v101_recipe_template_data import TEMPLATE_IMPORT_MARKER,TEMPLATE_SHEET_NAMES
from app.v101_recipe_template_patch import ensure_v101_recipe_templates
from app.v13_customer_documents import ensure_v13_customer_documents
from app.v143_customer_resources import ensure_customer_resources_v143
from app.db import db
expected=sys.argv[1]; assert app.version==expected,(app.version,expected)
ensure_v101_recipe_templates(); ensure_v13_customer_documents(); ensure_customer_resources_v143()
for method,path in [('GET','/life'),('GET','/life/recipes'),('GET','/life/tools'),('GET','/life/recipes/{recipe_id}/print'),('GET','/work'),('GET','/work/customers'),('GET','/work/library'),('GET','/search'),('GET','/customers/{customer_id}/documents-v13'),('POST','/customers/{customer_id}/documents-v13'),('GET','/customers/{customer_id}/documents-v13/{document_id}/download'),('GET','/customers/{customer_id}/resource-items-v143'),('POST','/customers/{customer_id}/resource-items-v143'),('POST','/customers/{customer_id}/resource-items-v143/{item_id}/delete'),('GET','/customers/{customer_id}/runtime-v143'),('POST','/customers/{customer_id}/runtime-v143'),('POST','/services/{service_id}/toggle-fixed'),('POST','/services/{service_id}/payment-review-toggle'),('POST','/customers/{customer_id}/payment-workflow-v031')]:
    assert any(getattr(r,'path','')==path and method in getattr(r,'methods',set()) for r in app.router.routes),(method,path)
with db() as conn:
    n=conn.execute('SELECT COUNT(*) n FROM recipe_versions WHERE change_summary LIKE ?',(f'{TEMPLATE_IMPORT_MARKER}%',)).fetchone()['n']; assert n==len(TEMPLATE_SHEET_NAMES)==18,n
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='customer_documents'").fetchone()
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='customer_resource_items_v143'").fetchone()
for path in ['app/templates/cooking_tools_v12.html','app/templates/recipe_print_v101.html','app/static/v12.js','app/static/v12.css','app/static/recipe-print-v101.css','app/static/work-home-polish-v121.css','app/static/global-back.js','app/static/global-back.css','app/static/v143_customer_status.js','app/static/v143_customer_status.css','app/static/v143_customer_resources.js','app/static/v143_customer_resources.css','app/static/v13_customer_documents.js','app/static/v13_customer_documents.css','app/v143_payment_controls_patch.py','app/v143_customer_resources.py','app/v144_audit_hardening.py','app/work_architecture.py','app/templates/work_shell_v14.html','app/templates/work_library_v14.html','app/static/work-architecture-v14.css','storage_node/app.py']:
    assert Path(path).is_file(),path
print('✓ v1.3 客户远程文件 + v1.4 工作双模块 + v1.4.3 功能 + 全量审计加固检查通过')
PY
if [[ -d data ]]; then chown "$SERVICE_USER:$SERVICE_GROUP" data; find data -maxdepth 1 -type f \( -name 'app.db' -o -name 'app.db-wal' -o -name 'app.db-shm' \) -exec chown "$SERVICE_USER:$SERVICE_GROUP" {} +; chmod u+rwx data; fi
systemctl restart "$SERVICE"; sleep 3; HEALTH_JSON="$(curl -fsS "$HEALTH_URL")"; echo "$HEALTH_JSON"
.venv/bin/python - "$HEALTH_JSON" "$EXPECTED_VERSION" <<'PY'
import json,sys
p=json.loads(sys.argv[1]); expected=sys.argv[2]; assert p.get('ok') is True and p.get('version')==expected,(p,expected); print(f"✓ 服务版本：{p['version']}")
PY
REV="$(git rev-parse --short HEAD)"
find app/static -maxdepth 1 -type f \( -name '*.js' -o -name '*.css' \) -print0 | sort -z | while IFS= read -r -d '' PATHNAME; do
  ASSET="${PATHNAME#app/static/}"
  TMP="$(mktemp)"
  curl -fsS "$APP_HTTP/static/$ASSET?deploy=$REV" -o "$TMP"
  [[ "$(sha256sum "$PATHNAME"|awk '{print $1}')" == "$(sha256sum "$TMP"|awk '{print $1}')" ]] || { echo "✗ 静态资源不一致：$ASSET"; rm -f "$TMP"; exit 1; }
  rm -f "$TMP"
done
echo "✓ 全部 JS/CSS 静态资源一致"
if grep -q '^REMOTE_STORAGE_BASE_URL=' .env 2>/dev/null && grep -q '^REMOTE_STORAGE_TOKEN=' .env 2>/dev/null; then
  STORAGE_URL="$(grep '^REMOTE_STORAGE_BASE_URL=' .env | tail -n1 | cut -d= -f2-)"
  if [[ -n "$STORAGE_URL" ]]; then curl -fsS "${STORAGE_URL%/}/health" >/dev/null && echo "✓ 远程资料存储通道在线" || echo "⚠ 远程资料存储已配置，但当前健康检查失败"; fi
else
  echo "ℹ 客户资料模块已安装；远程存储尚未配置时会在页面提示。"
fi
echo "===== 晨的助手 v${EXPECTED_VERSION} 更新完成 ====="; echo "代码：$(git rev-parse --short HEAD)"; echo "备份：${BACKUP_FILE:-无}"
