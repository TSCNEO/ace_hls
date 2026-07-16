#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="$(tr -d '[:space:]' < "${ROOT_DIR}/src/app/version.txt")"
TAG="${VERSION#v}"
IMAGE="tscneo/ace-hls-viewer:${TAG}"
PLATFORMS="${DOCKER_PLATFORMS:-linux/amd64,linux/arm64}"

if [[ -z "${TAG}" ]]; then
  echo "No se pudo leer la versión" >&2
  exit 1
fi

if [[ "${1:-}" == "--latest" && "${TAG}" == *-dev ]]; then
  echo "No se permite publicar latest desde una versión de desarrollo (${TAG})" >&2
  exit 2
fi

build_args=(
  buildx build
  --platform "${PLATFORMS}"
  --tag "${IMAGE}"
  --push
)

if [[ "${1:-}" == "--latest" ]]; then
  build_args+=(--tag tscneo/ace-hls-viewer:latest)
fi

docker "${build_args[@]}" "${ROOT_DIR}"

echo "Publicada ${IMAGE} para ${PLATFORMS}"
