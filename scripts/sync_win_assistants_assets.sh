#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${CHEN_ASSISTANT_DIR:-/opt/chen-assistant}"
REMOTE="${CHEN_ASSISTANT_REMOTE:-origin}"
RELEASE_BRANCH="${WIN_ASSISTANTS_RELEASE_BRANCH:-win-assistants-release}"
TARGET_DIR="$APP_DIR/app/static/win-assistants"
PUBLIC_BASE="${WIN_ASSISTANTS_PUBLIC_BASE:-https://assistant.ziboxiaozhushou.cn/static/win-assistants}"

cd "$APP_DIR"

git fetch --quiet "$REMOTE" "refs/heads/$RELEASE_BRANCH:refs/remotes/$REMOTE/$RELEASE_BRANCH"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

git show "$REMOTE/$RELEASE_BRANCH:win-assistants.exe" > "$tmp_dir/win-assistants.exe"
git show "$REMOTE/$RELEASE_BRANCH:update.json" > "$tmp_dir/update.json"

python3 - "$tmp_dir/update.json" "$tmp_dir/win-assistants.exe" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
exe_path = Path(sys.argv[2])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
exe = exe_path.read_bytes()
sha = hashlib.sha256(exe).hexdigest()
size = len(exe)
assert manifest.get("version"), manifest
assert manifest.get("exe_url"), manifest
assert manifest.get("sha256") == sha, (manifest.get("sha256"), sha)
assert int(manifest.get("size", 0)) == size, (manifest.get("size"), size)
assert exe[:2] == b"MZ"
print(f"verified win-assistants {manifest['version']} {sha} {size}")
PY

mkdir -p "$TARGET_DIR"
install -m 0644 "$tmp_dir/win-assistants.exe" "$TARGET_DIR/win-assistants.exe.new"
install -m 0644 "$tmp_dir/update.json" "$TARGET_DIR/update.json.new"
mv -f "$TARGET_DIR/win-assistants.exe.new" "$TARGET_DIR/win-assistants.exe"
mv -f "$TARGET_DIR/update.json.new" "$TARGET_DIR/update.json"

manifest_version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["version"])' "$TARGET_DIR/update.json")"
manifest_sha="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["sha256"])' "$TARGET_DIR/update.json")"

if command -v curl >/dev/null 2>&1; then
  curl --fail --silent --show-error --max-time 15     "$PUBLIC_BASE/update.json?sync=$(date +%s)"     | python3 -c "import json,sys; p=json.load(sys.stdin); assert p['version']=='$manifest_version'; assert p['sha256']=='$manifest_sha'"
fi

echo "win-assistants updater assets synced: v$manifest_version"
