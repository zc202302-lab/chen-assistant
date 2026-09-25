#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${REPO_URL:-https://github.com/zc202302-lab/chen-assistant}"
RUNNER_NAME="${RUNNER_NAME:-chen-assistant-ci-192-255-130-71}"
RUNNER_LABELS="${RUNNER_LABELS:-chen-assistant}"
RUNNER_USER="${RUNNER_USER:-ghrunner}"
RUNNER_HOME="${RUNNER_HOME:-/opt/actions-runner}"
RUNNER_TOKEN="${RUNNER_TOKEN:-}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this installer as root." >&2
  exit 1
fi

if [[ -z "$RUNNER_TOKEN" ]]; then
  cat >&2 <<'EOF'
RUNNER_TOKEN is required.
Generate it in GitHub:
Settings -> Actions -> Runners -> New self-hosted runner -> Linux -> x64.
Then run:
  RUNNER_TOKEN='...' sudo -E bash scripts/bootstrap_self_hosted_runner.sh
The registration token is short-lived; do not commit it.
EOF
  exit 2
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This bootstrap currently supports Debian/Ubuntu servers (apt-get required)." >&2
  exit 3
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y   ca-certificates curl git jq tar xz-utils unzip file   python3 python3-pip python3-venv   build-essential libicu-dev

if ! id "$RUNNER_USER" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "$RUNNER_USER"
fi

mkdir -p "$RUNNER_HOME"
chown -R "$RUNNER_USER:$RUNNER_USER" "$RUNNER_HOME"

arch="$(uname -m)"
case "$arch" in
  x86_64|amd64) runner_arch="x64" ;;
  aarch64|arm64) runner_arch="arm64" ;;
  *)
    echo "Unsupported architecture: $arch" >&2
    exit 4
    ;;
esac

release_json="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest)"
runner_version="$(jq -r '.tag_name' <<<"$release_json" | sed 's/^v//')"
asset_name="actions-runner-linux-${runner_arch}-${runner_version}.tar.gz"
asset_url="$(jq -r --arg n "$asset_name" '.assets[] | select(.name==$n) | .browser_download_url' <<<"$release_json")"

if [[ -z "$asset_url" || "$asset_url" == "null" ]]; then
  echo "Unable to resolve current GitHub Actions runner asset: $asset_name" >&2
  exit 5
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -fL --retry 3 -o "$tmp/$asset_name" "$asset_url"

systemctl stop "actions.runner."* 2>/dev/null || true

rm -rf "$RUNNER_HOME"/*
tar -xzf "$tmp/$asset_name" -C "$RUNNER_HOME"
chown -R "$RUNNER_USER:$RUNNER_USER" "$RUNNER_HOME"

cd "$RUNNER_HOME"
./bin/installdependencies.sh

sudo -u "$RUNNER_USER"   ./config.sh   --unattended   --url "$REPO_URL"   --token "$RUNNER_TOKEN"   --name "$RUNNER_NAME"   --labels "$RUNNER_LABELS"   --work "_work"   --replace

./svc.sh install "$RUNNER_USER"
./svc.sh start

# Pre-install Chromium system libraries required by the repository's
# Playwright browser acceptance suite. Browser binaries themselves are
# installed by each workflow run.
pwvenv="$(mktemp -d)"
python3 -m venv "$pwvenv"
"$pwvenv/bin/pip" install --quiet --upgrade pip
"$pwvenv/bin/pip" install --quiet playwright
"$pwvenv/bin/python" -m playwright install-deps chromium
rm -rf "$pwvenv"

echo
echo "Runner service status:"
./svc.sh status
echo
echo "Expected GitHub labels: self-hosted, linux, ${runner_arch}, ${RUNNER_LABELS}"
echo "Runner name: $RUNNER_NAME"
echo "Migration host: 192.255.130.71"
