#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(cd "${SCRIPT_DIR}/../../.." && pwd)}"
VERSION="${VERSION:-20260814-intranet-v1}"
REPOSITORY="${REPOSITORY:-docker.io/library/due-diligence-assistant}"
IMAGE="${REPOSITORY}:${VERSION}"
ARTIFACT_DIR="${PROJECT_DIR}/deploy/docker/artifacts"
ARCHIVE_NAME="due-diligence-assistant-${VERSION}.image.tar"

test -f "${PROJECT_DIR}/frontend/dist/index.html"
test -d "${PROJECT_DIR}/deploy/docker/wheelhouse"
(cd "${PROJECT_DIR}/deploy/docker/wheelhouse" && sha256sum -c ../WHEELHOUSE-SHA256SUMS)
mkdir -p "${ARTIFACT_DIR}"

docker build \
  --file "${PROJECT_DIR}/deploy/docker/Dockerfile.intranet" \
  --build-arg "APP_VERSION=${VERSION}" \
  --tag "${IMAGE}" \
  "${PROJECT_DIR}"
docker save --output "${ARTIFACT_DIR}/${ARCHIVE_NAME}" "${IMAGE}"
(cd "${ARTIFACT_DIR}" && sha256sum "${ARCHIVE_NAME}" > SHA256SUMS)
echo "镜像：${IMAGE}"
echo "离线包：${ARTIFACT_DIR}/${ARCHIVE_NAME}"
