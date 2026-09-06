# Configuración

La infraestructura se configura mediante entorno. La WebUI guarda sus ajustes en `settings.json`. El despliegue predeterminado está pensado para LAN/VPN y usa AceStream Orchestrator.

## Backend de streaming

| Variable | Predeterminado en Compose | Uso |
|---|---:|---|
| `STREAM_BACKEND` | `orchestrator` | `orchestrator` o `acexy`; selecciona el backend y la integración de gestión. |
| `STREAM_PROXY_HOST` | `orchestrator` | Host interno usado por AceHLS y FFmpeg. |
| `STREAM_PROXY_PORT` | `8000` | Puerto interno del proxy. |
| `STREAM_PUBLIC_PORT` | `8000` | Puerto publicado y usado al calcular listas directas. |
| `STREAM_PUBLIC_ENDPOINT` | vacío | Override HTTP/HTTPS completo; admite dominio, IPv6, ruta y puerto propios. |

En modo local y sin override, una petición a `http://192.168.1.20:8088` produce enlaces directos `http://192.168.1.20:8000/ace/getstream`. En modo remoto se usa `ORCHESTRATOR_HOST:ORCHESTRATOR_PORT`.

Durante v2.x, `ACEXY_IP`, `ACEXY_PORT` y `ACEXY_PUBLIC_ENDPOINT` son aliases de `STREAM_PROXY_HOST`, `STREAM_PROXY_PORT` y `STREAM_PUBLIC_ENDPOINT`. Las variables nuevas tienen prioridad. `ACEXY_PUBLIC_TOKEN` se conserva solo para AceXY y nunca recibe el token de gestión del Orchestrator.

## AceStream Orchestrator

| Variable | Predeterminado | Uso |
|---|---:|---|
| `ORCHESTRATOR_MODE` | `local` | `local` o `remote`; describe el despliegue efectivo en API y WebUI. |
| `ORCHESTRATOR_HOST` | `orchestrator` | Host del servicio; en remoto es obligatorio y admite IPv4, hostname o IPv6. |
| `ORCHESTRATOR_PORT` | `8000` | Puerto accesible del Orchestrator; en local debe conservar el puerto interno `8000`. |
| `ORCHESTRATOR_IMAGE` | `ghcr.io/krinkuto11/acestream-orchestrator:v2.1.0.3` | Imagen fijada, reemplazable al probar otra versión. |
| `ORCHESTRATOR_URL` | derivada de host y puerto | Override exclusivo de la base de la API de gestión. |
| `ORCHESTRATOR_API_PREFIX` | `/api/v1` | Prefijo de gestión. |
| `ORCHESTRATOR_API_TOKEN` | `change-this-local-token` | Se pasa como `API_KEY` y como Bearer token de AceHLS. |
| `ORCHESTRATOR_TIMEOUT` | `5` | Timeout de gestión en segundos. |
| `ORCHESTRATOR_VPN_ENABLED` | `false` | Activa la VPN administrada; requiere configurarla después en el panel. |

El panel está en `http://HOST:8000/panel` y la salud del proxy en `/proxy/health`. El Compose monta `/var/run/docker.sock`, persiste `/app/app/config` en `orchestrator_data` y establece `DOCKER_NETWORK=ace_hls_stream`. El token protege operaciones de gestión; el endpoint `/ace/getstream` permanece accesible sin añadir secretos a la URL.

El Compose remoto está en `docker-compose.orchestrator-remote.yml` y su variante publicada en `release/docker-compose.orchestrator-remote.yml`. Solo crea AceHLS. Usa `.env.orchestrator-remote.example` como base y consulta la [guía de despliegue](orchestrator-deployment.md).

`STREAM_PROXY_HOST/PORT` prevalece sobre `ORCHESTRATOR_HOST/PORT` para la reproducción interna. `ORCHESTRATOR_URL` solo afecta a gestión y `STREAM_PUBLIC_ENDPOINT` solo a enlaces para clientes.

`ACEXY_API_TOKEN` sigue siendo fallback de `ORCHESTRATOR_API_TOKEN` para despliegues antiguos que no usen los Compose suministrados.

## Easy Deploy

`easy-deploy/orchestrator-local` y `easy-deploy/orchestrator-remote` son los Compose recomendados para usuarios finales. Solo contienen referencias `image`, fijan la versión de AceHLS incluida en el paquete y no ejecutan builds.

| Variable Compose | Predeterminado | Uso |
|---|---:|---|
| `ACE_HLS_IMAGE` | versión fija del paquete | Override excepcional de la imagen AceHLS. |
| `ACE_HLS_DATA_VOLUME` | `ace_hls_data` | Nombre estable del volumen compartido por ambas variantes. |
| `ORCHESTRATOR_DATA_VOLUME` | `ace_hls_orchestrator_data` | Persistencia del Orchestrator local. |

Al migrar desde otro Compose, se puede asignar a `ACE_HLS_DATA_VOLUME` el nombre anterior mostrado por `docker volume ls`. Nunca se debe ejecutar `docker compose down -v` durante el cambio.

## Aplicación AceHLS

| Variable | Predeterminado | Uso |
|---|---:|---|
| `ACE_HLS_PORT` | `8088` | Puerto publicado de la WebUI. |
| `DATA_DIR` | `/app/data` | Directorio persistente interno. |
| `URL_ORIGEN` | vacío | Fuente inicial opcional. |
| `CACHE_DURATION` | `300` | Antigüedad de `channels.json` antes del refresh bajo demanda. |
| `PLAYLIST_REFRESH_INTERVAL` | `900` | Intervalo autónomo; mínimo 60 segundos. |
| `SOURCE_CONNECT_TIMEOUT` | `8` | Timeout de conexión de fuentes. |
| `SOURCE_READ_TIMEOUT` | `30` | Timeout de lectura de fuentes. |
| `SOURCE_MAX_BYTES` | `10485760` | Límite por respuesta. |
| `SOURCE_TLS_VERIFY` | `false` | Verificación TLS; `false` mantiene certificados LAN/VPN propios. |
| `SOURCE_REFRESH_WORKERS` | `4` | Concurrencia máxima para refresco paralelo de fuentes. |
| `FFMPEG_RW_TIMEOUT` | `60` | Timeout upstream de FFmpeg. |
| `HLS_IDLE_TIMEOUT` | `120` | Inactividad antes de detener FFmpeg; mínimo 60 segundos. |
| `ENABLE_TRANSCODE` | `false` | Habilita `max_compat`, `720p` y `480p`. |
| `TRANSCODE_720P_BITRATE` | `2500k` | Bitrate inicial 720p. |
| `TRANSCODE_480P_BITRATE` | `1000k` | Bitrate inicial 480p. |
| `TRANSCODE_COMPAT_CRF` | `23` | CRF del perfil compatible. |
| `MYLINKPASTE_DOMAIN_SUFFIX` | `elcano.top` | Sufijo de dominio DNS para resolver referencias MylinkPaste. |
| `MYLINKPASTE_DOH_PRIMARY` | `https://dns.google/resolve` | Endpoint primario DoH (DNS over HTTPS) para registros TXT. |
| `MYLINKPASTE_DOH_BACKUP` | `https://cloudflare-dns.com/dns-query` | Endpoint secundario DoH de respaldo. |

## Ajustes persistentes

| Clave | Predeterminado | Uso |
|---|---:|---|
| `stream_public_endpoint` | entorno o vacío | Override de la URL directa. |
| `stream_public_token` | vacío | Token por query exclusivo de AceXY legacy. |
| `orchestrator_enabled` | `false` | Compatibilidad cuando `STREAM_BACKEND` no está definido. |
| `transcode_720p_bitrate` | `2500k` | Bitrate 720p. |
| `transcode_480p_bitrate` | `1000k` | Bitrate 480p. |
| `transcode_compat_crf` | `23` | Calidad compatible. |
| `transcode_video_codec` | `h264` | Códec solicitado. |
| `transcode_audio_bitrate` | `128k` | Bitrate de audio. |
| `transcode_preset` | `veryfast` | Preset CPU. |
| `transcode_deinterlace` | `false` | Desentrelazado. |

Al abrir una instalación anterior, `acexy_public_endpoint` y `acexy_public_token` se migran atómicamente a las claves neutrales. Si `STREAM_BACKEND` está definido, el modo del entorno prevalece y el checkbox queda informativo.

## Compose legacy AceXY

`docker-compose.acexy.yml` y `release/docker-compose.acexy.yml` conservan AceXY `0.2.2` más el motor estático. Usan `ACEXY_PORT`, `ACEXY_PUBLIC_ENDPOINT`, `ACEXY_PUBLIC_TOKEN`, `ACEXY_SCHEME`, `ACEXY_HOST`, `ACESTREAM_PORT`, `ACEXY_M3U8_STREAM_TIMEOUT`, `ACEXY_M3U8`, `ACEXY_EMPTY_TIMEOUT`, `ACEXY_BUFFER_SIZE` y `ACEXY_NO_RESPONSE_TIMEOUT`.

`ACE_HLS_IMAGE` selecciona la imagen de AceHLS en los Compose de release. Para VAAPI hay que montar `/dev/dri`.

No se incluyen login, CSRF ni restricciones de red. El puerto `8000`, el panel y el Docker socket asociado al Orchestrator deben permanecer en una red confiable.
