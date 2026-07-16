# AceHLS Web Viewer

Interfaz web autogestionada para descubrir, reproducir y exportar canales AceStream. Convierte streams AceStream en HLS compatible con navegadores, iPhone/iPad y clientes IPTV, y puede integrarse con AceStream Orchestrator para mostrar el estado de motores y streams.

Versión actual: `v2.5.0-dev`.

## Características

- Interfaz responsive con búsqueda, categorías, favoritos, zapping y reproducción manual por AceStream ID.
- Reproducción web mediante HLS.js y HLS nativo cuando el navegador lo soporta.
- Detección automática del tipo de respuesta de AceXY:
  - Un manifiesto HLS real se sirve mediante proxy y reescritura de segmentos.
  - Un stream continuo `video/mp2t` se remultiplexa a HLS con FFmpeg.
- Compatibilidad con extensiones de navegador problemáticas: el worker de HLS.js está desactivado para evitar errores relacionados con `MediaKeyMessageEvent`.
- Sources 2.0: fuentes con nombre, estado, activación, validación y migración automática desde v2.4.x.
- Fuentes M3U y JSON de AceStream; admite `id`, `infohash`, URI AceStream y parámetros de URL.
- Canales personalizados gestionables desde la WebUI y con prioridad sobre metadatos remotos.
- Deduplicación global por tipo de identificador e identificador.
- Actualización autónoma de fuentes cada 15 minutos, sin depender de visitas a la WebUI.
- Caché persistente por fuente: una lista caída reutiliza su última copia válida sin eliminar sus canales.
- Listas M3U para VLC, TiviMate, IPTV Smarters y otros clientes.
- Perfiles opcionales `original`, `max_compat`, `720p` y `480p`.
- Transcodificación opcional por CPU o VAAPI cuando `/dev/dri/renderD128` está disponible en el contenedor.
- Cierre automático configurable de procesos FFmpeg sin peticiones HLS; el valor predeterminado es 120 segundos.
- Dashboard de CPU, RAM, disco, procesos FFmpeg, logs y motores del Orchestrator.
- Estadísticas persistentes de funcionamiento y datos técnicos obtenidos mediante FFprobe.
- Configuración persistente en el volumen de datos.

## Cambios recientes

Consulta [`CHANGELOG.md`](CHANGELOG.md) y la guía de migración [`docs/sources-v2.md`](docs/sources-v2.md).

## Arquitectura

```text
Fuente M3U ──► scheduler/cache por fuente ──► channels.json ──► WebUI/listas exportadas
                                                        │
Navegador/cliente ──► AceHLS ──► AceXY/Orchestrator ──► motor AceStream
                         │
                         ├─ HLS real: proxy de manifiesto y segmentos
                         └─ MPEG-TS continuo: FFmpeg ──► HLS
```

El `docker-compose.yml` de desarrollo incluye:

1. `ace-hls`: aplicación Flask servida por Gunicorn.
2. `acexy`: proxy HTTP de AceStream.
3. `acestream`: motor AceStream.

También puede usarse un AceStream Orchestrator externo que exponga el proxy de streams y su API de gestión.

## Instalación

### Configuración

```bash
cp .env.example .env
```

Edita `.env`. `URL_ORIGEN` puede quedar vacío; las fuentes también pueden añadirse desde el botón de configuración de la WebUI.

| Variable | Descripción | Defecto |
|---|---|---|
| `ACE_HLS_PORT` | Puerto publicado de la WebUI | `8088` |
| `ACEXY_IP` | Host de AceXY o del proxy unificado del Orchestrator | `acexy` |
| `ACEXY_PORT` | Puerto HTTP del proxy de streams | `8080` |
| `URL_ORIGEN` | Fuente M3U inicial opcional | vacío/reemplazar |
| `CACHE_DURATION` | Antigüedad para el refresh solicitado por la WebUI | `300` |
| `PLAYLIST_REFRESH_INTERVAL` | Intervalo del refresh autónomo, en segundos | `900` |
| `SOURCE_CONNECT_TIMEOUT` | Timeout de conexión de fuentes | `8` |
| `SOURCE_READ_TIMEOUT` | Timeout de lectura de fuentes | `30` |
| `SOURCE_MAX_BYTES` | Tamaño máximo de una respuesta | `10485760` |
| `SOURCE_TLS_VERIFY` | Verificación TLS; `false` conserva fuentes LAN/VPN con certificados propios | `false` |
| `FFMPEG_RW_TIMEOUT` | Timeout de lectura del proxy upstream, en segundos | `60` |
| `HLS_IDLE_TIMEOUT` | Tiempo sin peticiones HLS antes de cerrar FFmpeg | `120` |
| `ENABLE_TRANSCODE` | Habilita perfiles con recodificación | `false` |
| `ORCHESTRATOR_URL` | URL base de la API; vacío reutiliza `ACEXY_IP:ACEXY_PORT` | vacío |
| `ORCHESTRATOR_API_PREFIX` | Prefijo de la API unificada actual | `/api/v1` |
| `ORCHESTRATOR_API_TOKEN` | Bearer token; puede quedar vacío si no hay autenticación | `defaultpassword` |
| `ORCHESTRATOR_TIMEOUT` | Timeout de la API de gestión, en segundos | `5` |

`ACEXY_API_TOKEN` se mantiene únicamente como fallback de compatibilidad para `ORCHESTRATOR_API_TOKEN`.

### Desarrollo o build local

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r src/requirements.txt -r requirements-dev.txt
PYTHONPATH=src .venv/bin/python -m pytest -q
```

### Imagen publicada

```bash
docker compose -f release/docker-compose.yml pull ace-hls
docker compose -f release/docker-compose.yml up -d ace-hls
```

Acceso: `http://TU_IP:8088`.

## Fuentes y caché

Las fuentes se guardan en el esquema versionado de `sources.json`. Una instalación v2.4.x se migra de forma atómica al arrancar, conserva una única copia `sources.v1.backup.json` y no descarga fuentes durante la migración. Un esquema futuro desconocido se sirve desde caché y bloquea las mutaciones.

Cada fuente tiene un snapshot independiente dentro de `source_cache/`:

- Si responde correctamente, solo se reemplaza su propio snapshot.
- Si falla la descarga, devuelve contenido no M3U o intenta sustituir una caché no vacía por una lista vacía, se reutiliza su último snapshot válido.
- Los snapshots disponibles se combinan y deduplican para generar `channels.json` y `ace_hls.m3u` mediante reemplazo atómico.
- Al actualizar desde versiones anteriores, las cachés por hash de URL se migran a snapshots por ID estable de fuente.
- Si todas las fuentes fallan, se conserva la caché global y el scheduler reintenta después de 60 segundos.

Limitación inevitable: una instalación con volumen completamente nuevo no puede recuperar los canales de una fuente que nunca haya respondido correctamente.

El intervalo se configura con `PLAYLIST_REFRESH_INTERVAL`; el mínimo admitido es 60 segundos.

## Reproducción y listas M3U

### Navegador

Abre `http://TU_IP:8088` y selecciona un canal. AceHLS decide automáticamente si puede proxificar HLS real o si necesita generar HLS mediante FFmpeg.

### Clientes IPTV

| Modalidad | URL |
|---|---|
| HLS original | `http://TU_IP:8088/playlist.m3u?profile=original` |
| Enlace directo a AceXY | `http://TU_IP:8088/playlist.m3u?profile=direct` |
| Máxima compatibilidad H.264 | `http://TU_IP:8088/playlist.m3u?profile=max_compat` |
| 720p | `http://TU_IP:8088/playlist.m3u?profile=720p` |
| 480p | `http://TU_IP:8088/playlist.m3u?profile=480p` |
| Todas las variantes | `http://TU_IP:8088/api/playlist/all.m3u` |

Los perfiles `max_compat`, `720p` y `480p` requieren `ENABLE_TRANSCODE=true`. La modalidad `direct` evita AceHLS durante la reproducción; el dispositivo cliente debe poder acceder al endpoint público de AceXY configurado.

## AceStream Orchestrator

La integración se activa desde la configuración de la WebUI. La implementación actual usa el prefijo `/api/v1` de la API unificada y admite autenticación Bearer.

Endpoints upstream utilizados:

- `/api/v1/engines`
- `/api/v1/streams?status=started`
- `/api/v1/orchestrator/status`
- `/api/v1/metrics/dashboard?window_seconds=900`

Endpoints expuestos por AceHLS:

- `/api/orchestrator/status`
- `/api/orchestrator/streams`
- `/api/orchestrator/overview`
- `/api/orchestrator/metrics`
- `/api/orchestrator/config` — no expone el token.

Referencia: [API de AceStream Orchestrator](https://github.com/krinkuto11/acestream-orchestrator/blob/main/docs/API.md).

## Persistencia

El volumen `ace_hls_data` se monta en `/app/data` y contiene:

| Ruta | Contenido |
|---|---|
| `sources.json` | Registro de fuentes M3U |
| `sources.v1.backup.json` | Copia única del registro anterior a Sources 2.0 |
| `custom_channels.json` | Canales personalizados |
| `source_cache/` | Último snapshot válido de cada fuente |
| `channels.json` | Caché global deduplicada |
| `ace_hls.m3u` | Lista directa generada |
| `settings.json` | Configuración de la WebUI |
| `stats.json` | Salud y metadatos técnicos de canales |
| `app.log` | Log de aplicación |
| `hls/` | Segmentos y manifiestos temporales |

No elimines el volumen si quieres conservar fuentes, cachés, configuración y estadísticas.

## API y diagnóstico

| Endpoint | Función |
|---|---|
| `/health` | Disco, conexión AceXY, procesos FFmpeg y estado del scheduler |
| `/api/version` | Versión y estado de transcodificación |
| `/api/channels` | Canales normalizados |
| `/api/sources` | Listado y alta de fuentes |
| `/api/sources/{id}` | Edición y borrado de fuentes |
| `/api/sources/{id}/validate` | Revalidación de una fuente |
| `/api/sources/refresh` | Refresh manual |
| `/api/sources/refresh/status` | Estado del scheduler |
| `/api/custom-channels` | CRUD de canales personalizados |
| `/api/hls/start/{ace_id}` | Inicio de reproducción HLS |
| `/dashboard` | Dashboard de sistema |

`/health` es un endpoint de diagnóstico. Los Compose incluidos actualmente no lo declaran como `healthcheck` de Docker; `restart: unless-stopped` solo reinicia el contenedor cuando el proceso termina.

## Actualización de la imagen

```bash
docker compose pull ace-hls
docker compose up -d --force-recreate ace-hls
```

Adapta `ace-hls` al nombre real del servicio definido en tu Compose.

## Validación del proyecto

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src tests
node --check src/app/static/script.js
docker compose config -q
docker build -t ace-hls-viewer:2.5.0-dev-test .
```

`push_docker.sh` publica por defecto un manifiesto compatible con `linux/amd64` y `linux/arm64`. Puede limitarse mediante `DOCKER_PLATFORMS`; las versiones `-dev` bloquean siempre la etiqueta `latest`.
