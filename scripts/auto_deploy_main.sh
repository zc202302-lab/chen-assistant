#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${CHEN_ASSISTANT_DIR:-/opt/chen-assistant}"
REMOTE="${CHEN_ASSISTANT_REMOTE:-origin}"
BRANCH="${CHEN_ASSISTANT_BRANCH:-production-ready}"
STATE_DIR="${CHEN_AUTO_DEPLOY_STATE_DIR:-/var/lib/chen-assistant-auto-deploy}"
CHECKPOINT_FILE="$STATE_DIR/last-successful-revision"
LOCK_FILE="$STATE_DIR/deploy.lock"
SYNC_TARGET="${CHEN_AUTO_DEPLOY_SYNC_TARGET:-/usr/local/sbin/chen-assistant-auto-deploy}"

mkdir -p "$STATE_DIR"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "another chen-assistant deployment check is already running; skip"
  exit 0
fi

cd "$APP_DIR"

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "tracked files are modified; automatic deployment stopped"
  git status --short
  exit 1
fi

fetch_ready_ref() {
  local attempt
  for attempt in 1 2 3; do
    if timeout 60s git fetch --quiet "$REMOTE" "$BRANCH:refs/remotes/$REMOTE/$BRANCH"; then
      return 0
    fi
    echo "fetch $REMOTE/$BRANCH failed (attempt $attempt/3)"
    sleep $((attempt * 2))
  done
  return 1
}

fetch_ready_ref
START_REV="$(git rev-parse HEAD)"
TARGET_REV="$(git rev-parse "refs/remotes/$REMOTE/$BRANCH")"

# Keep the production-side worker itself current. This is safe because only the
# CI-published, validated production-ready revision is used as the source.
if [[ "${CHEN_AUTO_DEPLOY_REEXEC:-0}" != "1" ]]; then
  TARGET_WORKER="$(mktemp)"
  trap 'rm -f "$TARGET_WORKER"' EXIT
  git show "$TARGET_REV:scripts/auto_deploy_main.sh" > "$TARGET_WORKER"
  if [[ ! -f "$SYNC_TARGET" ]] || ! cmp -s "$TARGET_WORKER" "$SYNC_TARGET"; then
    install -m 0755 "$TARGET_WORKER" "$SYNC_TARGET"
    echo "auto-deploy worker refreshed from validated production-ready revision"
    exec env CHEN_AUTO_DEPLOY_REEXEC=1       CHEN_ASSISTANT_DIR="$APP_DIR"       CHEN_ASSISTANT_REMOTE="$REMOTE"       CHEN_ASSISTANT_BRANCH="$BRANCH"       CHEN_AUTO_DEPLOY_STATE_DIR="$STATE_DIR"       CHEN_AUTO_DEPLOY_SYNC_TARGET="$SYNC_TARGET"       "$SYNC_TARGET"
  fi
  rm -f "$TARGET_WORKER"
  trap - EXIT
fi

CHECKPOINT_REV=""
if [[ -s "$CHECKPOINT_FILE" ]]; then
  CHECKPOINT_REV="$(tr -d '[:space:]' < "$CHECKPOINT_FILE")"
  if ! git rev-parse --verify "$CHECKPOINT_REV^{commit}" >/dev/null 2>&1; then
    echo "last successful deployment checkpoint is invalid; forcing a full self-check"
    CHECKPOINT_REV=""
  elif ! git merge-base --is-ancestor "$CHECKPOINT_REV" "$TARGET_REV"; then
    echo "last successful deployment checkpoint is not an ancestor of validated target; stop"
    exit 1
  fi
fi

if [[ "$START_REV" != "$TARGET_REV" ]]; then
  git merge-base --is-ancestor "$START_REV" "$TARGET_REV" || {
    echo "production checkout cannot fast-forward to $REMOTE/$BRANCH"
    exit 1
  }
fi

if [[ -n "$CHECKPOINT_REV" && "$CHECKPOINT_REV" == "$TARGET_REV" && "$START_REV" == "$TARGET_REV" ]]; then
  echo "chen-assistant production already verified current: $(git rev-parse --short HEAD)"
  exit 0
fi

DIFF_BASE="$START_REV"
FORCE_DEPLOY=0
if [[ -n "$CHECKPOINT_REV" ]]; then
  DIFF_BASE="$CHECKPOINT_REV"
else
  # A missing checkpoint must never be interpreted as success. Run the normal
  # deploy self-check once so the state can be rebuilt safely.
  FORCE_DEPLOY=1
fi

CHANGED_FILE_LIST="$(mktemp)"
DEPLOY_SCRIPT="$(mktemp)"
trap 'rm -f "$CHANGED_FILE_LIST" "$DEPLOY_SCRIPT"' EXIT

if [[ "$DIFF_BASE" == "$TARGET_REV" ]]; then
  : > "$CHANGED_FILE_LIST"
else
  git diff --name-only "$DIFF_BASE" "$TARGET_REV" > "$CHANGED_FILE_LIST"
fi

WEB_CHANGED="$FORCE_DEPLOY"
while IFS= read -r path; do
  [[ -z "$path" ]] && continue
  case "$path" in
    app/*|storage_node/*|requirements.txt|deploy.sh)
      WEB_CHANGED=1
      break
      ;;
  esac
done < "$CHANGED_FILE_LIST"

write_checkpoint() {
  local tmp
  tmp="$(mktemp "$STATE_DIR/.last-successful-revision.XXXXXX")"
  printf '%s\n' "$TARGET_REV" > "$tmp"
  chmod 0644 "$tmp"
  mv -f "$tmp" "$CHECKPOINT_FILE"
}

if [[ "$WEB_CHANGED" -ne 1 ]]; then
  if [[ "$START_REV" != "$TARGET_REV" ]]; then
    git merge --ff-only "$TARGET_REV"
  fi
  write_checkpoint
  echo "validated main advanced with no Web runtime changes; service restart skipped"
  exit 0
fi

git show "$TARGET_REV:deploy.sh" > "$DEPLOY_SCRIPT"
chmod 0700 "$DEPLOY_SCRIPT"
CHEN_DEPLOY_FROM_REV="$DIFF_BASE" CHEN_DEPLOY_TARGET_REV="$TARGET_REV" bash "$DEPLOY_SCRIPT"

# deploy.sh writes the checkpoint at the very end. Keep this fallback so a
# successful older deploy script can still transition safely during rollout.
if [[ ! -s "$CHECKPOINT_FILE" || "$(tr -d '[:space:]' < "$CHECKPOINT_FILE")" != "$TARGET_REV" ]]; then
  write_checkpoint
fi

echo "automatic production deployment verified: $(git rev-parse --short "$TARGET_REV")"
