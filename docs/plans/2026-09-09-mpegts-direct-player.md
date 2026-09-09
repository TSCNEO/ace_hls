# Reproducción Directa MPEG-TS en Chromium (VLC-Like) sin FFmpeg

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Dotar a AceHLS de un motor de reproducción directa MPEG-TS en el navegador (`mpegts.js`) para clientes compatibles (Chromium, Firefox, Android), eliminando por completo el proceso FFmpeg en el servidor, el uso de disco y la latencia en modo Directo, con degradación automática a HLS en iOS Safari.

**Architecture:** El cliente web detecta las capacidades del navegador (`mpegts.isSupported()`). Si está soportado y el perfil es Directo (`original`), se conecta mediante `fetch()` en streaming continuo a un endpoint de proxy ligero en el backend (`/api/stream/direct/<id>`), demuxeando los paquetes TS en RAM con Web Workers e inyectándolos directamente a `MediaSource` (MSE). Si no está soportado (iOS Safari) o se solicita recodificación (`max_compat`), conmuta de forma transparente al stack HLS actual con FFmpeg.

**Tech Stack:** `mpegts.js` (v1.7.3+), HTML5 MediaSource Extensions (MSE), Web Workers, Python Flask/Gunicorn stream proxy, JavaScript ES6.

---

## 1. Contexto y Diagnóstico

### Situación Actual (Modo Directo con HLS)
1. El usuario selecciona un canal en modo Directo (`profile=original`).
2. AceHLS levanta un subproceso FFmpeg en el servidor:
   ```bash
   ffmpeg -i http://192.168.90.10:8000/ace/getstream?id=<id> -c copy -bsf:v dump_extra -hls_time 4 -hls_list_size 6 ...
   ```
3. FFmpeg trocea el flujo continuo en segmentos `.ts` de 4 segundos y escribe `index.m3u8` en disco.
4. El navegador usa `Hls.js` para pedir fragmentos HTTP sucesivos.
5. **Peajes:** 
   - Latencia forzada de 8 a 12 segundos respecto al directo.
   - Escritura continua en disco/tmpfs del contenedor (`index0.ts` .. `index5.ts`).
   - Ciclo de vida y monitorización de procesos FFmpeg.

### La Experiencia VLC / TiviMate
- VLC y TiviMate se conectan al socket HTTP continuo de AceStream (`/ace/getstream`).
- Leen paquetes de 188 bytes MPEG-TS en crudo y los reproducen al vuelo con latencia de 200-500 ms.

### Solución: `mpegts.js` en Navegadores Compatibles
- `mpegts.js` (sucesor de `flv.js` desarrollado por Bilibili) implementa un demuxer de MPEG-TS en JavaScript.
- Lee el flujo HTTP chunked continuo, convierte los paquetes TS a fragmentos ISO BMFF (fMP4) en memoria mediante un Web Worker y los envía al `<video>` mediante `SourceBuffer.appendBuffer()`.
- **Compatibilidad:**
  - ✅ Google Chrome (Desktop / Android / Android TV)
  - ✅ Microsoft Edge, Brave, Opera, Vivaldi
  - ✅ Mozilla Firefox (Desktop / Android)
  - ❌ iOS / iPadOS Safari (Apple no soporta MSE para vídeo en vivo; fallback obligatorio a HLS).

---

## 2. Mapa de Tareas de Implementación

### Task 1: Vendorizar `mpegts.js` en Frontend
**Objective:** Incorporar la librería `mpegts.js` minificada en los estáticos del proyecto para despliegues 100% offline y herméticos.
- **Files:**
  - Create: `src/app/static/vendor/mpegts.min.js`
  - Modify: `src/app/static/index.html` (inclusión condicional del script con versión)
  - Test: `tests/test_frontend_config.py` (comprobar existencia e importación en HTML)

### Task 2: Endpoint Backend de Proxy Directo Continuo (`/api/stream/direct/<id>`)
**Objective:** Proporcionar una ruta en AceHLS que conecte con AceStream Orchestrator (`/ace/getstream`) y reenvíe el flujo continuo `video/mp2t` con cabeceras `Transfer-Encoding: chunked`, `Access-Control-Allow-Origin: *` y gestión de cierre limpio de socket cuando el cliente pausa o sale.
- **Files:**
  - Modify: `src/app/routes.py`
  - Test: `tests/test_direct_stream_route.py`
  - Contract: Devolver `Content-Type: video/mp2t`, soportar parámetros `identifier_type=id|infohash`.

### Task 3: Controlador de Reproducción Dual (`MpegtsController` vs `HlsController`)
**Objective:** Implementar en `script.js` un selector de motor de reproducción en cliente:
- Si `playerMode === 'direct'` Y `window.mpegts && mpegts.isSupported()`:
  - Instanciar `mpegts.createPlayer({ type: 'mse', isLive: true, url: directStreamUrl })`.
  - Configurar `liveBufferLatencyChasing: true`, `enableWorker: true`, `stashInitialSize: 128KB`.
- En cualquier otro caso (iOS, modo `max_compat`, `720p`):
  - Mantener el flujo `attachHlsToPlayer()` actual con `Hls.js`.
- **Files:**
  - Modify: `src/app/static/script.js`
  - Test: `tests/test_sources_v2.py` / `tests/test_frontend_config.py`

### Task 4: Adaptación del HUD "Stats for Nerds" para MPEG-TS
**Objective:** Permitir que el HUD lea estadísticas tanto si el motor activo es Hls.js como si es `mpegts.js` (`mpegtsPlayer.statisticsInfo`, buffer en segundos, dropped frames nativos de `getVideoPlaybackQuality`).
- **Files:**
  - Modify: `src/app/static/script.js`

### Task 5: Selectores de UI y Fallback Transparente
**Objective:** Agregar selector de modo en la interfaz (Directo MPEG-TS vs HLS) o detección automática, y en caso de error de red en `mpegts.js` degradar automáticamente a HLS con aviso en pantalla.
- **Files:**
  - Modify: `src/app/static/index.html`
  - Modify: `src/app/static/script.js`

---

## 3. Guía de Ejecución

1. **Entorno de Trabajo:**
   - Rama recomendada: `feat/mpegts-direct-player`
   - Host de pruebas: CT 112 (`192.168.90.16`)
2. **Validación:**
   - Pruebas sintéticas con Playwright Chromium para medir latencia y FPS reales.
   - Pruebas de compatibilidad en Safari iOS para verificar el fallback a HLS.
