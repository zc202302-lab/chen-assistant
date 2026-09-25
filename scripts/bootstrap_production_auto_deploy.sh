#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${CHEN_ASSISTANT_DIR:-/opt/chen-assistant}"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "请使用 root 运行此脚本。"
  exit 1
fi

cd "$APP_DIR"
timeout 60s git fetch origin main production-ready
TARGET_REV="$(git rev-parse origin/production-ready)"
DEPLOY_SCRIPT="$(mktemp)"
trap 'rm -f "$DEPLOY_SCRIPT"' EXIT

git show "$TARGET_REV:deploy.sh" > "$DEPLOY_SCRIPT"
chmod 0700 "$DEPLOY_SCRIPT"

echo "→ 部署当前已验证 production-ready：$TARGET_REV"
CHEN_DEPLOY_TARGET_REV="$TARGET_REV" bash "$DEPLOY_SCRIPT"

echo "→ 安装/启用生产自动部署 timer"
bash "$APP_DIR/scripts/install_auto_deploy_timer.sh"

echo "→ 验证自动部署 timer"
systemctl is-enabled chen-assistant-auto-deploy.timer
systemctl is-active chen-assistant-auto-deploy.timer
systemctl list-timers --all --no-pager | grep -F 'chen-assistant-auto-deploy' || true

echo "→ 验证 Web 健康状态"
curl -fsS http://172.19.0.1:8010/health
echo

echo "✓ 晨的小助手生产自动部署 bootstrap 完成；今后 main 的 Web 运行时更新将由 timer 自动检查并部署。"
