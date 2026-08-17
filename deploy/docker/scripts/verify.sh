#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8888}"
curl --fail --show-error --silent "${BASE_URL}/api/v1/health/live"
echo
curl --fail --show-error --silent "${BASE_URL}/api/v1/health/ready"
echo
curl --fail --show-error --silent "${BASE_URL}/api/v1/health"
echo
