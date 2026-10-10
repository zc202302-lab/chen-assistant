#!/usr/bin/env bash
set -Eeuo pipefail
APP_DIR="/opt/chen-assistant"; SERVICE="chen-assistant"; APP_HTTP="http://172.19.0.1:8010"; HEALTH_URL="$APP_HTTP/health"; BACKUP_DIR="$APP_DIR/backups"; EXPECTED_VERSION="1.7.7"
cd "$APP_DIR"
echo "===== 晨的助手 v${EXPECTED_VERSION} 一键更新 ====="
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then echo "✗ 检测到服务器受 Git 管理文件有本地修改，已停止更新。"; git status --short; exit 1; fi
DEPLOY_FROM_REV="${CHEN_DEPLOY_FROM_REV:-$(git rev-parse HEAD)}"
TARGET_REV="${CHEN_DEPLOY_TARGET_REV:-}"
START_REV="$(git rev-parse HEAD)"
echo "当前代码：$(git rev-parse --short HEAD)"
git fetch origin main
if [[ -n "$TARGET_REV" ]]; then
  git rev-parse --verify "$TARGET_REV^{commit}" >/dev/null 2>&1 || { echo "✗ 指定部署提交不存在：$TARGET_REV"; exit 1; }
  git merge-base --is-ancestor "$TARGET_REV" origin/main || { echo "✗ 指定部署提交不属于当前 origin/main：$TARGET_REV"; exit 1; }
  if [[ "$TARGET_REV" == "$START_REV" ]]; then
    echo "✓ 当前生产代码正是指定提交，继续执行部署自检"
  elif git merge-base --is-ancestor "$TARGET_REV" "$START_REV"; then
    echo "✓ 当前生产代码已经超过指定提交，跳过过时部署任务且不回退"
    exit 0
  elif git merge-base --is-ancestor "$START_REV" "$TARGET_REV"; then
    git merge --ff-only "$TARGET_REV"
  else
    echo "✗ 生产代码与指定部署提交无法快进合并，已停止更新"
    exit 1
  fi
else
  git merge --ff-only origin/main
fi
END_REV="$(git rev-parse HEAD)"
if [[ "$START_REV" != "$END_REV" && "${CHEN_DEPLOY_REEXEC:-0}" != "1" ]]; then
  echo "✓ 已更新部署脚本与代码，使用新脚本继续部署"
  exec env CHEN_DEPLOY_REEXEC=1 CHEN_DEPLOY_FROM_REV="$DEPLOY_FROM_REV" CHEN_DEPLOY_TARGET_REV="$TARGET_REV" bash "$APP_DIR/deploy.sh"
fi
CHANGED_FILE_LIST="$(mktemp)"
trap 'rm -f "$CHANGED_FILE_LIST"' EXIT
if [[ "$DEPLOY_FROM_REV" != "$END_REV" ]]; then
  git diff --name-only "$DEPLOY_FROM_REV" "$END_REV" > "$CHANGED_FILE_LIST"
else
  : > "$CHANGED_FILE_LIST"
fi
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
if grep -qx 'requirements.txt' "$CHANGED_FILE_LIST"; then
  echo "→ requirements.txt 有变化，更新 Python 依赖"
  .venv/bin/pip install -q -r requirements.txt
else
  echo "✓ Python 依赖未变化，跳过 pip install"
fi
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
from app.work_list_import import ensure_work_list_import_schema
from app.work_lists import ensure_work_lists_schema
from app.db import db
from app.reminders import ensure_reminder_schema
expected=sys.argv[1]; assert app.version==expected,(app.version,expected)
ensure_reminder_schema(); ensure_work_lists_schema(); ensure_work_list_import_schema(); ensure_v101_recipe_templates(); ensure_v13_customer_documents(); ensure_customer_resources_v143()
for method,path in [('GET','/reminders'),('GET','/api/reminders'),('POST','/api/reminders/subscriptions'),('GET','/reminders/open/{reminder_id}'),('GET','/life'),('GET','/life/recipes'),('GET','/life/tools'),('GET','/life/recipes/{recipe_id}/print'),('GET','/work/list-import'),('POST','/work/list-import/{token}/confirm'),('GET','/work/lists'),('GET','/work/lists/{list_id}/export.xlsx'),('POST','/work/lists/{list_id}/records/new'),('GET','/work'),('GET','/work/customers'),('GET','/work/library'),('GET','/search'),('GET','/api/number-inbox/pending'),('POST','/api/number-inbox/{item_id}/done'),('GET','/customers/{customer_id}/documents-v13'),('POST','/customers/{customer_id}/documents-v13'),('GET','/customers/{customer_id}/documents-v13/{document_id}/download'),('GET','/customers/{customer_id}/resource-items-v143'),('POST','/customers/{customer_id}/resource-items-v143'),('POST','/customers/{customer_id}/resource-items-v143/{item_id}/delete'),('GET','/customers/{customer_id}/runtime-v143'),('POST','/customers/{customer_id}/runtime-v143'),('POST','/services/{service_id}/toggle-fixed'),('POST','/services/{service_id}/payment-review-toggle'),('POST','/customers/{customer_id}/payment-workflow-v031'),('GET','/customers/{customer_id}/payment.xlsx')]:
    assert any(getattr(r,'path','')==path and method in getattr(r,'methods',set()) for r in app.router.routes),(method,path)
with db() as conn:
    n=conn.execute('SELECT COUNT(*) n FROM recipe_versions WHERE change_summary LIKE ?',(f'{TEMPLATE_IMPORT_MARKER}%',)).fetchone()['n']; assert n==len(TEMPLATE_SHEET_NAMES)==18,n
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='customer_documents'").fetchone()
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='customer_resource_items_v143'").fetchone()
for path in ['app/templates/cooking_tools_v12.html','app/templates/recipe_print_v101.html','app/static/v12.js','app/static/v12.css','app/static/recipe-print-v101.css','app/static/work-home-polish-v121.css','app/static/global-back.js','app/static/global-back.css','app/static/v143_customer_status.js','app/static/v143_customer_status.css','app/static/v143_customer_resources.js','app/static/v143_customer_resources.css','app/static/v13_customer_documents.js','app/static/v13_customer_documents.css','app/static/chen_foxmail_bootstrap.ps1','app/static/chen_foxmail_helper_v09.ps1','app/static/v123_foxmail_compose_fix.js','app/static/home-top-nav-v153.css','app/v143_payment_controls_patch.py','app/v143_customer_resources.py','app/v144_audit_hardening.py','app/work_architecture.py','app/v162_number_inbox.py','app/templates/work_shell_v14.html','app/templates/work_library_v14.html','app/templates/number_submit_v162.html','app/templates/number_inbox_v162.html','app/static/number-inbox-v162.css','app/static/number-inbox-v162.js','app/static/task-v164.css','tests/v164_task_review_contract.py','storage_node/app.py']:
    assert Path(path).is_file(),path
print('✓ v1.7.7 首页模块自定义 + 定时号码提醒 + 历史功能检查通过')
PY
if [[ -d data ]]; then chown "$SERVICE_USER:$SERVICE_GROUP" data; find data -maxdepth 1 -type f \( -name 'app.db' -o -name 'app.db-wal' -o -name 'app.db-shm' \) -exec chown "$SERVICE_USER:$SERVICE_GROUP" {} +; chmod u+rwx data; fi
if [[ -f scripts/install_win_assistants_asset_sync.sh ]]; then
  echo "→ 安装/刷新 win-assistants 更新资产同步定时器"
  bash scripts/install_win_assistants_asset_sync.sh
  echo "✓ win-assistants 更新资产同步定时器已刷新"
fi
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
FOXMAIL_CHANGED=0
for ASSET in chen_foxmail_bootstrap.ps1 chen_foxmail_helper_v09.ps1; do
  if grep -qx "app/static/$ASSET" "$CHANGED_FILE_LIST"; then
    TMP="$(mktemp)"
    curl -fsS "$APP_HTTP/static/$ASSET?deploy=$REV" -o "$TMP"
    [[ "$(sha256sum "app/static/$ASSET"|awk '{print $1}')" == "$(sha256sum "$TMP"|awk '{print $1}')" ]] || { echo "✗ Foxmail 助手资源不一致：$ASSET"; rm -f "$TMP"; exit 1; }
    rm -f "$TMP"
    FOXMAIL_CHANGED=1
  fi
done
if [[ "$FOXMAIL_CHANGED" -eq 1 ]]; then echo "✓ Foxmail v0.9 本次变更资源一致"; else echo "✓ Foxmail 助手未变化，跳过资源重复校验"; fi
if grep -q '^REMOTE_STORAGE_BASE_URL=' .env 2>/dev/null && grep -q '^REMOTE_STORAGE_TOKEN=' .env 2>/dev/null; then
  STORAGE_URL="$(grep '^REMOTE_STORAGE_BASE_URL=' .env | tail -n1 | cut -d= -f2-)"
  if [[ -n "$STORAGE_URL" ]]; then curl --max-time 5 -fsS "${STORAGE_URL%/}/health" >/dev/null && echo "✓ 远程资料存储通道在线" || echo "⚠ 远程资料存储已配置，但当前健康检查失败（5 秒超时，不阻塞部署）"; fi
else
  echo "ℹ 客户资料模块已安装；远程存储尚未配置时会在页面提示。"
fi
echo "===== 晨的助手 v${EXPECTED_VERSION} 更新完成 ====="; echo "代码：$(git rev-parse --short HEAD)"; echo "备份：${BACKUP_FILE:-无}"




