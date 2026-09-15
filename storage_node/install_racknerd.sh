#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "请使用 root 运行此脚本。" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR=/opt/chen-storage
DATA_DIR=/data/chen-files
ENV_FILE=/etc/chen-storage.env
SERVICE=/etc/systemd/system/chen-storage.service
PORT=18790

if ! command -v python3 >/dev/null 2>&1; then
  echo "未找到 python3。" >&2
  exit 1
fi

if ! python3 -m venv --help >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    apt-get install -y python3-venv
  else
    echo "缺少 python3-venv，请先安装。" >&2
    exit 1
  fi
fi

mkdir -p "$APP_DIR" "$DATA_DIR"
cp "$SCRIPT_DIR/app.py" "$APP_DIR/app.py"
cp "$SCRIPT_DIR/requirements.txt" "$APP_DIR/requirements.txt"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip >/dev/null
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [ -f "$ENV_FILE" ] && grep -q '^CHEN_STORAGE_TOKEN=' "$ENV_FILE"; then
  TOKEN="$(grep '^CHEN_STORAGE_TOKEN=' "$ENV_FILE" | head -n1 | cut -d= -f2-)"
else
  TOKEN="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
fi

cat > "$ENV_FILE" <<EOF
CHEN_STORAGE_ROOT=$DATA_DIR
CHEN_STORAGE_TOKEN=$TOKEN
CHEN_STORAGE_MAX_FILE_MB=50
EOF
chmod 600 "$ENV_FILE"

cat > "$SERVICE" <<EOF
[Unit]
Description=Chen Assistant Private Storage
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=$ENV_FILE
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/uvicorn app:app --host 127.0.0.1 --port $PORT
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=$DATA_DIR

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now chen-storage
sleep 1
curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null

echo
echo "===== RackNerd 私有资料存储安装完成 ====="
echo "监听地址：127.0.0.1:$PORT（没有暴露公网端口）"
echo "文件目录：$DATA_DIR"
echo "服务：chen-storage"
echo
echo "请保存下面的 Token，下一步需要填到青岛 ECS："
echo "$TOKEN"
