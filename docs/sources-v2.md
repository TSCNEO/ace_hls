# Sources 2.0

## Persistencia

`sources.json` usa `schema_version: 2`. Cada elemento de `sources` contiene `id`, `name`, `url`, `kind`, `enabled`, `created_at`, `updated_at`, el último resultado `validation` y el estado `refresh`. Los IDs `src-…` son estables durante una edición; en la migración se derivan de la URL.

`custom_channels.json` usa `schema_version: 1`. Cada canal contiene `id`, `name`, `stream_id`, `identifier_type`, `group`, `logo`, `tvg_id`, `created_at` y `updated_at`. La pareja `identifier_type + stream_id` es única.

## Migración

Al leer por primera vez un `sources.json` v1 (array de `{url, added_at}`), AceHLS toma un bloqueo de proceso, crea una sola copia `sources.v1.backup.json` y reemplaza el registro de forma atómica por el esquema 2. Los IDs se derivan de la URL, por lo que repetir la operación no crea fuentes nuevas. La migración no accede a la red.

Las cachés antiguas nombradas con el hash de la URL se trasladan al ID estable de la fuente cuando se reconstruyen los canales. `channels.json` nunca se vacía si todas las fuentes fallan. Los esquemas futuros desconocidos no se modifican: las mutaciones devuelven un error estructurado y la aplicación conserva las salidas ya generadas.

## Validación y Tipos de Fuentes

AceHLS admite los siguientes tipos de fuentes (`kind`):
1. **Listas M3U (`m3u`)**: URLs HTTP(S) con cabecera `#EXTM3U` (incluyendo BOM UTF-8).
2. **IDs y Enlaces MylinkPaste (`mylinkpaste`)**: Códigos alfanuméricos directos o esquemas `mylinkpaste://<ID>` resueltos dinámicamente mediante DNS TXT sobre DoH.

Cada entrada de canal debe contener una URI `acestream://`, `infohash://`, un hash hexadecimal de 40 caracteres o una URL con `id`, `content_id` o `infohash` (query decodificada y sin sensibilidad a mayúsculas).

### Resolución de Fuentes MylinkPaste
Para fuentes de tipo MylinkPaste:
- Se realiza una consulta DNS TXT (Tipo 16) vía DNS over HTTPS (DoH) hacia `<code_o_ref>.elcano.top` utilizando Google DNS DoH (`https://dns.google/resolve`) con fallback automático a Cloudflare DoH (`https://cloudflare-dns.com/dns-query`).
- El registro TXT se desfragmenta, decodifica desde Base64 y se descomprime mediante GZIP si contiene la firma `\x1f\x8b`.
- El JSON resultante se parsea recursivamente:
  - Objetos con `type: "category"` y `ref: "<hash>"` se resuelven recursivamente heredando el nombre de grupo/categoría.
  - Objetos con `subLinks` se expanden para extraer los canales con esquemas `acestream://<HASH>`.
  - El resolver incorpora detección de referencias circulares (ciclos) y límite de profundidad (`max_depth = 10`).
- Las fuentes pueden añadirse mediante su identificador directo o formato URI `mylinkpaste://<ID>`.

Una fuente se valida antes de activarse. Una respuesta inválida solo puede guardarse enviando `allow_invalid_disabled=true`; el servidor fuerza `enabled=false`. Las fuentes desactivadas no se descargan ni aportan canales. Editar una URL conserva el ID y la caché anterior, aunque esa caché no se mezcla mientras la fuente siga desactivada.

La descarga tiene límite de 10 MiB, timeout de conexión de 8 s y lectura de 30 s. Por compatibilidad con instalaciones internas, LAN y VPN, `SOURCE_TLS_VERIFY=false` es el valor predeterminado. Esta versión no incorpora login, CSRF, rate limiting ni restricciones SSRF y no debe exponerse directamente a Internet.

## API

- `GET/POST /api/sources`
- `PATCH/DELETE /api/sources/{source_id}`
- `POST /api/sources/{source_id}/validate`
- `POST /api/sources/refresh`
- `GET/POST /api/custom-channels`
- `PATCH/DELETE /api/custom-channels/{channel_id}`

Durante v2.5.x se mantienen el alta `{url}` y el borrado por URL. Los canales personalizados se almacenan en `custom_channels.json`, se mezclan antes que las fuentes remotas y sus metadatos prevalecen cuando el identificador coincide.

El alta de fuente acepta `name`, `url` y, solo para conservarla desactivada tras un error, `allow_invalid_disabled`. La edición admite `name`, `url` y `enabled`. Un canal personalizado exige `name` y `stream_id`; `group`, `logo` y `tvg_id` son opcionales.
