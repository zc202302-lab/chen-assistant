#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${CHEN_ASSISTANT_DIR:-/opt/chen-assistant}"
SYNC_TARGET="/usr/local/sbin/chen-assistant-auto-deploy"
SERVICE_FILE="/etc/systemd/system/chen-assistant-auto-deploy.service"
TIMER_FILE="/etc/systemd/system/chen-assistant-auto-deploy.timer"
STATE_DIR="${CHEN_AUTO_DEPLOY_STATE_DIR:-/var/lib/chen-assistant-auto-deploy}"
SYNC_ONLY="${CHEN_AUTO_DEPLOY_SYNC_ONLY:-0}"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "请使用 root 运行此安装脚本。"
  exit 1
fi

cd "$APP_DIR"
mkdir -p "$STATE_DIR"
chmod 0755 "$STATE_DIR"

if [[ "$SYNC_ONLY" == "1" ]]; then
  install -m 0755 scripts/auto_deploy_main.sh "$SYNC_TARGET"
else
  timeout 60s git fetch --quiet origin main
  git show origin/main:scripts/auto_deploy_main.sh > "$SYNC_TARGET"
  chmod 0755 "$SYNC_TARGET"
fi

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Automatically deploy validated chen-assistant revisions
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
Environment=CHEN_ASSISTANT_DIR=$APP_DIR
Environment=CHEN_ASSISTANT_BRANCH=production-ready
Environment=CHEN_AUTO_DEPLOY_STATE_DIR=$STATE_DIR
ExecStart=$SYNC_TARGET
TimeoutStartSec=15min
EOF

cat > "$TIMER_FILE" <<'EOF'
[Unit]
Description=Periodically check validated chen-assistant revision for production deployment

[Timer]
OnBootSec=60s
OnUnitInactiveSec=2min
AccuracySec=15s
Persistent=true
Unit=chen-assistant-auto-deploy.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable chen-assistant-auto-deploy.timer >/dev/null

if [[ "$SYNC_ONLY" == "1" ]]; then
  systemctl restart chen-assistant-auto-deploy.timer
  echo "晨的小助手 Web 自动部署运行时已刷新；现有部署任务不被递归启动。"
  exit 0
fi

systemctl start chen-assistant-auto-deploy.timer
systemctl start chen-assistant-auto-deploy.service
systemctl --no-pager --full status chen-assistant-auto-deploy.service || true
systemctl list-timers --all --no-pager | grep -F 'chen-assistant-auto-deploy' || true

echo "晨的小助手 Web 自动部署已安装：只跟随 CI 验证后的 production-ready，任务结束约 2 分钟后再次检查。"
