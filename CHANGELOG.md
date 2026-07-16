# Changelog

## v2.6.0-dev

- Convertido AceStream Orchestrator en el backend predeterminado de los Compose, fijado inicialmente en `v2.1.0.3`.
- Añadida configuración neutral `STREAM_*`, conservando aliases `ACEXY_*` durante v2.x.
- Añadida detección automática del endpoint directo LAN/VPN y override compatible con HTTP/HTTPS e IPv6.
- Compartido el Bearer token de gestión sin incluirlo en URLs de reproducción, respuestas ni logs.
- Conservado el stack AceXY anterior en Compose legacy y migrados sus ajustes persistentes.
- Ampliadas la WebUI, la API de configuración y la salud para mostrar el backend efectivo.

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
