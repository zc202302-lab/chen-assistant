#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/opt/chen-assistant"
SERVICE="chen-assistant"
APP_HTTP="http://172.19.0.1:8010"
HEALTH_URL="$APP_HTTP/health"
BACKUP_DIR="$APP_DIR/backups"

cd "$APP_DIR"
echo "===== 晨的助手 v0.3 一键更新 ====="

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "✗ 检测到服务器上的受 Git 管理文件有本地修改，已停止更新。"
  echo "请先处理 git status 显示的修改，避免覆盖。"
  exit 1
fi

SERVICE_USER="$(systemctl show "$SERVICE" -p User --value)"
SERVICE_GROUP="$(systemctl show "$SERVICE" -p Group --value)"
[[ -n "$SERVICE_USER" ]] || SERVICE_USER="root"
[[ -n "$SERVICE_GROUP" ]] || SERVICE_GROUP="$SERVICE_USER"
echo "服务运行账户：$SERVICE_USER:$SERVICE_GROUP"

mkdir -p "$BACKUP_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_FILE="$BACKUP_DIR/app.db.$TS"
if [[ -f data/app.db ]]; then
  .venv/bin/python - "$BACKUP_FILE" <<'PY'
import sqlite3, sys
from pathlib import Path
src=Path('data/app.db'); dst=Path(sys.argv[1]); dst.parent.mkdir(parents=True,exist_ok=True)
with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d)
    if d.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise SystemExit('数据库备份完整性检查失败')
print(f"✓ 数据库已备份并通过完整性检查：{dst}")
PY
else
  echo "! 未发现 data/app.db，本次跳过数据库备份"
fi

OLD_COMMIT="$(git rev-parse --short HEAD)"
echo "当前代码：$OLD_COMMIT"
git fetch origin main
git merge --ff-only origin/main
.venv/bin/pip install -q -r requirements.txt

echo "===== 更新前代码检查 ====="
.venv/bin/python -m compileall -q app
if command -v node >/dev/null 2>&1; then
  for ASSET in app.js v028.js ui-drag.js service-promotions.js business-sync.js v0211.js workspace-refinement-v0212.js v03.js v03_runtime_fix.js v03_business_mail.js v03_payment_template.js v03_foxmail_action_fix.js v03_insert_order.js v03_review_reset.js; do
    node --check "app/static/$ASSET"
  done
fi

.venv/bin/python - <<'PY'
from jinja2 import Environment, FileSystemLoader
from app import config
from app.main import app

env=Environment(loader=FileSystemLoader(str(config.ROOT/'app'/'templates')))
runtime_templates=('base.html','dashboard_v027.html','customer_workspace_v0211.html','account_detail.html','account_form.html','accounts.html','customer_form.html','login.html','search.html')
for name in runtime_templates:
    p=config.ROOT/'app'/'templates'/name
    if not p.exists():
        continue
    env.get_template(name)
    text=p.read_text(encoding='utf-8')
    assert 'type="date"' not in text and "type='date'" not in text, f'{name} 仍包含日期选择器'

assert app.version=='0.3',f'预期 v0.3，实际 v{app.version}'
for path in ('/','/customers/{customer_id}','/health'):
    matches=[r for r in app.router.routes if getattr(r,'path','')==path]
    assert len(matches)==1,f'{path} 路由数量异常：{len(matches)}'
customer_route=next(r for r in app.router.routes if getattr(r,'path','')=='/customers/{customer_id}')
assert getattr(customer_route.endpoint,'__module__','')=='app.v0212_routes','客户工作区渲染路由异常'

owned={
    ('/customers/{customer_id}/payment-run','POST'):'app.v03_payment_routes',
    ('/customers/{customer_id}/payment-run-v03','GET'):'app.v03_routes',
    ('/customers/{customer_id}/workflow-state-v03','GET'):'app.v031_runtime_routes',
    ('/customers/{customer_id}/payment-email-v03','POST'):'app.v03_routes',
    ('/customers/{customer_id}/mail-template-v03','GET'):'app.v03_mail_draft_routes',
    ('/customers/{customer_id}/mail-template-v03','POST'):'app.v03_mail_draft_routes',
    ('/customers/{customer_id}/payment-mail-compose-v03','GET'):'app.v03_mail_draft_routes',
    ('/customers/{customer_id}/payment-mail-draft-v03','GET'):'app.v03_mail_draft_routes',
    ('/services/{service_id}/status-v03','POST'):'app.v03_mail_draft_routes',
    ('/services/{service_id}/payment-status-v03','POST'):'app.v03_mail_draft_routes',
    ('/customers/{customer_id}/payment.txt','GET'):'app.v0212_routes',
    ('/services/{service_id}/defer-v0212','POST'):'app.v0212_routes',
    ('/services/{service_id}/delete-v0212','POST'):'app.v0212_routes',
    ('/customers/{customer_id}/business-columns-v0212','POST'):'app.v0212_business_display_routes',
}
for (path,method),module in owned.items():
    matches=[r for r in app.router.routes if getattr(r,'path','')==path and method in getattr(r,'methods',set())]
    assert matches,f'缺少 v0.3 核心路由：{path} {method}'
    assert getattr(matches[0].endpoint,'__module__','')==module,f'{path} 未由预期 v0.3 路由接管：{matches[0].endpoint.__module__}'

base=(config.ROOT/'app'/'templates'/'base.html').read_text(encoding='utf-8')
current_assets=(
    '/static/app.js','/static/v028.js','/static/ui-drag.js','/static/service-promotions.js',
    '/static/business-sync.js','/static/v0211.js','/static/workspace-refinement-v0212.js','/static/v03.js',
    '/static/v03_runtime_fix.js','/static/v03_business_mail.js','/static/v03_payment_template.js',
    '/static/v03_foxmail_action_fix.js','/static/v03_insert_order.js','/static/v03_review_reset.js',
    '/static/app.css','/static/v028.css','/static/layout-refinement.css','/static/v0212.css',
    '/static/workspace-refinement-v0212.css','/static/v03.css','/static/v03_business_mail.css',
    '/static/v03_payment_template.css',
)
for current in current_assets:
    assert base.count(current)==1,f'{current} 必须且只能加载一次'
for retired in ('/static/v0212.js','/static/business-editor-hotfix.js','/static/current.js','/static/v025.js','/static/v026.js','/static/v027.js'):
    assert retired not in base,f'检测到已退役前端资源仍在运行：{retired}'
for asset in (
    'app.js','v028.js','ui-drag.js','service-promotions.js','business-sync.js','v0211.js',
    'workspace-refinement-v0212.js','v03.js','v03_runtime_fix.js','v03_business_mail.js','v03_payment_template.js',
    'v03_foxmail_action_fix.js','v03_insert_order.js','v03_review_reset.js',
    'app.css','v028.css','layout-refinement.css','v0212.css','workspace-refinement-v0212.css','v03.css','v03_business_mail.css',
    'v03_payment_template.css','chen_foxmail_helper.ps1',
):
    assert (config.ROOT/'app'/'static'/asset).is_file(),f'缺少 {asset}'
print(f"✓ Python / 路由 / 模板 / v0.3 前端资源检查通过：v{app.version}")
PY

echo "===== 数据库结构与 v0.3 安全迁移 ====="
.venv/bin/python - <<'PY'
from app.db import init_db, db
from app.v03_routes import _ensure_v03
from app.v03_mail_draft_routes import _ensure_mail_templates
init_db()
with db() as conn:
    _ensure_v03(conn)
    _ensure_mail_templates(conn)
print('✓ v0.3 数据库结构检查/迁移完成')
PY

# deploy.sh 由 root 执行数据库迁移时，SQLite 主文件可能保留/变成 root 所有，
# 而正式服务以专用用户运行。每次迁移后都把 data 目录及 SQLite 文件归还给服务账户。
if [[ -d data ]]; then
  chown "$SERVICE_USER:$SERVICE_GROUP" data
  find data -maxdepth 1 -type f \( -name 'app.db' -o -name 'app.db-wal' -o -name 'app.db-shm' \) \
    -exec chown "$SERVICE_USER:$SERVICE_GROUP" {} +
  chmod u+rwx data
  find data -maxdepth 1 -type f \( -name 'app.db' -o -name 'app.db-wal' -o -name 'app.db-shm' \) \
    -exec chmod u+rw {} +
  echo "✓ SQLite 权限已校正：$SERVICE_USER:$SERVICE_GROUP"
fi

# 生产部署绝不执行 tests/ 下的测试程序。完整测试只在 GitHub CI 的隔离环境运行。
# 此处只对生产库做只读安全核对：完整性必须正常，且客户/业务数量不得少于部署前备份。
if [[ -f "$BACKUP_FILE" && -f data/app.db ]]; then
  .venv/bin/python - "$BACKUP_FILE" data/app.db <<'PY'
import sqlite3, sys

def stats(path):
    con=sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        integrity=con.execute('PRAGMA integrity_check').fetchone()[0]
        customers=con.execute('SELECT COUNT(*) FROM customers').fetchone()[0]
        services=con.execute('SELECT COUNT(*) FROM services').fetchone()[0]
        return integrity, customers, services
    finally:
        con.close()

before=stats(sys.argv[1]); after=stats(sys.argv[2])
print(f'部署前备份：完整性={before[0]} 客户={before[1]} 业务={before[2]}')
print(f'迁移后生产库：完整性={after[0]} 客户={after[1]} 业务={after[2]}')
if before[0] != 'ok' or after[0] != 'ok':
    raise SystemExit('✗ SQLite 完整性检查失败，停止部署')
if after[1] < before[1] or after[2] < before[2]:
    raise SystemExit('✗ 检测到生产客户/业务数量减少，停止部署；请使用本次部署前备份检查数据')
print('✓ 生产数据库安全核对通过')
PY
fi

echo "✓ 生产服务器不运行 tests/ 测试套件；完整自动测试由 GitHub CI 隔离执行"

systemctl restart "$SERVICE"
sleep 3
HEALTH_JSON="$(curl -fsS "$HEALTH_URL")"
echo "$HEALTH_JSON"
.venv/bin/python - "$HEALTH_JSON" <<'PY'
import json,sys
p=json.loads(sys.argv[1])
if p.get('ok') is not True: raise SystemExit('健康检查返回 ok=false')
if p.get('version')!='0.3': raise SystemExit(f"版本不匹配：{p.get('version')}")
print(f"✓ 服务版本：{p.get('version')}")
PY

echo "===== 已运行静态文件一致性检查 ====="
REV="$(git rev-parse --short HEAD)"
for ASSET in app.js v028.js ui-drag.js service-promotions.js business-sync.js v0211.js workspace-refinement-v0212.js v03.js v03_runtime_fix.js v03_business_mail.js v03_payment_template.js v03_foxmail_action_fix.js v03_insert_order.js v03_review_reset.js app.css v028.css layout-refinement.css v0212.css workspace-refinement-v0212.css v03.css v03_business_mail.css v03_payment_template.css chen_foxmail_helper.ps1; do
  LOCAL_FILE="app/static/$ASSET"; TMP_FILE="$(mktemp)"
  curl -fsS "$APP_HTTP/static/$ASSET?deploy=$REV" -o "$TMP_FILE"
  LOCAL_SHA="$(sha256sum "$LOCAL_FILE"|awk '{print $1}')"; SERVED_SHA="$(sha256sum "$TMP_FILE"|awk '{print $1}')"; rm -f "$TMP_FILE"
  if [[ "$LOCAL_SHA" != "$SERVED_SHA" ]]; then
    echo "✗ 正式服务返回的 $ASSET 与本地部署文件不一致"; exit 1
  fi
  echo "✓ $ASSET：正式服务与 Git 工作区一致"
done

for ASSET in app.js v028.js ui-drag.js service-promotions.js business-sync.js v0211.js workspace-refinement-v0212.js v03.js v03_runtime_fix.js v03_business_mail.js v03_payment_template.js v03_foxmail_action_fix.js v03_insert_order.js v03_review_reset.js; do
  CACHE_HEADER="$(curl -fsSI "$APP_HTTP/static/$ASSET?deploy=$REV" | tr -d '\r' | awk 'BEGIN{IGNORECASE=1} /^Cache-Control:/{sub(/^[^:]*:[ ]*/,""); print; exit}')"
  case "$CACHE_HEADER" in
    *no-store*) echo "✓ $ASSET 禁止浏览器缓存旧控制代码" ;;
    *) echo "✗ $ASSET 缓存策略异常：${CACHE_HEADER:-未返回 Cache-Control}"; exit 1 ;;
  esac
done

echo "✓ v0.3 服务健康检查通过"
echo "更新后代码：$REV"
echo "===== v0.3 更新完成 ====="