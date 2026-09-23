#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${CHEN_ASSISTANT_DIR:-/opt/chen-assistant}"
SYNC_TARGET="/usr/local/sbin/chen-win-assistants-sync"
SERVICE_FILE="/etc/systemd/system/chen-win-assistants-sync.service"
TIMER_FILE="/etc/systemd/system/chen-win-assistants-sync.timer"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "请使用 root 运行此安装脚本。"
  exit 1
fi

cd "$APP_DIR"
git fetch --quiet origin main
git show origin/main:scripts/sync_win_assistants_assets.sh > "$SYNC_TARGET"
chmod 0755 "$SYNC_TARGET"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Sync win-assistants updater assets from GitHub release branch
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
Environment=CHEN_ASSISTANT_DIR=$APP_DIR
ExecStart=$SYNC_TARGET
EOF

cat > "$TIMER_FILE" <<'EOF'
[Unit]
Description=Periodically sync win-assistants updater assets

[Timer]
OnBootSec=45s
OnUnitActiveSec=2min
AccuracySec=20s
Persistent=true
Unit=chen-win-assistants-sync.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now chen-win-assistants-sync.timer
systemctl start chen-win-assistants-sync.service
systemctl --no-pager --full status chen-win-assistants-sync.service || true
systemctl list-timers --all --no-pager | grep -F 'chen-win-assistants-sync' || true

echo "win-assistants 更新资产自动同步已安装；不会切换 Web main，也不会重启 chen-assistant 服务。"
