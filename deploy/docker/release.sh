#!/bin/bash
set -eo pipefail

shopt -s expand_aliases

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -f ~/.bash_profile ]]; then
  source ~/.bash_profile
fi

if [[ -f ./.envs_shell ]]; then
  source ./.envs_shell
fi

if [[ -f ./.env.release ]]; then
  source ./.env.release
fi

set -u

IMAGE_ARCHIVE="${IMAGE_ARCHIVE:-due-diligence-assistant-20260814-intranet-v1.image.tar}"

export APP_IMAGE="${APP_IMAGE:-docker.io/library/due-diligence-assistant:20260814-intranet-v1}"
export APP_PORT="${APP_PORT:-8888}"
export APP_ENV_FILE="${APP_ENV_FILE:-.env.intranet}"

# 1. 加载新镜像
nerdctl load -i "$IMAGE_ARCHIVE"
echo "load镜像成功"

# 2. 启动新服务
nerdctl compose -f docker-compose.yml up -d
echo "服务启动成功"

exit 0
