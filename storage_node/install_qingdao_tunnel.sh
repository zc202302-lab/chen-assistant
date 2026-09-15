#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "请使用 root 运行此脚本。" >&2
  exit 1
fi

if [ "$#" -lt 1 ]; then
  echo "用法：bash install_qingdao_tunnel.sh <RackNerd存储Token> [RackNerd_IP]" >&2
  exit 1
fi

TOKEN="$1"
REMOTE_IP="${2:-172.245.54.13}"
LOCAL_PORT=18790
ENV_FILE=/opt/chen-assistant/.env
SERVICE=/etc/systemd/system/chen-storage-tunnel.service

if [ ! -f /root/.ssh/id_ed25519 ]; then
  ssh-keygen -t ed25519 -N '' -f /root/.ssh/id_ed25519
  echo
  echo "已生成青岛 ECS SSH 密钥。"
  echo "现在先执行：ssh-copy-id root@$REMOTE_IP"
  echo "输入一次 RackNerd root 密码完成授权后，再重新运行本脚本。"
  exit 2
fi

if ! ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new "root@$REMOTE_IP" 'true' >/dev/null 2>&1; then
  echo "青岛 ECS 还不能免密登录 RackNerd。" >&2
  echo "请先执行：ssh-copy-id root@$REMOTE_IP" >&2
  echo "完成后重新运行本脚本。" >&2
  exit 3
fi

cat > "$SERVICE" <<EOF
[Unit]
Description=Chen Assistant encrypted tunnel to RackNerd storage
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/ssh -NT \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o StrictHostKeyChecking=accept-new \
  -L 127.0.0.1:$LOCAL_PORT:127.0.0.1:$LOCAL_PORT root@$REMOTE_IP
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now chen-storage-tunnel
sleep 2
curl -fsS "http://127.0.0.1:$LOCAL_PORT/health" >/dev/null

python3 - "$ENV_FILE" "$TOKEN" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
token = sys.argv[2]
text = path.read_text(encoding='utf-8') if path.exists() else ''
updates = {
    'REMOTE_STORAGE_BASE_URL': 'http://127.0.0.1:18790',
    'REMOTE_STORAGE_TOKEN': token,
    'REMOTE_STORAGE_MAX_FILE_MB': '50',
}
lines = text.splitlines()
seen = set()
out = []
for line in lines:
    if '=' in line and not line.lstrip().startswith('#'):
        key = line.split('=', 1)[0].strip()
        if key in updates:
            out.append(f'{key}={updates[key]}')
            seen.add(key)
            continue
    out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(f'{key}={value}')
path.write_text('\n'.join(out).rstrip() + '\n', encoding='utf-8')
PY

chmod 600 "$ENV_FILE"
systemctl restart chen-assistant
sleep 2

echo
echo "===== 青岛 ECS → RackNerd 加密存储通道已完成 ====="
echo "本机入口：http://127.0.0.1:$LOCAL_PORT"
echo "SSH通道：青岛 ECS → $REMOTE_IP → RackNerd 127.0.0.1:$LOCAL_PORT"
echo "已写入 $ENV_FILE 并重启 chen-assistant"
