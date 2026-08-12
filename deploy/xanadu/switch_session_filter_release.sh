#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="due-diligence-assistant"
BACKUP_NAME="due-diligence-assistant-pre-session-filter-20260812"
APP_ROOT="/home/pianwei/apps/due-diligence-assistant"
RELEASE_ROOT="$APP_ROOT/releases/session-filter-20260812"
BASE_IMAGE="due-diligence-assistant:20260812-shared-interaction-v3"
IMAGE="due-diligence-assistant:20260812-session-filter-v4"
ARCHIVE="$APP_ROOT/xanadu-session-filter-20260812.tar.gz"
ENV_FILE="$APP_ROOT/.env"

if docker container inspect "$BACKUP_NAME" >/dev/null 2>&1; then
  echo "backup container already exists: $BACKUP_NAME" >&2
  exit 1
fi
if ! docker image inspect "$BASE_IMAGE" >/dev/null 2>&1; then
  echo "base image does not exist: $BASE_IMAGE" >&2
  exit 1
fi

rm -rf "$RELEASE_ROOT"
mkdir -p "$RELEASE_ROOT"
tar -xzf "$ARCHIVE" -C "$RELEASE_ROOT"

docker build \
  --build-arg "BASE_IMAGE=$BASE_IMAGE" \
  -t "$IMAGE" \
  -f "$RELEASE_ROOT/deploy/xanadu/code-overlay.Dockerfile" \
  "$RELEASE_ROOT"

docker stop "$APP_NAME"
docker rename "$APP_NAME" "$BACKUP_NAME"

rollback() {
  docker rm -f "$APP_NAME" >/dev/null 2>&1 || true
  docker rename "$BACKUP_NAME" "$APP_NAME" >/dev/null 2>&1 || true
  docker start "$APP_NAME" >/dev/null 2>&1 || true
  echo "deployment rolled back" >&2
}
trap rollback ERR

docker run -d \
  --name "$APP_NAME" \
  --restart unless-stopped \
  --env-file "$ENV_FILE" \
  -p 127.0.0.1:8010:8000 \
  -v "$APP_ROOT/runtime:/app/runtime" \
  "$IMAGE"
docker network connect docker_default "$APP_NAME"

for _ in {1..90}; do
  health="$(curl -fsS http://127.0.0.1:8010/api/v1/health 2>/dev/null || true)"
  if [[ "$health" == *'"status":"ready"'* ]] \
    && [[ "$health" == *'"report_count":293'* ]] \
    && [[ "$health" == *'"tag_count":5860'* ]]; then
    trap - ERR
    echo "$health"
    echo "session filter release container is healthy"
    exit 0
  fi
  sleep 1
done

echo "health check timed out or data counts do not match" >&2
exit 1
