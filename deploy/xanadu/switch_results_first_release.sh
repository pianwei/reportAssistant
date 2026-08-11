#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="due-diligence-assistant"
BACKUP_NAME="due-diligence-assistant-pre-results-first-final-20260811"
APP_ROOT="/home/pianwei/apps/due-diligence-assistant"
RELEASE_ROOT="$APP_ROOT/releases/results-first-final-20260811"
IMAGE="due-diligence-assistant:20260811-results-first-final"
ARCHIVE="$APP_ROOT/xanadu-results-first-20260811.tar.gz"

if docker container inspect "$BACKUP_NAME" >/dev/null 2>&1; then
  echo "backup container already exists: $BACKUP_NAME" >&2
  exit 1
fi

mkdir -p "$RELEASE_ROOT"
tar -xzf "$ARCHIVE" -C "$RELEASE_ROOT"
docker build -t "$IMAGE" "$RELEASE_ROOT"
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
  --env-file "$APP_ROOT/.env" \
  -p 127.0.0.1:8010:8000 \
  -v "$APP_ROOT/runtime:/app/runtime" \
  "$IMAGE"
docker network connect docker_default "$APP_NAME"

for _ in {1..20}; do
  if curl -fsS http://127.0.0.1:8010/api/v1/health >/dev/null; then
    trap - ERR
    echo "results-first release container is healthy"
    exit 0
  fi
  sleep 1
done

echo "health check timed out" >&2
exit 1
