# API HTTP

Todas las respuestas de gestión son JSON salvo las listas M3U, logs y archivos HLS. No hay autenticación: la API debe permanecer en LAN/VPN.

## Aplicación y diagnóstico

| Método | Ruta | Resultado |
|---|---|---|
| `GET` | `/` | WebUI. |
| `GET` | `/dashboard` | Dashboard local. |
| `GET` | `/api/version` | Versión y disponibilidad de transcodificación. |
| `GET` | `/health` | Disco, backend de streaming, sesiones FFmpeg y scheduler; devuelve 500 si está degradado. Incluye `stream_proxy` y el alias `acexy` durante v2.x. |
| `GET` | `/api/system/stats` | Métricas del host/contenedor y sesiones activas. |
| `GET` | `/api/system/logs` | Últimas 50 líneas de `app.log`. |
| `GET` | `/api/settings` | Ajustes persistentes de la WebUI. |
| `POST` | `/api/settings` | Mezcla el objeto JSON recibido en `settings.json`. |

## Canales y fuentes

| Método | Ruta | Resultado |
|---|---|---|
| `GET` | `/api/channels` | Canales normalizados con URL reproducible. |
| `GET` | `/api/sources` | Fuentes registradas y estado de validación/refresh. |
| `POST` | `/api/sources` | Valida y crea una fuente; devuelve 201. |
| `DELETE` | `/api/sources` | Compatibilidad v2.5.x: elimina por cuerpo `{"url":"…"}`. |
| `PATCH` | `/api/sources/<source_id>` | Edita nombre, URL o estado. Activar o cambiar URL obliga a validar. |
| `DELETE` | `/api/sources/<source_id>` | Elimina la fuente y su snapshot. |
| `POST` | `/api/sources/<source_id>/validate` | Revalida; `{"enable":true}` activa solo si es válida. |
| `POST` | `/api/sources/refresh` | Refresca todas las fuentes habilitadas. |
| `GET` | `/api/sources/refresh/status` | Estado del scheduler. |
| `GET` | `/api/custom-channels` | Lista canales personalizados. |
| `POST` | `/api/custom-channels` | Crea un canal personalizado; devuelve 201. |
| `PATCH` | `/api/custom-channels/<channel_id>` | Modifica un canal personalizado. |
| `DELETE` | `/api/custom-channels/<channel_id>` | Elimina un canal personalizado. |
| `POST` | `/api/stats/feedback` | Registra `{"id":"…","vote":"like|dislike"}`. |

Para guardar una fuente inválida desactivada, `POST` o `PATCH` debe incluir `"allow_invalid_disabled":true`. Los errores habituales usan 400, 404, 409 o 422 con `error` y `code`.

Un canal personalizado requiere `name` y `stream_id`; admite `group`, `logo` y `tvg_id`. Los duplicados se comparan por `identifier_type + stream_id`.

## Reproducción y listas

| Método | Ruta | Resultado |
|---|---|---|
| `GET` | `/api/hls/start/<ace_id>` | Inicia o reutiliza una sesión. Query: `profile`, `force`, `identifier_type`. |
| `GET` | `/api/hls/stop/<ace_id>` | Detiene una sesión. Query: `profile`, `identifier_type`. |
| `GET` | `/hls/<path:filename>` | Manifiestos y segmentos generados. |
| `GET` | `/proxy/hls/<ace_id>/index.m3u8` | Proxy de manifiesto HLS real. |
| `GET` | `/proxy/hls/<ace_id>/segment.ts` | Proxy de segmento. |
| `GET` | `/stream/<ace_id>.m3u8` | Redirección/arranque HLS para clientes externos. |
| `GET` | `/playlist.m3u` | Lista por perfil: `original`, `direct`, `max_compat`, `720p` o `480p`. |
| `GET` | `/api/playlist.m3u` | Alias de `/playlist.m3u`. |
| `GET` | `/api/playlist/all.m3u` | Variantes disponibles de todos los canales. |

`identifier_type` admite `id` (predeterminado) o `infohash`. Los perfiles con recodificación devuelven error si `ENABLE_TRANSCODE=false`.

## Orchestrator

| Método | Ruta | Upstream |
|---|---|---|
| `GET` | `/api/orchestrator/status` | `/api/v1/engines` |
| `GET` | `/api/orchestrator/streams` | `/api/v1/streams?status=started` |
| `GET` | `/api/orchestrator/overview` | `/api/v1/orchestrator/status` |
| `GET` | `/api/orchestrator/metrics` | `/api/v1/metrics/dashboard`; query `window_seconds`. |
| `GET` | `/api/orchestrator/config` | Backend, despliegue local/remoto, URL de gestión, hosts, puertos, endpoint público, panel y autenticación efectiva sin revelar el token. |

`STREAM_BACKEND=orchestrator` activa la integración automáticamente. Sin esa variable se conserva el ajuste `orchestrator_enabled`. Cuando está desactivada o el upstream falla, estos endpoints devuelven errores JSON estructurados en lugar de propagar una excepción Flask.

## Assets auxiliares

`GET /manifest.json` y `GET /sw.js` sirven los assets PWA. No forman parte de la API de gestión.
