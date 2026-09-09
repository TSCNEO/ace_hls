# Changelog

## v2.12.7

- **Control de Bitrate Estricto en Perfil max_compat (1080p):**
  - Eliminado el parámetro `-qp 18` sin límite de tasa en VAAPI que disparaba el bitrate a más de 44 Mbps (segmentos de 21 MB) provocando asfixia de buffer en VLC y bloqueos inmediatos en iOS Safari.
  - Fijado bitrate estricto a 5000 kbps (`-b:v 5000k -maxrate 5000k -bufsize 10000k`) tanto en VAAPI como en CPU. Los segmentos pesan ahora ~2.5 MB, garantizando fluidez continua sin parones en todos los clientes.

## v2.12.6

- **Optimización de Transcoding / Recode y Menú de Copia Multisuperficie en el Player:**
  - Eliminado el empaquetado fragmentado fMP4 (`.m4s` / `init.mp4`) en perfiles de recodificación (`max_compat`, `720p`, `480p`), unificando todos los perfiles en MPEG-TS (`.ts`). Esto elimina los errores de `Packet duration out of range`, falta de sincronización y parones recurrentes en VLC iOS y Safari.
  - Añadido `-g 50 -keyint_min 50 -bf 0` a todos los perfiles de transcodificación para garantizar keyframes cada 1-2 segundos sin retardo de reordenación B-frame. Los cortes de segmentos HLS son ahora limpios a 4 segundos exactos y el arranque es inmediato.
  - Forzado `h264_vaapi` y `-bsf:v dump_extra` en recode para asegurar decodificación por hardware compatible universalmente (especialmente Apple VideoToolbox).
  - Renovado el menú `🔗 Copiar...` en el reproductor web para permitir copiar con un clic cualquier superficie del canal activo: Perfil Actual, MPEG-TS Directo, HLS Original, HLS Compatibilidad, HLS 720p o HLS 480p.

## v2.12.5

- **Estabilidad de HLS contra microcortes y 404 en VLC/iOS:**
  - Ampliada ventana de playlist HLS (`-hls_list_size`) de 6 a 8 segmentos (32s).
  - Añadido umbral de retención en disco (`-hls_delete_threshold 6`): los segmentos obsoletos se mantienen en disco durante 6 ciclos adicionales antes de borrarse. Esto elimina los errores 404 cuando clientes como VLC o Safari van con 10-20s de búfer detrás del live edge.
  - El manifiesto inicial espera ahora a tener al menos 2 segmentos completos (`min_segments=2`, 8s) antes de declararse listo, proporcionando un colchón de búfer seguro desde el primer segundo.

## v2.12.4

- **Auto-arranque bajo demanda en rutas `/hls/<stream_id>/index.m3u8` y copiado directo:**
  - El endpoint `/hls/<stream_id>/index.m3u8` ahora inicia automáticamente el motor AceStream y FFmpeg si el stream no está corriendo en disco en lugar de devolver 404.
  - Añadido botón rápido `🔗` en cada tarjeta de canal para copiar el enlace HLS directamente al portapapeles sin necesidad de abrir el reproductor.
  - Los enlaces copiados desde el player o desde las tarjetas arrancan el motor de forma autónoma al ser reproducidos en VLC, Safari, Infuse, o cualquier cliente IPTV.
  - Renovación de Service Worker (`acehls-v2.12.4`).

## v2.12.3

- **Optimización de tiempo de arranque y Live Buffer en preparación:**
  - Reducida sonda FFmpeg (`-analyzeduration` y `-probesize`) de 10M a 3M en HLS, recortando ~2.2s de análisis de flujo en cada arranque.
  - Reducido intervalo de sondeo de upstream en `routes.py` de 1.5s a 0.75s para detección más rápida de datos listos.
  - Indicador de "Live Buffer" en el overlay de preparación (`#player-error-message`): muestra segundos transcurridos, peers conectados y velocidad real de descarga del enjambre P2P (MB/s).
  - Renovación de Service Worker (`acehls-v2.12.3`).

## v2.12.2

- **Corrección de SPS/PPS (`dump_extra`) para reproducción fluida en decodificador nativo iOS:**
  - Restaurado el bitstream filter `-bsf:v dump_extra` y `-hls_flags delete_segments+independent_segments` en el passthrough HLS.
  - Esto inyecta cabeceras SPS/PPS en el inicio de cada fragmento `.ts`, permitiendo a AVFoundation (Safari iOS) decodificar todos los fotogramas (25/50 fps) en vez de congelarse en 1 fotograma estático cada 6 segundos.
  - Bump a `v2.12.2` con renovación forzada del Service Worker (`acehls-v2.12.2`).

## v2.12.1

- **Restauración de línea base HLS probada (v2.9.0):**
  - Recuperado `-fflags +genpts+igndts` y HLS v3 estándar (`-hls_flags delete_segments`) en FFmpeg passthrough para evitar microcortes y congelaciones en el decodificador AVFoundation de Apple.
  - Eliminada la reescritura invasiva del overlay en `fetchEngineInfo` y simplificado el temporizador de carga del reproductor.
  - Priorización directa de HLS nativo en iOS Safari (`player.src = streamUrl`) con recarga forzada de Service Worker (`acehls-v2.12.1`).

## v2.12.0

- **Guía electrónica de programación (EPG XMLTV estándar y dinámico con soporte HTTPS):**
  - Generador automático `/epg.xml` y `/api/agenda/epg.xml` en formato XMLTV estándar a partir de los eventos deportivos y señales descubiertas.
  - Inyección dinámica de esquemas (`http://` o `https://`) y cabecera `Host` respetando `X-Forwarded-Proto` en todas las listas M3U (`/agenda.m3u`, `/playlist.m3u`, `/api/playlist/all.m3u` y `ace_hls.m3u`) para despliegues con proxy inverso SSL (Traefik, Nginx, Caddy, Cloudflare).
- **Player Inteligente / Heartbeat Guard consciente del Orquestador:**
  - Monitorización en tiempo real del enjambre P2P a través del orquestador (`/api/orchestrator/streams`).
  - Si el enjambre está descargando activamente (`speed_down > 20 KB/s` o `peers > 0`), el reproductor y el backend renuevan el temporizador de carga, evitando abortar sesiones sanas durante el prebuffering inicial.
  - Telemetría en vivo de conexión en la pantalla de preparación (`👤 X peers | ⬇️ Y KB/s`).
- **Conmutación a Backup 100% Opcional y Manual:**
  - Eliminados los saltos automáticos forzados a señales de respaldo: el usuario mantiene el control total.
  - Aviso interactivo ante señales inestables con opciones claras: `[ Probar señal #N ]`, `[ Reintentar ]` y `[ Cancelar ]`.
  - Botón visible de "Cancelar" y aspa de cierre en el diálogo de preparación para abortar sin bloqueos.
- **Corrección Crítica de Fluidez de Vídeo (Eliminación del bug de 2 fps en Directo):**
  - Inyección del bitstream filter `-bsf:v dump_extra` en modo passthrough (`-c copy`), garantizando que cada segmento `.ts` comience con sus parámetros de decodificación SPS/PPS para que el navegador decodifique todos los fotogramas sin descartes.
  - Emisión de la etiqueta HLS `#EXT-X-INDEPENDENT-SEGMENTS` en todas las listas para asegurar que cada fragmento es autónomo.
  - Eliminación de `+igndts` y adopción de `+discardcorrupt` en FFmpeg, corrigiendo el desorden de timestamps en streams con B-frames y garantizando cadencia perfecta a 25.0 / 50.0 fps con 0 frames caídos.
  - Calibración de FPS en frontend blindada: mide en régimen permanente (`currentTime >= 1.2s`), eliminando el bloqueo en lecturas transitorias de arranque.
- **Identificación Robusta del Motor AceStream:**
  - Detección directa del contenedor (`container_name`) desde el propio stream en el orquestador, eliminando el fallo que mostraba "Motor no identificado" en el HUD.
- **HUD de Estadísticas en Vivo ("Stats for Nerds"):**
  - Overlay flotante con telemetría unificada: motor P2P, enjambre/peers, velocidad de bajada, resolución, **fluidez real en FPS** (cifra verde `50 fps` o amarilla `25 fps`), buffer cliente y fotogramas caídos.
- **Alivio de Servidor (Eliminación de ffprobe):**
  - Eliminado el subproceso bloqueante `ffprobe` y el sondeo de segmentos en disco en el backend.
  - Endpoint `POST /api/channels/<ace_id>/tech_info` para reporte asíncrono y nativo desde el navegador.
- **Selector de pistas de audio (Multi-Audio / Radio):**
  - Detección y selector dinámico de pistas de audio secundarias (carrusel de radio, sonido ambiente, idiomas alternativos).
- **Gestos táctiles y salto al directo:**
  - Doble tap en pantalla (izquierda -10s / derecha +10s) con animación de ondas táctiles.
  - Botón de sincronización rápida al directo (`⚡ Directo`) con histéresis estable (se muestra con retardo > 15s, se oculta con < 5s).

## v2.11.3

- **Eliminación de falsas conmutaciones durante la reproducción:**
  - Eliminados listeners de `waiting` y `stalled` en la etiqueta `<video>`: en streams en vivo HLS, encontrarse en el live edge y esperar brevemente al siguiente segmento es un comportamiento estándar y no debe conmutar de canal.
  - Prioridad de recuperación: `recoverPlayback` reintenta en primer lugar el canal activo; únicamente tras agotar los reintentos locales conmuta a la señal de respaldo.
  - Aumentados timeouts de backend (`wait_timeout=20s`, `_wait_for_upstream_media=12s`) y frontend (`loadTimeout=35s`) para evitar falsos timeouts en arranques de canales fríos P2P.

## v2.11.2

- **Blindaje contra falsos positivos de failover:**
  - `Hls.Events.ERROR`: se prioriza la recuperación automática nativa de Hls.js (`recoverMediaError`) ante discontinuidades iniciales de PTS o timestamp en streams P2P, evitando que un salto de medio inicial fuerce la conmutación de canal prematura.
  - `stallTimer`: ampliado de 7.5s a 16s y acotado estrictamente a reproducción activa (`hasPlayedSuccessfully = true`), ignorando el buffer previo al primer fotograma.
  - `loadTimeout`: ampliado de 12s a 28s para respetar el tiempo normal de conexión P2P de AceStream (10-20s), cancelándose inmediatamente al avanzar `timeupdate` o `playing`.

## v2.11.1

- **Depuración de eventos pasados (+4h):** Los eventos deportivos que comenzaron hace más de 4 horas se purgan automáticamente de la agenda y de las listas M3U, manteniendo el catálogo limpio y actualizado.
- **Enfoque en la hora actual y vista colapsable de eventos pasados:** Al acceder a la Agenda, la parrilla empieza directamente por los eventos en curso y futuros. Los eventos finalizados en las últimas 4 horas se agrupan en un bloque colapsable superior (`⏪ Ver X eventos anteriores de hoy`) desplegable a demanda sin forzar scroll innecesario.
- **Ventana temporal T-15m en seguimiento:** Los partidos programados para más adelante no lanzan probes inmediatos; quedan programados con sondeo automático al entrar en los 15 minutos previos al inicio.

## v2.11.0

- **Failover automático en reproductor Web:** Cuando se reproduce un partido de la Agenda, el reproductor arma una cola con todas las señales alternativas del evento. Si la señal principal tarda más de 12 segundos en arrancar, falla el flujo HLS o se congela el vídeo más de 7s, conmuta automáticamente a la siguiente señal viva sin interrumpir al usuario.
- **Optimización de timeouts de arranque HLS:** Reducidos los tiempos de espera bloqueantes en el servidor de 45s a 14s por intento y 8s para detección de media, evitando cuelgues indefinidos en estado «Preparando stream».
- **Seguimiento inteligente de partidos (Match Tracking ⭐):** Marcado de partidos favoritos en la Agenda persistidos en navegador; botón de sondeo acotado (`POST /api/agenda/probe`) que prueba secuencialmente hasta 3 candidatos y se detiene en cuanto confirma 2 señales vivas (🟢 UP), sin sobrecargar el motor AceStream ni generar falsos positivos.
- Documentación ampliada en `docs/agenda.md` y `docs/api.md`.

## v2.10.1

- Rediseño compacto de la barra de herramientas de la Agenda Deportiva (`.agenda-toolbar`), eliminando espacios vacíos e integrando el estado de eventos en la cabecera.
- Pestañas selectoras de día (`[ 📅 Todos | ⚽ Hoy | 🗓️ Mañana | 🗓️ Pasado ]`) con contador dinámico de eventos en cada píldora.
- Desplegable de filtro por competición (`#agendaCompSelect`) generado dinámicamente según los eventos cargados.
- Reemplazo del emoji rojo por `⚡ En directo` tanto en filtros como en las tarjetas de eventos para evitar confusión con estados de error.
- Búsqueda en tiempo real por equipo, competición o canal combinable con el selector de día y competición.

## v2.10.0

- Añadido módulo de **Agenda Deportiva (EPG)**: eventos deportivos multidiarios sincronizados con `futbolenlatv.es/deporte`.
- Motor de emparejamiento inteligente de canales (`Channel Matcher`) con aislamiento estricto de números y diales de canal, detección de calidad y mapeo de equivalencias configurable.
- Nueva pestaña interactiva **⚽ Agenda** en la WebUI con filtrado por eventos disponibles, en directo o búsqueda textual y reproducción HLS en 1 clic.
- Exportación de lista M3U viva y dinámica en `/agenda.m3u` con multiseñal ordenada por calidad y perfiles por surface (`original`, `direct`, `max_compat`, `720p`, `all`).
- Nuevos endpoints de API: `/api/agenda`, `/api/agenda/live`, `/api/agenda/refresh` y `/api/agenda/playlist.m3u`.
- Documentación completa en `docs/agenda.md`.

- Añadido desplegable de filtro por fuente (`#sourceSelect`) en la cabecera: «Todas las fuentes (Mix)» o una fuente concreta.
- Al elegir una fuente concreta, `/api/channels?source=<id>` devuelve los canales **crudos de esa fuente sin deduplicar** (se ven los duplicados reales de cada lista).
- Añadida píldora compacta `· <fuente>` en cada tarjeta de canal para identificar el origen sin saturar pantallas pequeñas.
- El mix global (`/api/channels` sin parámetro) sigue deduplicando por identificador como antes.

## v2.8.0

- Añadido refresco concurrente de fuentes con `ThreadPoolExecutor` y parámetro configurable `SOURCE_REFRESH_WORKERS`.
- Añadida verificación rápida de hash en raíz (`content_hash`) para omitir descargas y resoluciones DNS redundantes cuando el contenido no ha variado (`not_modified`).
- Optimizado el pipeline de caché por fuente para reutilizar snapshots instantáneamente ante respuestas no modificadas.

## v2.7.0

- Añadido soporte nativo para fuentes e identificadores **MylinkPaste** resueltos mediante DoH (DNS over HTTPS).
- Implementado parser recursivo con descompresión GZIP y decodificación Base64 desde registros DNS TXT (`<ref>.elcano.top`).
- Añadida protección de ciclos en referencias circulares y límite de profundidad configurable.
- Soporte para DoH primario (Google DNS) y DoH de respaldo (Cloudflare).
- Añadido badge distintivo `MylinkPaste` en la lista de fuentes activas y persistencia automática en el esquema Sources 2.0.
- Optimización de carga asíncrona de canales con entrega inmediata desde caché.

## v2.6.0

- Convertido AceStream Orchestrator en el backend predeterminado de los Compose, fijado inicialmente en `v2.1.0.3`.
- Añadida configuración neutral `STREAM_*`, conservando aliases `ACEXY_*` durante v2.x.
- Añadida detección automática del endpoint directo LAN/VPN y override compatible con HTTP/HTTPS e IPv6.
- Compartido el Bearer token de gestión sin incluirlo en URLs de reproducción, respuestas ni logs.
- Conservado el stack AceXY anterior en Compose legacy y migrados sus ajustes persistentes.
- Ampliadas la WebUI, la API de configuración y la salud para mostrar el backend efectivo.
- Añadido despliegue con Orchestrator externo mediante IP, hostname o IPv6, sin crear servicios ni montar Docker socket localmente.
- Añadidos Compose y ejemplo de entorno remotos, junto con una guía completa de instalación, verificación, actualización y diagnóstico.
- Añadido `easy-deploy` con variantes local y remota sin build, volúmenes estables y etiquetas de imagen versionadas.
- Añadido empaquetado ZIP reproducible y publicación automática del asset al crear una etiqueta estable.

## v2.5.1

- Reorganizada y contrastada toda la documentación de instalación, configuración, API, persistencia y entrega.
- Sincronizadas las variables de entorno entre `.env.example` y los Compose.
- Actualizado AceXY a `0.2.2` también en el Compose de release.
- Eliminadas referencias y comentarios obsoletos; añadidas pruebas de sincronización documental.

## v2.5.0

- Añadido Sources 2.0 con esquema versionado, migración atómica, backup único y caché por ID estable.
- Añadido parser compartido para M3U y respuestas JSON de AceStream, con soporte de `id` e `infohash`.
- Añadido CRUD, activación, revalidación y estado de fuentes en API y WebUI.
- Añadido CRUD de canales personalizados con precedencia de metadatos y reconstrucción sin red.
- Endurecido el renderizado de datos remotos y la exportación M3U.
- Parametrizada la imagen de Compose y protegida la publicación de `latest` para versiones `-dev`.
- Publicación Docker multi-arquitectura para servidores AMD64/Intel y hosts ARM64.
