#!/usr/bin/env bash
set -Eeuo pipefail

shopt -s expand_aliases
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"
[[ -f ~/.bash_profile ]] && source ~/.bash_profile
[[ -f ./.envs_shell ]] && source ./.envs_shell
set -a
source ./.env.release
set +a

CONTAINER_CLI="${CONTAINER_CLI:-nerdctl}"
CONTAINER_NAMESPACE="${CONTAINER_NAMESPACE:-k8s.io}"
mkdir -p backups
output="backups/${MYSQL_DATABASE}-$(date +%Y%m%d-%H%M%S).sql.gz"

run_cli() {
  if [[ "$CONTAINER_CLI" == "docker" ]]; then docker "$@"; else nerdctl -n "$CONTAINER_NAMESPACE" "$@"; fi
}

run_cli exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$MYSQL_CONTAINER_NAME" \
  mysqldump -uroot --single-transaction --quick --routines --triggers --events \
  --hex-blob --set-gtid-purged=OFF --default-character-set=utf8mb4 --no-tablespaces "$MYSQL_DATABASE" | gzip -9 > "$output"
sha256sum "$output" > "${output}.sha256"
echo "备份完成：$output"
