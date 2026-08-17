#!/usr/bin/env bash
set -Eeuo pipefail

shopt -s expand_aliases
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 用户环境脚本可能引用尚未定义的变量；仅在加载期间关闭 nounset，
# 随后立即恢复严格模式，发布配置仍会接受未定义变量检查。
set +u
[[ -f ~/.bash_profile ]] && source ~/.bash_profile
[[ -f ./.envs_shell ]] && source ./.envs_shell
set -u

if [[ ! -f .env.release || ! -f .env.intranet ]]; then
  echo "缺少配置文件。请先复制并修改："
  echo "  cp .env.release.example .env.release"
  echo "  cp .env.intranet.example .env.intranet"
  exit 1
fi

set -a
source ./.env.release
set +a

APP_IMAGE_ARCHIVE="${APP_IMAGE_ARCHIVE:-images/due-diligence-assistant-20260817-mysql-ops-v2.image.tar}"
MYSQL_IMAGE_ARCHIVE="${MYSQL_IMAGE_ARCHIVE:-images/mysql-8.4.image.tar}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-due-diligence-assistant}"
APP_CONTAINER_NAME="${APP_CONTAINER_NAME:-due-diligence-assistant}"
CONTAINER_CLI="${CONTAINER_CLI:-nerdctl}"
CONTAINER_NAMESPACE="${CONTAINER_NAMESPACE:-k8s.io}"

run_cli() {
  if [[ "$CONTAINER_CLI" == "docker" ]]; then
    docker "$@"
  else
    nerdctl -n "$CONTAINER_NAMESPACE" "$@"
  fi
}

run_compose() {
  if [[ "$CONTAINER_CLI" == "docker" ]]; then
    docker compose --env-file .env.release -p "$COMPOSE_PROJECT_NAME" -f docker-compose.yml "$@"
  else
    nerdctl -n "$CONTAINER_NAMESPACE" compose --env-file .env.release -p "$COMPOSE_PROJECT_NAME" -f docker-compose.yml "$@"
  fi
}

for required in SHA256SUMS "$APP_IMAGE_ARCHIVE" "$MYSQL_IMAGE_ARCHIVE" database/001-due_diligence-full.sql; do
  [[ -f "$required" ]] || { echo "缺少发布文件：$required"; exit 1; }
done

sha256sum -c SHA256SUMS

VOLUME_NAME="${COMPOSE_PROJECT_NAME}_mysql-data"
if [[ "${REQUIRE_EMPTY_DATABASE_VOLUME:-true}" == "true" ]] && run_cli volume inspect "$VOLUME_NAME" >/dev/null 2>&1; then
  echo "检测到已有 MySQL 数据卷：$VOLUME_NAME"
  echo "为避免覆盖或绕过迁移数据，本次发布已停止。"
  echo "如这是已完成初始化后的应用升级，请将 REQUIRE_EMPTY_DATABASE_VOLUME=false。"
  exit 1
fi

run_cli load -i "$MYSQL_IMAGE_ARCHIVE"
echo "MySQL 镜像加载完成"
run_cli load -i "$APP_IMAGE_ARCHIVE"
echo "应用镜像加载完成"

run_compose up -d
echo "容器已启动，等待应用就绪……"

for _ in $(seq 1 90); do
  status="$(run_cli inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$APP_CONTAINER_NAME" 2>/dev/null || true)"
  if [[ "$status" == "healthy" ]]; then
    echo "应用健康检查通过"
    exit 0
  fi
  if [[ "$status" == "unhealthy" ]]; then
    run_cli logs --tail 120 "$APP_CONTAINER_NAME" || true
    echo "应用健康检查失败"
    exit 1
  fi
  sleep 2
done

run_cli logs --tail 120 "$APP_CONTAINER_NAME" || true
echo "应用未在 180 秒内就绪"
exit 1
