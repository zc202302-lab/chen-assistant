#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/opt/chen-assistant"
SERVICE="chen-assistant"
HEALTH_URL="http://172.19.0.1:8010/health"
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
.venv/bin/python - <<'PY'
from jinja2 import Environment, FileSystemLoader
from app import config
from app.main import app

env = Environment(loader=FileSystemLoader(str(config.ROOT / 'app' / 'templates')))
for name in ('base.html', 'dashboard_v026.html', 'customer_workspace_v026.html'):
    env.get_template(name)
assert app.version == '0.2.6', f'预期 v0.2.6，实际 v{app.version}'
print(f"✓ Python / 路由 / 模板检查通过：v{app.version}")
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
if payload.get('version') != '0.2.6':
    raise SystemExit(f"版本不匹配：{payload.get('version')}")
print(f"✓ 服务版本：{payload.get('version')}")
PY

echo "✓ 服务健康检查通过"
echo "更新后代码：$(git rev-parse --short HEAD)"
echo "===== 更新完成 ====="
