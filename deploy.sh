#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/opt/chen-assistant"
SERVICE="chen-assistant"
APP_HTTP="http://172.19.0.1:8010"
HEALTH_URL="$APP_HTTP/health"
BACKUP_DIR="$APP_DIR/backups"
EXPECTED_VERSION="1.0"

cd "$APP_DIR"
echo "===== 晨的助手 v${EXPECTED_VERSION} 一键更新 ====="

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "✗ 检测到服务器受 Git 管理文件有本地修改，已停止更新。"
  git status --short
  exit 1
fi

SERVICE_USER="$(systemctl show "$SERVICE" -p User --value)"; [[ -n "$SERVICE_USER" ]] || SERVICE_USER="root"
SERVICE_GROUP="$(systemctl show "$SERVICE" -p Group --value)"; [[ -n "$SERVICE_GROUP" ]] || SERVICE_GROUP="$SERVICE_USER"
mkdir -p "$BACKUP_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_FILE="$BACKUP_DIR/app.db.$TS"
if [[ -f data/app.db ]]; then
  .venv/bin/python - "$BACKUP_FILE" <<'PY'
import sqlite3,sys
from pathlib import Path
src=Path('data/app.db'); dst=Path(sys.argv[1])
with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d)
    assert d.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
print(f'✓ 数据库备份完成：{dst}')
PY
fi

OLD_COMMIT="$(git rev-parse --short HEAD)"
echo "当前代码：$OLD_COMMIT"
git fetch origin main
git merge --ff-only origin/main
.venv/bin/pip install -q -r requirements.txt

echo "===== 更新后代码检查 ====="
.venv/bin/python -m compileall -q app
if command -v node >/dev/null 2>&1; then
  for ASSET in app.js v028.js ui-drag.js service-promotions.js business-sync.js v0211.js workspace-refinement-v0212.js v03.js v03_runtime_fix.js v03_business_mail.js v03_payment_template.js v03_foxmail_action_fix.js v03_insert_order.js v03_review_reset.js v031_payment_workflow.js v031_amount_rollback_fix.js v031_workflow_actions.js v031_workflow_runtime_fix.js v031_workflow_dom_guard.js v031_windows_bootstrap.js v033_payment_flow_patch.js v10.js; do
    node --check "app/static/$ASSET"
  done
fi

.venv/bin/python - "$EXPECTED_VERSION" <<'PY'
from jinja2 import Environment,FileSystemLoader
import sys
from app import config
from app.main import app
from app.v10_routes import ensure_v10_schema
expected=sys.argv[1]
assert app.version==expected,(app.version,expected)
ensure_v10_schema()
expected_routes={
 ('GET','/'):'app.v10_routes',('GET','/search'):'app.v10_routes',('GET','/work'):'app.v10_routes',
 ('GET','/life'):'app.v10_routes',('GET','/life/recipes'):'app.v10_routes',('GET','/life/records'):'app.v10_routes',
 ('GET','/life/knowledge'):'app.v10_routes',
 ('GET','/customers/{customer_id}'):'app.v0212_routes',
 ('POST','/services/{service_id}/payment-current'):'app.v031_fixed_review_patch',
 ('POST','/services/{service_id}/payment-review-toggle'):'app.v031_fixed_review_patch',
 ('GET','/customers/{customer_id}/payment.txt'):'app.v033_payment_flow_patch',
 ('GET','/customers/{customer_id}/payment-mail-compose-v031'):'app.v033_payment_flow_patch',
}
for (method,path),module in expected_routes.items():
    matches=[r for r in app.router.routes if getattr(r,'path','')==path and method in getattr(r,'methods',set())]
    assert matches,(method,path)
    assert matches[0].endpoint.__module__==module,(method,path,matches[0].endpoint.__module__)
env=Environment(loader=FileSystemLoader(str(config.ROOT/'app'/'templates')))
for name in ('base.html','home_v10.html','work_home_v10.html','life_home_v10.html','search_v10.html','recipe_list_v10.html','recipe_detail_v10.html','recipe_edit_v10.html','recipe_versions_v10.html','cook_mode_v10.html','cook_complete_v10.html','cook_records_v10.html','cook_record_detail_v10.html','knowledge_list_v10.html','knowledge_edit_v10.html','customer_workspace_v0211.html'):
    env.get_template(name)
base=(config.ROOT/'app'/'templates'/'base.html').read_text(encoding='utf-8')
for token in ('v1.0','href="/work"','href="/life"','/static/v10.css?v=1000','/static/v10.js?v=1000'):
    assert token in base,token
for asset in ('v10.js','v10.css','v033_payment_flow_patch.js','chen_foxmail_helper.ps1'):
    assert (config.ROOT/'app'/'static'/asset).is_file(),asset
print('✓ v1.0 Python / 路由 / 模板 / 资源检查通过')
PY

echo "===== 数据库结构迁移 ====="
.venv/bin/python - <<'PY'
from app.db import init_db,db
from app.v03_routes import _ensure_v03
from app.v03_mail_draft_routes import _ensure_mail_templates
from app.v031_payment_workflow_routes import ensure_v031
from app.v033_payment_flow_patch import _ensure_customer_payment_template
from app.v10_routes import ensure_v10_schema
init_db()
with db() as conn:
    _ensure_v03(conn); _ensure_mail_templates(conn); ensure_v031(conn); _ensure_customer_payment_template(conn); ensure_v10_schema(conn)
    recipes=conn.execute('SELECT COUNT(*) FROM recipes').fetchone()[0]
    knowledge=conn.execute('SELECT COUNT(*) FROM cooking_knowledge').fetchone()[0]
print(f'✓ v1.0 数据结构完成：菜谱 {recipes}，知识 {knowledge}')
PY

if [[ -d data ]]; then
  chown "$SERVICE_USER:$SERVICE_GROUP" data
  find data -maxdepth 1 -type f \( -name 'app.db' -o -name 'app.db-wal' -o -name 'app.db-shm' \) -exec chown "$SERVICE_USER:$SERVICE_GROUP" {} +
  chmod u+rwx data
  find data -maxdepth 1 -type f \( -name 'app.db' -o -name 'app.db-wal' -o -name 'app.db-shm' \) -exec chmod u+rw {} +
fi

if [[ -f "$BACKUP_FILE" && -f data/app.db ]]; then
  .venv/bin/python - "$BACKUP_FILE" data/app.db <<'PY'
import sqlite3,sys
def stat(path):
    c=sqlite3.connect(f'file:{path}?mode=ro',uri=True)
    try:return c.execute('PRAGMA integrity_check').fetchone()[0],c.execute('SELECT COUNT(*) FROM customers').fetchone()[0],c.execute('SELECT COUNT(*) FROM services').fetchone()[0]
    finally:c.close()
before,after=stat(sys.argv[1]),stat(sys.argv[2])
assert before[0]=='ok' and after[0]=='ok'
assert after[1]>=before[1] and after[2]>=before[2],(before,after)
print(f'✓ 生产数据安全核对通过：客户 {after[1]}，业务 {after[2]}')
PY
fi

systemctl restart "$SERVICE"
sleep 3
HEALTH_JSON="$(curl -fsS "$HEALTH_URL")"
echo "$HEALTH_JSON"
.venv/bin/python - "$HEALTH_JSON" "$EXPECTED_VERSION" <<'PY'
import json,sys
p=json.loads(sys.argv[1]); expected=sys.argv[2]
assert p.get('ok') is True,p
assert p.get('version')==expected,(p,expected)
print(f"✓ 服务版本：{p['version']}")
PY

REV="$(git rev-parse --short HEAD)"
for ASSET in v10.js v10.css v033_payment_flow_patch.js app.css; do
  TMP="$(mktemp)"; curl -fsS "$APP_HTTP/static/$ASSET?deploy=$REV" -o "$TMP"
  [[ "$(sha256sum app/static/$ASSET|awk '{print $1}')" == "$(sha256sum "$TMP"|awk '{print $1}')" ]] || { echo "✗ 静态资源不一致：$ASSET"; rm -f "$TMP"; exit 1; }
  rm -f "$TMP"
done

echo "✓ 静态资源一致"
echo "===== 晨的助手 v${EXPECTED_VERSION} 更新完成 ====="
echo "代码：$(git rev-parse --short HEAD)"
echo "备份：${BACKUP_FILE:-无}"
