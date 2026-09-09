#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

VERSION="$(tr -d '[:space:]' < "${ROOT_DIR}/src/app/version.txt")"
TAG="${VERSION#v}"

echo "=== Iniciando publicación de Release ${VERSION} ==="

# 1. Verificar working tree limpio
if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR: El repositorio tiene cambios pendientes sin commitear." >&2
  exit 1
fi

# 2. Ejecutar tests
echo "Ejecutando tests unitarios..."
PYTHONPATH=src .venv/bin/python -m pytest -q

# 3. Empaquetar Easy Deploy
echo "Generando paquete Easy Deploy..."
.venv/bin/python scripts/package_easy_deploy.py

# 4. Sincronizar y compilar en .16
echo "Sincronizando código con 192.168.90.16..."
rsync -a --delete --exclude='.git' --exclude='.venv' --exclude='__pycache__' --exclude='dist' "${ROOT_DIR}/" root@192.168.90.16:/root/Docker/ace-hls-src/

echo "Compilando y subiendo imagen a Docker Hub desde .16..."
ssh root@192.168.90.16 "cd /root/Docker/ace-hls-src && \
  docker build -t tscneo/ace-hls-viewer:${TAG} -t tscneo/ace-hls-viewer:latest . && \
  docker push tscneo/ace-hls-viewer:${TAG} && \
  docker push tscneo/ace-hls-viewer:latest"

# 5. Desplegar en .16
echo "Actualizando contenedor en .16..."
ssh root@192.168.90.16 "sed -i 's|^ACE_HLS_IMAGE=.*|ACE_HLS_IMAGE=tscneo/ace-hls-viewer:${TAG}|' /root/Docker/ace-hls/.env && \
  cd /root/Docker/ace-hls && docker compose up -d --force-recreate"

# 6. Crear tag Git y publicar
if git rev-parse "${VERSION}" >/dev/null 2>&1; then
  echo "El tag ${VERSION} ya existe localmente. Omitiendo creación de tag."
else
  echo "Creando tag Git ${VERSION}..."
  git tag -a "${VERSION}" -m "Release ${VERSION}"
fi

echo "Pusheando cambios y tag a GitHub..."
git push origin main
git push origin "${VERSION}"

echo "=== Publicación de ${VERSION} completada con éxito ==="
