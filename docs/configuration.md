# Configuración

La configuración de infraestructura se carga desde variables de entorno. Los ajustes modificables en la WebUI se guardan en `settings.json` y prevalecen para las opciones que gestiona la interfaz.

## Aplicación AceHLS

| Variable | Predeterminado | Uso |
|---|---:|---|
| `ACE_HLS_PORT` | `8088` | Puerto publicado por Docker Compose. |
| `DATA_DIR` | `/app/data` | Directorio persistente dentro del contenedor. |
| `ACEXY_IP` | `acexy` en Compose | Host interno de AceXY o del proxy de streams. |
| `ACEXY_PORT` | `8080` | Puerto HTTP de AceXY. |
| `URL_ORIGEN` | vacío en `.env.example` | Fuente inicial opcional, creada solo si no existe `sources.json`. |
| `CACHE_DURATION` | `300` | Antigüedad máxima de `channels.json` antes de refrescar al consultar canales. |
| `PLAYLIST_REFRESH_INTERVAL` | `900` | Intervalo del scheduler; mínimo efectivo 60 segundos. |
| `SOURCE_CONNECT_TIMEOUT` | `8` | Timeout de conexión de una fuente, en segundos. |
| `SOURCE_READ_TIMEOUT` | `30` | Timeout de lectura de una fuente, en segundos. |
| `SOURCE_MAX_BYTES` | `10485760` | Tamaño máximo descargado por validación, en bytes. |
| `SOURCE_TLS_VERIFY` | `false` | Verificación TLS. Se mantiene desactivada para certificados internos/LAN/VPN. |
| `FFMPEG_RW_TIMEOUT` | `60` | Timeout de lectura upstream de FFmpeg, en segundos. |
| `HLS_IDLE_TIMEOUT` | `120` | Inactividad antes de detener una sesión FFmpeg; mínimo efectivo 60 segundos. |
| `ENABLE_TRANSCODE` | `false` | Habilita `max_compat`, `720p` y `480p`. |
| `TRANSCODE_720P_BITRATE` | `2500k` | Bitrate inicial del perfil 720p. |
| `TRANSCODE_480P_BITRATE` | `1000k` | Bitrate inicial del perfil 480p. |
| `TRANSCODE_COMPAT_CRF` | `23` | CRF inicial del perfil compatible. |
| `ACEXY_PUBLIC_ENDPOINT` | vacío | Base pública de AceXY usada por listas `direct`. |
| `ACEXY_PUBLIC_TOKEN` | vacío | Token añadido al endpoint público de AceXY. |

Los valores de transcodificación y endpoint público se copian a `settings.json` al crearlo. Después se administran desde la WebUI; cambiar solo el entorno no reemplaza un `settings.json` existente.

| Ajuste en `settings.json` | Predeterminado | Uso |
|---|---:|---|
| `transcode_720p_bitrate` | `2500k` | Bitrate del perfil 720p. |
| `transcode_480p_bitrate` | `1000k` | Bitrate del perfil 480p. |
| `transcode_compat_crf` | `23` | Calidad del perfil compatible. |
| `transcode_video_codec` | `h264` | Códec solicitado: `h264` o `hevc`; los perfiles escalados usan H.264 actualmente. |
| `transcode_audio_bitrate` | `128k` | Bitrate de audio al recodificar. |
| `transcode_preset` | `veryfast` | Preset de codificación por CPU. |
| `transcode_deinterlace` | `false` | Activa desentrelazado. |
| `acexy_public_endpoint` | vacío | Base de AceXY para listas directas. |
| `acexy_public_token` | vacío | Token del endpoint público. |
| `orchestrator_enabled` | `false` | Activa las consultas de gestión al Orchestrator. |

## AceStream Orchestrator

| Variable | Predeterminado | Uso |
|---|---:|---|
| `ORCHESTRATOR_URL` | `http://ACEXY_IP:ACEXY_PORT` | URL base de la API de gestión. |
| `ORCHESTRATOR_API_PREFIX` | `/api/v1` | Prefijo de la API. |
| `ORCHESTRATOR_API_TOKEN` | valor de `ACEXY_API_TOKEN` | Bearer token; puede quedar vacío. |
| `ORCHESTRATOR_TIMEOUT` | `5` | Timeout de gestión, en segundos. |
| `ACEXY_API_TOKEN` | `defaultpassword` | Fallback de compatibilidad para el token del Orchestrator. |

La integración no realiza peticiones hasta activarla en Ajustes. La API consulta `/engines`, `/streams?status=started`, `/orchestrator/status` y `/metrics/dashboard` bajo el prefijo configurado.

## Stack AceXY/AceStream

Estas variables pertenecen a los servicios del Compose, no al proceso Flask:

| Variable | Predeterminado |
|---|---:|
| `ACEXY_SCHEME` | `http` |
| `ACEXY_HOST` | `acestream` |
| `ACESTREAM_PORT` | `6878` |
| `ACEXY_M3U8_STREAM_TIMEOUT` | `60s` |
| `ACEXY_M3U8` | `false` |
| `ACEXY_EMPTY_TIMEOUT` | `60s` |
| `ACEXY_BUFFER_SIZE` | `4MB` |
| `ACEXY_NO_RESPONSE_TIMEOUT` | `10s` |

## Imagen y hardware

`ACE_HLS_IMAGE` selecciona la imagen en `release/docker-compose.yml`; si no se define usa `tscneo/ace-hls-viewer:latest`.

Para VAAPI hay que descomentar el montaje de `/dev/dri` en el Compose. La aplicación usa `/dev/dri/renderD128` cuando existe; en otro caso transcodifica por CPU.

Este despliegue está diseñado para una red confiable. `SOURCE_TLS_VERIFY=false`, la ausencia de login/CSRF y el acceso permitido a IP privadas son decisiones de compatibilidad interna, no una configuración apta para Internet.
