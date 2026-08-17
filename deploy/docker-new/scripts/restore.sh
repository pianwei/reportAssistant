#!/usr/bin/env bash
set -Eeuo pipefail

shopt -s expand_aliases
if [[ $# -ne 1 || ! -f "$1" ]]; then
  echo "用法：$0 backups/due_diligence-时间.sql.gz"
  exit 1
fi

BACKUP_FILE="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"
[[ -f ~/.bash_profile ]] && source ~/.bash_profile
[[ -f ./.envs_shell ]] && source ./.envs_shell
set -a
source ./.env.release
set +a

[[ "$MYSQL_DATABASE" =~ ^[A-Za-z0-9_]+$ ]] || { echo "非法数据库名"; exit 1; }
read -r -p "恢复会清空数据库 $MYSQL_DATABASE。输入 RESTORE 继续：" answer
[[ "$answer" == "RESTORE" ]] || { echo "已取消"; exit 1; }

CONTAINER_CLI="${CONTAINER_CLI:-nerdctl}"
CONTAINER_NAMESPACE="${CONTAINER_NAMESPACE:-k8s.io}"

run_cli() {
  if [[ "$CONTAINER_CLI" == "docker" ]]; then docker "$@"; else nerdctl -n "$CONTAINER_NAMESPACE" "$@"; fi
}

run_compose() {
  if [[ "$CONTAINER_CLI" == "docker" ]]; then
    docker compose --env-file .env.release -p "$COMPOSE_PROJECT_NAME" -f docker-compose.yml "$@"
  else
    nerdctl -n "$CONTAINER_NAMESPACE" compose --env-file .env.release -p "$COMPOSE_PROJECT_NAME" -f docker-compose.yml "$@"
  fi
}

run_compose stop app
run_cli exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$MYSQL_CONTAINER_NAME" mysql -uroot -e \
  "DROP DATABASE IF EXISTS \`$MYSQL_DATABASE\`; CREATE DATABASE \`$MYSQL_DATABASE\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
gzip -dc "$BACKUP_FILE" | run_cli exec -i -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$MYSQL_CONTAINER_NAME" mysql -uroot "$MYSQL_DATABASE"
run_compose start app
echo "恢复完成，请执行 ./scripts/verify.sh"
