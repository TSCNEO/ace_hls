# Changelog

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
