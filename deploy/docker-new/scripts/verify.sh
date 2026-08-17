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
BASE_URL="${1:-http://127.0.0.1:${APP_PORT:-8888}}"

run_cli() {
  if [[ "$CONTAINER_CLI" == "docker" ]]; then docker "$@"; else nerdctl -n "$CONTAINER_NAMESPACE" "$@"; fi
}

curl --fail --show-error --silent "$BASE_URL/api/v1/health/live"; echo
curl --fail --show-error --silent "$BASE_URL/api/v1/health/ready"; echo
curl --fail --show-error --silent "$BASE_URL/api/v1/health"; echo
curl --fail --show-error --silent --output /dev/null "$BASE_URL/ops"

counts="$(run_cli exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$MYSQL_CONTAINER_NAME" mysql -uroot -N "$MYSQL_DATABASE" -e \
  "SELECT CONCAT((SELECT COUNT(*) FROM reports),'|',(SELECT COUNT(*) FROM report_tags),'|',(SELECT COUNT(*) FROM sessions),'|',(SELECT COUNT(*) FROM messages),'|',(SELECT COUNT(*) FROM session_tags),'|',(SELECT COUNT(*) FROM suggestion_batches),'|',(SELECT COUNT(*) FROM model_profiles),'|',(SELECT COUNT(*) FROM model_events));")"
IFS='|' read -r reports tags sessions messages session_tags suggestion_batches model_profiles model_events <<< "$counts"

[[ "$reports" == "${EXPECTED_REPORTS:-293}" ]] || { echo "报告数不符：$reports"; exit 1; }
[[ "$tags" == "${EXPECTED_REPORT_TAGS:-5860}" ]] || { echo "标签数不符：$tags"; exit 1; }
[[ "$sessions" == "${EXPECTED_SESSIONS:-2}" ]] || { echo "会话数不符：$sessions"; exit 1; }
[[ "$messages" == "${EXPECTED_MESSAGES:-4}" ]] || { echo "消息数不符：$messages"; exit 1; }
[[ "$session_tags" == "${EXPECTED_SESSION_TAGS:-2}" ]] || { echo "会话标签数不符：$session_tags"; exit 1; }
[[ "$suggestion_batches" == "${EXPECTED_SUGGESTION_BATCHES:-6}" ]] || { echo "建议批次数不符：$suggestion_batches"; exit 1; }
[[ "$model_profiles" == "${EXPECTED_MODEL_PROFILES:-0}" ]] || { echo "模型配置数不符：$model_profiles"; exit 1; }
[[ "$model_events" == "${EXPECTED_MODEL_EVENTS:-0}" ]] || { echo "模型事件数不符：$model_events"; exit 1; }

echo "MySQL 8 张表数据校验通过：reports=$reports, report_tags=$tags, sessions=$sessions, messages=$messages, session_tags=$session_tags, suggestion_batches=$suggestion_batches, model_profiles=$model_profiles, model_events=$model_events"
echo "运营端：$BASE_URL/ops"
