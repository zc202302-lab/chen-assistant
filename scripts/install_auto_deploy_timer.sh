#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${CHEN_ASSISTANT_DIR:-/opt/chen-assistant}"
SYNC_TARGET="/usr/local/sbin/chen-assistant-auto-deploy"
SERVICE_FILE="/etc/systemd/system/chen-assistant-auto-deploy.service"
TIMER_FILE="/etc/systemd/system/chen-assistant-auto-deploy.timer"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "请使用 root 运行此安装脚本。"
  exit 1
fi

cd "$APP_DIR"
git fetch --quiet origin main
git show origin/main:scripts/auto_deploy_main.sh > "$SYNC_TARGET"
chmod 0755 "$SYNC_TARGET"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Automatically deploy validated chen-assistant main updates
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
Environment=CHEN_ASSISTANT_DIR=$APP_DIR
ExecStart=$SYNC_TARGET
EOF

cat > "$TIMER_FILE" <<'EOF'
[Unit]
Description=Periodically check chen-assistant main for production deployment

[Timer]
OnBootSec=60s
OnUnitActiveSec=2min
AccuracySec=20s
Persistent=true
Unit=chen-assistant-auto-deploy.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now chen-assistant-auto-deploy.timer
systemctl start chen-assistant-auto-deploy.service
systemctl --no-pager --full status chen-assistant-auto-deploy.service || true
systemctl list-timers --all --no-pager | grep -F 'chen-assistant-auto-deploy' || true

echo "晨的小助手 Web 自动部署已安装：main 更新后最多约 2 分钟自动检查并部署。"
