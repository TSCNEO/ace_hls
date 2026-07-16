# AceHLS Web Viewer

AceHLS es una aplicación Flask para descubrir canales AceStream, reproducirlos en el navegador y exportarlos como listas IPTV. Está pensada para una red interna, LAN o VPN; no incorpora autenticación ni protecciones para exponerla directamente a Internet.

La versión de la aplicación se define únicamente en [`src/app/version.txt`](src/app/version.txt). Los cambios publicados están en [`CHANGELOG.md`](CHANGELOG.md).

## Qué incluye

- Webplayer responsive con búsqueda, categorías, favoritos, zapping y reproducción manual.
- Fuentes M3U y respuestas JSON de `api.acestream.me/all` o `/search`.
- Identificadores `id` e `infohash`, URI `acestream://` e `infohash://` y hashes de 40 caracteres.
- Sources 2.0: alta, edición, validación, activación, caché por fuente y migración desde v2.4.x.
- Canales personalizados con prioridad sobre los metadatos de fuentes remotas.
- Exportación M3U para clientes IPTV y reproducción directa mediante Orchestrator o AceXY legacy.
- Detección de HLS real; los streams MPEG-TS continuos se remultiplexan con FFmpeg.
- Perfiles `original`, `max_compat`, `720p` y `480p`; los tres últimos requieren transcodificación.
- Dashboard local, estadísticas persistentes e integración con AceStream Orchestrator.

## Arquitectura

```text
Fuentes remotas ─► validador ─► caché por fuente ─┐
Canales propios ──────────────────────────────────┼─► channels.json ─► WebUI / M3U
                                                  │
Navegador o IPTV ─► AceHLS ─► Orchestrator ─► motores AceStream ┘
                       ├─ HLS real: proxy
                       └─ MPEG-TS: FFmpeg a HLS
```

El Compose predeterminado ejecuta `ace-hls` y AceStream Orchestrator `v2.1.0.3`. El Orchestrator crea y administra los motores bajo demanda. El stack simple AceXY continúa disponible en `docker-compose.acexy.yml`.

## Instalación

```bash
cp .env.example .env
docker compose up -d --build
```

La WebUI queda en `http://IP_DEL_HOST:8088`, el panel del Orchestrator en `http://IP_DEL_HOST:8000/panel` y la reproducción directa usa el mismo puerto `8000`. Cambia `ORCHESTRATOR_API_TOKEN` antes de usar el stack fuera de una red de confianza.

Para usar la imagen publicada:

```bash
docker compose -f release/docker-compose.yml pull
docker compose -f release/docker-compose.yml up -d
```

El Compose de release usa `tscneo/ace-hls-viewer:latest`. Para fijar una versión:

```bash
ACE_HLS_IMAGE=tscneo/ace-hls-viewer:2.6.0-dev \
docker compose -f release/docker-compose.yml up -d
```

La configuración completa está en [`docs/configuration.md`](docs/configuration.md).

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

`direct` genera automáticamente `http://IP_DEL_HOST:8000/ace/getstream`; `STREAM_PUBLIC_ENDPOINT` permite sobrescribirlo. `max_compat`, `720p` y `480p` requieren `ENABLE_TRANSCODE=true`. Si se habilita VAAPI, debe montarse `/dev/dri` en el contenedor.

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
.venv/bin/python -m compileall -q src tests
node --check src/app/static/script.js
docker compose --env-file .env.example config -q
docker compose -f docker-compose.acexy.yml --env-file .env.example config -q
docker build -t ace-hls-viewer:test .
```

`push_docker.sh` lee `src/app/version.txt` y publica `linux/amd64` y `linux/arm64`. `--latest` solo se admite para versiones sin sufijo `-dev`.
