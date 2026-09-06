# AceHLS Web Viewer

AceHLS es una aplicación Flask para descubrir canales AceStream, reproducirlos en el navegador y exportarlos como listas IPTV. Está pensada para una red interna, LAN o VPN; no incorpora autenticación ni protecciones para exponerla directamente a Internet.

La versión de la aplicación se define únicamente en [`src/app/version.txt`](src/app/version.txt). Los cambios publicados están en [`CHANGELOG.md`](CHANGELOG.md).

## Qué incluye

- Webplayer responsive con búsqueda, categorías, favoritos, zapping y reproducción manual.
- Fuentes M3U con metadatos IPTV y referencias AceStream normalizadas.
- Fuentes e identificadores MylinkPaste dinámicos mediante resolución DNS TXT sobre DoH.
- Identificadores `id` e `infohash`, URI `acestream://` e `infohash://` y hashes de 40 caracteres.
- Sources 2.0: alta, edición, validación, activación, caché por fuente y migración.
- Canales personalizados con prioridad sobre los metadatos de fuentes remotas.
- Exportación M3U para clientes IPTV y reproducción directa mediante Orchestrator o AceXY legacy.
- Detección de HLS real; los streams MPEG-TS continuos se remultiplexan con FFmpeg.
- Perfiles `original`, `max_compat`, `720p` y `480p`; los tres últimos requieren transcodificación.
- Dashboard local, estadísticas persistentes e integración con AceStream Orchestrator.

## Instalación recomendada: Easy Deploy

[`easy-deploy/`](easy-deploy/) contiene dos paquetes autónomos que usan imágenes ya construidas: no necesitan ejecutar `docker build`. El mismo contenido se publica como un único ZIP en [GitHub Releases](https://github.com/TSCNEO/ace_hls/releases/tag/v2.8.0).

Clonar una vez el repositorio:

```bash
git clone https://github.com/TSCNEO/ace_hls.git
cd ace_hls
```

O descargar solo el paquete listo para desplegar:

```bash
curl -LO https://github.com/TSCNEO/ace_hls/releases/download/v2.8.0/ace-hls-easy-deploy-v2.8.0.zip
unzip ace-hls-easy-deploy-v2.8.0.zip
cd ace-hls-easy-deploy-v2.8.0
```

Después elige una de las dos variantes.

Orchestrator en el mismo host:

```bash
cd easy-deploy/orchestrator-local
cp .env.example .env
# Editar ORCHESTRATOR_API_TOKEN
docker compose pull
docker compose up -d --remove-orphans
```

Orchestrator en otra IP:

```bash
cd easy-deploy/orchestrator-remote
cp .env.example .env
# Editar ORCHESTRATOR_HOST y ORCHESTRATOR_API_TOKEN
docker compose pull
docker compose up -d --remove-orphans
```

Ambas variantes reutilizan el volumen configurable `ace_hls_data`. Consulta la [guía Easy Deploy](easy-deploy/README.md) para actualizar, cambiar de variante, reutilizar un volumen anterior o hacer rollback.

## Arquitectura

```text
Fuentes remotas ─► validador ─► caché por fuente ─┐
Canales propios ──────────────────────────────────┼─► channels.json ─► WebUI / M3U
                                                  │
Navegador o IPTV ─► AceHLS ─► Orchestrator ─► motores AceStream ┘
                       ├─ HLS real: proxy
                       └─ MPEG-TS: FFmpeg a HLS
```

El Compose predeterminado ejecuta `ace-hls` y AceStream Orchestrator `v2.1.0.3`. También existe un Compose que conecta AceHLS a un Orchestrator instalado en otra IP. El stack simple AceXY continúa disponible en `docker-compose.acexy.yml`.

## Instalación desde el repositorio

Estos Compose se conservan para desarrollo y compatibilidad con instalaciones existentes. Para una instalación nueva se recomienda Easy Deploy.

```bash
cp .env.example .env
# Editar ORCHESTRATOR_API_TOKEN
docker compose --env-file .env up -d --build --remove-orphans
```

La WebUI queda en `http://IP_DEL_HOST:8088`, el panel del Orchestrator en `http://IP_DEL_HOST:8000/panel` y la reproducción directa usa el mismo puerto `8000`. Cambia `ORCHESTRATOR_API_TOKEN` antes de usar el stack fuera de una red de confianza.

Para construir una imagen local de forma explícita, por ejemplo para AMD64/Intel:

```bash
docker build --platform linux/amd64 -t ace-hls-viewer:2.8.0 .
ACE_HLS_IMAGE=ace-hls-viewer:2.8.0 \
docker compose -f release/docker-compose.yml --env-file .env up -d --remove-orphans
```

`push_docker.sh --latest` construye y publica conjuntamente las variantes `linux/amd64` y `linux/arm64`, etiquetadas como `2.8.0` y `latest`. Easy Deploy evita todo este proceso y descarga las imágenes publicadas.

Para usar la imagen publicada:

```bash
docker compose -f release/docker-compose.yml --env-file .env pull
docker compose -f release/docker-compose.yml --env-file .env up -d --remove-orphans
```

El Compose de release usa `tscneo/ace-hls-viewer:latest`. Para fijar una versión:

```bash
ACE_HLS_IMAGE=tscneo/ace-hls-viewer:2.8.0 \
docker compose -f release/docker-compose.yml --env-file .env up -d --remove-orphans
```

## Instalación con Orchestrator externo

```bash
cp .env.orchestrator-remote.example .env
# Editar ORCHESTRATOR_HOST y ORCHESTRATOR_API_TOKEN
ACE_HLS_IMAGE=tscneo/ace-hls-viewer:2.8.0 \
docker compose -f release/docker-compose.orchestrator-remote.yml --env-file .env \
  up -d --remove-orphans
```

Este modo solo ejecuta AceHLS y utiliza por defecto `http://ORCHESTRATOR_HOST:ORCHESTRATOR_PORT` para la API y la reproducción. No monta el Docker socket ni publica un Orchestrator local.

La guía paso a paso, verificación y diagnóstico está en [`docs/orchestrator-deployment.md`](docs/orchestrator-deployment.md). La referencia de variables está en [`docs/configuration.md`](docs/configuration.md).

## Fuentes y persistencia

El volumen `ace_hls_data` se monta en `/app/data`. No debe eliminarse durante una actualización.

| Ruta | Contenido |
|---|---|
| `sources.json` | Registro Sources 2.0 |
| `sources.v1.backup.json` | Backup único creado al migrar desde v2.4.x |
| `custom_channels.json` | Canales personalizados |
| `source_cache/` | Último snapshot válido de cada fuente |
| `channels.json` | Salida normalizada y deduplicada |
| `ace_hls.m3u` | Lista directa generada |
| `settings.json` | Ajustes de la WebUI |
| `stats.json` | Salud y metadatos técnicos |
| `app.log` | Log de aplicación |
| `hls/` | Manifiestos y segmentos temporales |

La migración del registro es atómica y no accede a la red. Después del arranque, el scheduler actualiza en segundo plano las fuentes habilitadas. Si una fuente falla se usa su snapshot válido; si fallan todas se conserva `channels.json`. Un esquema futuro desconocido nunca se sobrescribe.

Detalles del formato y compatibilidad: [`docs/sources-v2.md`](docs/sources-v2.md).

## Reproducción y listas

| Modalidad | URL |
|---|---|
| HLS original | `/playlist.m3u?profile=original` |
| Backend directo | `/playlist.m3u?profile=direct` |
| H.264 compatible | `/playlist.m3u?profile=max_compat` |
| 720p | `/playlist.m3u?profile=720p` |
| 480p | `/playlist.m3u?profile=480p` |
| Todas las variantes | `/api/playlist/all.m3u` |

En modo local, `direct` genera `http://IP_DEL_HOST:8000/ace/getstream`. En modo remoto usa `ORCHESTRATOR_HOST:ORCHESTRATOR_PORT`. `STREAM_PUBLIC_ENDPOINT` permite sobrescribir ambos casos. `max_compat`, `720p` y `480p` requieren `ENABLE_TRANSCODE=true`. Si se habilita VAAPI, debe montarse `/dev/dri` en el contenedor.

La referencia completa de endpoints está en [`docs/api.md`](docs/api.md).

## Actualización

```bash
docker compose pull
docker compose up -d --force-recreate --remove-orphans
```

Una actualización desde v2.4.x reutiliza el mismo volumen y migra automáticamente fuentes y cachés. Conviene conservar `sources.v1.backup.json` hasta comprobar la instalación.

Para conservar el modo simple anterior:

```bash
docker compose -f release/docker-compose.acexy.yml up -d --remove-orphans
```

## Desarrollo y validación

Las pruebas y servidores locales se ejecutan con Python 3.11 dentro de `.venv`:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r src/requirements.txt -r requirements-dev.txt
PYTHONPATH=src .venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src tests scripts
node --check src/app/static/script.js
docker compose --env-file .env.example config -q
docker compose -f docker-compose.orchestrator-remote.yml --env-file .env.orchestrator-remote.example config -q
docker compose -f docker-compose.acexy.yml --env-file .env.example config -q
.venv/bin/python scripts/package_easy_deploy.py
docker build -t ace-hls-viewer:test .
```

`push_docker.sh` lee `src/app/version.txt` y publica `linux/amd64` y `linux/arm64`. `--latest` solo se admite para versiones sin sufijo `-dev`. Al publicar una etiqueta Git estable, el workflow verifica primero que exista esa imagen y adjunta `ace-hls-easy-deploy-vX.Y.Z.zip` a GitHub Releases.
