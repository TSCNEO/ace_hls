#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="$(tr -d '[:space:]' < "${ROOT_DIR}/src/app/version.txt")"
TAG="${VERSION#v}"
IMAGE="tscneo/ace-hls-viewer:${TAG}"

if [[ -z "${TAG}" ]]; then
  echo "No se pudo leer la versión" >&2
  exit 1
fi

if [[ "${1:-}" == "--latest" && "${TAG}" == *-dev ]]; then
  echo "No se permite publicar latest desde una versión de desarrollo (${TAG})" >&2
  exit 2
fi

docker build --tag "${IMAGE}" "${ROOT_DIR}"
docker push "${IMAGE}"

if [[ "${1:-}" == "--latest" ]]; then
  docker tag "${IMAGE}" tscneo/ace-hls-viewer:latest
  docker push tscneo/ace-hls-viewer:latest
fi

echo "Publicada ${IMAGE}"
