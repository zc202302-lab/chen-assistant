#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/opt/chen-assistant"
SERVICE="chen-assistant"
APP_HTTP="http://172.19.0.1:8010"
HEALTH_URL="$APP_HTTP/health"
BACKUP_DIR="$APP_DIR/backups"

cd "$APP_DIR"

echo "===== 晨的助手一键更新 ====="

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "✗ 检测到服务器上的受 Git 管理文件有本地修改，已停止更新。"
  echo "请先处理 git status 显示的修改，避免覆盖。"
  exit 1
fi

mkdir -p "$BACKUP_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_FILE="$BACKUP_DIR/app.db.$TS"

if [[ -f data/app.db ]]; then
  .venv/bin/python - "$BACKUP_FILE" <<'PY'
import sqlite3, sys
from pathlib import Path
src = Path('data/app.db')
dst = Path(sys.argv[1])
dst.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d)
print(f"✓ 数据库已备份：{dst}")
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
  node --check app/static/v028.js
fi
.venv/bin/python - <<'PY'
from jinja2 import Environment, FileSystemLoader
from app import config
from app.main import app

env = Environment(loader=FileSystemLoader(str(config.ROOT / 'app' / 'templates')))
for name in ('base.html', 'dashboard_v027.html', 'customer_workspace_v028.html'):
    env.get_template(name)
assert app.version == '0.2.8', f'预期 v0.2.8，实际 v{app.version}'

for path in ('/', '/customers/{customer_id}', '/health'):
    matches = [r for r in app.router.routes if getattr(r, 'path', '') == path]
    assert len(matches) == 1, f'{path} 路由数量异常：{len(matches)}'

customer_route = next(r for r in app.router.routes if getattr(r, 'path', '') == '/customers/{customer_id}')
assert getattr(customer_route.endpoint, '__module__', '') == 'app.v028_routes', '客户页未由 v0.2.8 接管'
base = (config.ROOT / 'app' / 'templates' / 'base.html').read_text(encoding='utf-8')
assert base.count('/static/v028.js') == 1, 'v028.js 必须且只能加载一次'
for old in ('/static/current.js', '/static/v025.js', '/static/v025_minor.js', '/static/v026.js', '/static/v027.js'):
    assert old not in base, f'检测到旧客户页控制器仍在加载：{old}'
assert (config.ROOT / 'app' / 'static' / 'v028.js').is_file(), '缺少 v028.js'
print(f"✓ Python / 路由 / 模板 / 单控制器检查通过：v{app.version}")
PY

.venv/bin/python -c 'from app.db import init_db; init_db(); print("✓ 数据库结构检查/迁移完成")'

systemctl restart "$SERVICE"
sleep 3

HEALTH_JSON="$(curl -fsS "$HEALTH_URL")"
echo "$HEALTH_JSON"

.venv/bin/python - "$HEALTH_JSON" <<'PY'
import json, sys
payload = json.loads(sys.argv[1])
if payload.get('ok') is not True:
    raise SystemExit('健康检查返回 ok=false')
if payload.get('version') != '0.2.8':
    raise SystemExit(f"版本不匹配：{payload.get('version')}")
print(f"✓ 服务版本：{payload.get('version')}")
PY

echo "===== 已运行静态文件一致性检查 ====="
REV="$(git rev-parse --short HEAD)"
for ASSET in app.js v028.js v028.css; do
  LOCAL_FILE="app/static/$ASSET"
  TMP_FILE="$(mktemp)"
  curl -fsS "$APP_HTTP/static/$ASSET?deploy=$REV" -o "$TMP_FILE"
  LOCAL_SHA="$(sha256sum "$LOCAL_FILE" | awk '{print $1}')"
  SERVED_SHA="$(sha256sum "$TMP_FILE" | awk '{print $1}')"
  rm -f "$TMP_FILE"
  if [[ "$LOCAL_SHA" != "$SERVED_SHA" ]]; then
    echo "✗ 正式服务返回的 $ASSET 与本地部署文件不一致"
    echo "  本地：$LOCAL_SHA"
    echo "  服务：$SERVED_SHA"
    exit 1
  fi
  echo "✓ $ASSET：正式服务与Git工作区一致"
done

CACHE_HEADER="$(curl -fsSI "$APP_HTTP/static/v028.js?deploy=$REV" | tr -d '\r' | awk 'BEGIN{IGNORECASE=1} /^Cache-Control:/{sub(/^[^:]*:[ ]*/,""); print; exit}')"
case "$CACHE_HEADER" in
  *no-store*) echo "✓ v028.js 禁止浏览器缓存旧控制器" ;;
  *) echo "✗ v028.js 缓存策略异常：${CACHE_HEADER:-未返回 Cache-Control}"; exit 1 ;;
esac

echo "✓ 服务健康检查通过"
echo "更新后代码：$REV"
echo "===== 更新完成 ====="
