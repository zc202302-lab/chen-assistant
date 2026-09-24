#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${CHEN_ASSISTANT_DIR:-/opt/chen-assistant}"
REMOTE="${CHEN_ASSISTANT_REMOTE:-origin}"
BRANCH="${CHEN_ASSISTANT_BRANCH:-main}"

cd "$APP_DIR"

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "tracked files are modified; automatic deployment stopped"
  git status --short
  exit 1
fi

git fetch --quiet "$REMOTE" "$BRANCH"
START_REV="$(git rev-parse HEAD)"
TARGET_REV="$(git rev-parse "$REMOTE/$BRANCH")"

if [[ "$START_REV" == "$TARGET_REV" ]]; then
  echo "chen-assistant production already current: $(git rev-parse --short HEAD)"
  exit 0
fi

git merge-base --is-ancestor "$START_REV" "$TARGET_REV" || {
  echo "production checkout cannot fast-forward to $REMOTE/$BRANCH"
  exit 1
}

CHANGED_FILE_LIST="$(mktemp)"
DEPLOY_SCRIPT="$(mktemp)"
trap 'rm -f "$CHANGED_FILE_LIST" "$DEPLOY_SCRIPT"' EXIT

git diff --name-only "$START_REV" "$TARGET_REV" > "$CHANGED_FILE_LIST"
WEB_CHANGED=0
while IFS= read -r path; do
  [[ -z "$path" ]] && continue
  case "$path" in
    app/*|storage_node/*|requirements.txt|deploy.sh)
      WEB_CHANGED=1
      break
      ;;
  esac
done < "$CHANGED_FILE_LIST"

if [[ "$WEB_CHANGED" -ne 1 ]]; then
  git merge --ff-only "$TARGET_REV"
  echo "main advanced with no Web runtime changes; production service restart skipped"
  exit 0
fi

git show "$TARGET_REV:deploy.sh" > "$DEPLOY_SCRIPT"
chmod 0700 "$DEPLOY_SCRIPT"
CHEN_DEPLOY_FROM_REV="$START_REV" CHEN_DEPLOY_TARGET_REV="$TARGET_REV" bash "$DEPLOY_SCRIPT"
