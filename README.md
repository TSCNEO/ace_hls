# AceHLS Web Viewer

Interfaz web autogestionada para descubrir, reproducir y exportar canales AceStream. Convierte streams AceStream en HLS compatible con navegadores, iPhone/iPad y clientes IPTV, y puede integrarse con AceStream Orchestrator para mostrar el estado de motores y streams.

Versión actual: `v2.4.1`.

## Características

- Interfaz responsive con búsqueda, categorías, favoritos, zapping y reproducción manual por AceStream ID.
- Reproducción web mediante HLS.js y HLS nativo cuando el navegador lo soporta.
- Detección automática del tipo de respuesta de AceXY:
  - Un manifiesto HLS real se sirve mediante proxy y reescritura de segmentos.
  - Un stream continuo `video/mp2t` se remultiplexa a HLS con FFmpeg.
- Compatibilidad con extensiones de navegador problemáticas: el worker de HLS.js está desactivado para evitar errores relacionados con `MediaKeyMessageEvent`.
- Gestión persistente de múltiples fuentes M3U desde la WebUI.
- Deduplicación global por AceStream ID.
- Actualización autónoma de fuentes cada 15 minutos, sin depender de visitas a la WebUI.
- Caché persistente por fuente: una lista caída reutiliza su última copia válida sin eliminar sus canales.
- Listas M3U para VLC, TiviMate, IPTV Smarters y otros clientes.
- Perfiles opcionales `original`, `max_compat`, `720p` y `480p`.
- Transcodificación opcional por CPU o VAAPI cuando `/dev/dri/renderD128` está disponible en el contenedor.
- Cierre automático de procesos FFmpeg tras 60 segundos sin actividad.
- Dashboard de CPU, RAM, disco, procesos FFmpeg, logs y motores del Orchestrator.
- Estadísticas persistentes de funcionamiento y datos técnicos obtenidos mediante FFprobe.
- Configuración persistente en el volumen de datos.

## Cambios recientes

- Corregida la preparación infinita del player: AceHLS ya distingue un manifiesto HLS de un stream MPEG-TS continuo antes de decidir entre proxy y FFmpeg.
- Evitado el bloqueo al inspeccionar streams continuos y mantenida activa la sesión mientras FFmpeg prepara el primer segmento.
- Desactivado el worker de HLS.js para evitar que extensiones del navegador rompan la reproducción cuando `MediaKeyMessageEvent` no está disponible.
- Añadido el scheduler autónomo de fuentes con intervalo predeterminado de 15 minutos.
- Actualizada la integración con AceStream Orchestrator a la API unificada `/api/v1`, con Bearer token opcional y errores estructurados.
- Adaptados el player y el dashboard a los campos actuales `container_id`, `content_id`, `stream_count`, peers y velocidades.
- Añadida caché independiente por fuente, migración desde la caché global y fallback ante fallos parciales.
- Añadida la arquitectura machine-readable del proyecto en [`AGENTS.md`](AGENTS.md).

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
| `ENABLE_TRANSCODE` | Habilita perfiles con recodificación | `false` |
| `ORCHESTRATOR_URL` | URL base de la API; vacío reutiliza `ACEXY_IP:ACEXY_PORT` | vacío |
| `ORCHESTRATOR_API_PREFIX` | Prefijo de la API unificada actual | `/api/v1` |
| `ORCHESTRATOR_API_TOKEN` | Bearer token; puede quedar vacío si no hay autenticación | `defaultpassword` |
| `ORCHESTRATOR_TIMEOUT` | Timeout de la API de gestión, en segundos | `5` |

`ACEXY_API_TOKEN` se mantiene únicamente como fallback de compatibilidad para `ORCHESTRATOR_API_TOKEN`.

### Desarrollo o build local

```bash
docker compose up -d --build
```

### Imagen publicada

```bash
docker compose -f release/docker-compose.yml pull ace-hls
docker compose -f release/docker-compose.yml up -d ace-hls
```

Acceso: `http://TU_IP:8088`.

## Fuentes y caché

Las fuentes se guardan en `sources.json`. El scheduler se inicia junto con la aplicación, comprueba la antigüedad de `channels.json` y actualiza las listas aunque ningún usuario abra la WebUI.

Cada fuente tiene un snapshot independiente dentro de `source_cache/`:

- Si responde correctamente, solo se reemplaza su propio snapshot.
- Si falla la descarga, devuelve contenido no M3U o intenta sustituir una caché no vacía por una lista vacía, se reutiliza su último snapshot válido.
- Los snapshots disponibles se combinan y deduplican para generar `channels.json` y `ace_hls.m3u` mediante reemplazo atómico.
- Al actualizar desde versiones anteriores, `channels.json` se migra automáticamente a snapshots por fuente.
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
| `/api/sources` | Gestión de fuentes |
| `/api/sources/refresh` | Refresh manual |
| `/api/sources/refresh/status` | Estado del scheduler |
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
PYTHONPATH=src python -m pytest -q
python -m compileall -q src tests
node --check src/app/static/script.js
docker compose config -q
docker build -t ace-hls-viewer:test .
```
