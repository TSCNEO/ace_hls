# Agenda Deportiva y Guía EPG Dinámica (AceHLS)

AceHLS incluye un módulo integrado de **Agenda Deportiva (EPG)** que transforma la lista pasiva de canales en un **Centro de Eventos en Directo**: permite consultar los partidos y competiciones de Hoy, Mañana y Pasado Mañana, verificar qué eventos tienen canales sintonizables en tu servidor y reproducirlos en un clic o exportarlos dinámicamente en formato M3U para reproductores externos (TiviMate, iSTB, VLC, Jellyfin).

---

## 1. Origen de Datos

La programación se obtiene directamente de:
* **Fuente:** `https://www.futbolenlatv.es/deporte`
* **Periodicidad:** La información se actualiza automáticamente en segundo plano con una caché configurable (por defecto 30 minutos) o bajo demanda mediante la API o la interfaz web.
* **Cobertura multidiaria:** Agrupa los eventos en tres bloques temporales: *Hoy*, *Mañana* y *Pasado Mañana*.

---

## 2. Motor de Emparejamiento de Canales (Channel Matcher)

Para que un evento deportivo muestre el botón de reproducción, el sistema analiza los canales de televisión asociados al evento en la guía y los cruza con los canales sintonizables que tengas dados de alta en AceHLS (procedentes de tus listas M3U o canales personalizados).

### Aislamiento estricto de diales y números
El normalizador separa los adornos del canal (`1080p`, `FHD`, `★`, `🔹`, etiquetas de calidad o notas de origen) pero **conserva de forma estricta el identificador numérico o dial**:
* Un partido emitido en `M+ Liga de Campeones 2` **únicamente** se emparejará con señales que contengan el número `2`. Jamás se emparejará con el canal principal `M+ Liga de Campeones` ni con el dial `3`.
* `DAZN 1` solo empareja con señales del canal 1, sin mezclarse con `DAZN 2` ni con `DAZN LaLiga`.

### Detección de Calidad
El motor extrae la resolución declarada en cada señal (`1080p`, `720p`, `4K`, `SD`) y las ordena de mayor a menor calidad para priorizar la mejor emisión disponible.

### Equivalencias y Personalización
AceHLS incorpora un mapa canónico interno de equivalencias entre los nombres de televisión y los nombres habituales en catálogos de streaming.
Si deseas añadir equivalencias propias o adaptar nombres específicos, puedes colocar un archivo JSON en:
`/app/data/equivalencias_canales.json`

Formato admitido:
```json
{
  "Nombre Canal en Guía (Dial)": ["Nombre En Catalogo 1", "Nombre En Catalogo 2"],
  "M+ LALIGA (M54 O110)": ["M+ LaLiga", "Movistar LaLiga"]
}
```

---

## 3. Lista M3U Dinámica de Eventos (`/agenda.m3u`)

AceHLS expone una lista M3U viva en una URL fija:

```
http://<ip-o-host>:8088/agenda.m3u
```

### Características
* **Actualización en tiempo real:** A medida que los eventos van finalizando o entrando en emisión, la lista se refresca automáticamente sin necesidad de editar la URL en tus clientes IPTV.
* **Detección multiseñal:** Si un evento importante (ej. un partido de liga) cuenta con múltiples emisiones disponibles en tu catálogo (de distintas fuentes o calidades), la lista genera una entrada independiente para cada señal, indicando calidad y origen en el título.
* **Marcado de emisión en directo:** Los eventos que se están disputando en el momento de la consulta se marcan automáticamente con el prefijo `[⚡ VIVO]`.

### Modos de Reproducción (Surfaces / Perfiles)
Mediante el parámetro `profile`, puedes elegir qué superficie de reproducción entrega la lista:

| Perfil | URL | Uso recomendado |
|---|---|---|
| **HLS Original (Passthrough)** | `/agenda.m3u?profile=original` | Predeterminado. Calidad nativa sin recodificar. |
| **Directo AceStream** | `/agenda.m3u?profile=direct` | Enlaces nativos de streaming para reproductores compatibles. |
| **Compatible (H.264)** | `/agenda.m3u?profile=max_compat` | Recodificación H.264 para navegadores o clientes antiguos. |
| **Transcodificado 720p** | `/agenda.m3u?profile=720p` | Ahorro de ancho de banda para conexiones móviles o remotas. |
| **Mega-Lista Unificada (All)** | `/agenda.m3u?profile=all` | Incluye todas las surfaces agrupadas en categorías IPTV (`group-title`). |

Ejemplo de agrupación en modo `profile=all`:
* `group-title="⚽ Hoy · Directo"`
* `group-title="⚽ Hoy · HLS Original"`
* `group-title="⚽ Hoy · HLS 720p"`
* `group-title="⚽ Mañana · HLS Original"`

---

## 4. Uso en la WebUI

1. En la barra superior de AceHLS, pulsa en la pestaña **⚽ Agenda**.
2. **Pestañas de Día:** Alterna entre `[ 📅 Todos | ⚽ Hoy | 🗓️ Mañana | 🗓️ Pasado ]` con los contadores de eventos activos en cada pestaña.
3. **Filtro por Competición:** Utiliza el menú desplegable dinámico para aislar competiciones específicas (ej. *LaLiga EA Sports*, *Champions League*, *US Open*, etc.).
4. **Búsqueda y Filtros:** Escribe el nombre de cualquier equipo o canal en el buscador, activa la casilla **🟢 Solo disponibles** o filtra por eventos **⚡ En directo**.
5. Haz clic en **▶ Ver** en cualquier partido para abrir inmediatamente el reproductor integrado HLS de AceHLS.
6. Para copiar o descargar la lista M3U de eventos, abre el menú desplegable **📋 M3U** de la cabecera y selecciona **⚽ Agenda**.

---

## 5. Endpoints de la API

* `GET /api/agenda`: Devuelve el JSON estructurado de la agenda cruzada con tu catálogo. Query opcional: `refresh=true`, `live_only=true`, `available_only=true`.
* `GET /api/agenda/live`: Devuelve únicamente los eventos en vivo en la franja horaria actual.
* `POST /api/agenda/refresh`: Fuerza la descarga y procesamiento inmediato de la guía externa.
* `GET /agenda.m3u`: Exporta la lista M3U dinámica (admite `?profile=...` y `?live_only=true`).
* `GET /api/agenda/playlist.m3u`: Alias de `/agenda.m3u`.
