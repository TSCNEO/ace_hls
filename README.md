# AceHLS Web Viewer

Una interfaz web moderna y autogestionada para visualizar y reproducir canales de AceStream.

## 🚀 Características Principales

*   **📺 Interfaz Web Moderna**: Grid estilo Netflix con buscador y categorías. Compatible con móviles.
*   **🔄 Multiplexado Real (AceXY)**: Soporte para **múltiples usuarios simultáneos** viendo el mismo o diferentes canales sin cortes.
*   **🍎 Soporte Web/iOS (HLS Remuxer)**: Motor de transcodificación ligero integrado (`ffmpeg` copy). Permite reproducir en **iPhone, iPad y Navegadores Web** sin instalar nada.
*   **🧠 IP Dinámica Inteligente**: La aplicación detecta automáticamente la IP de acceso (Local, LAN o WAN) y genera los enlaces M3U correctos. ¡Adiós a configurar IPs manualmente!
*   **🧟 Monitor de Inactividad**: Sistema "Watchdog" que mata automáticamente los procesos de video si cierras la pestaña o dejas de ver un canal, ahorrando ancho de banda y CPU.
*   **📋 Lista M3U Universal**: Genera una lista compatible con VLC, TiviMate, IPTV Smarters, etc.

---

## 🛠️ Instalación con Docker Compose

Este stack incluye todo lo necesario: 
1. `ace-hls-viewer`: La interfaz web y API.
2. `acexy`: El proxy que gestiona la concurrencia.
3. `acestream`: El motor P2P.

### 2. Arrancar

```bash
docker-compose up -d
```

---

## 📱 Cómo Usar

### En el Navegador (PC / Móvil / iPhone)
Accede a `http://TU_IP:8089`.
- **Click en un canal**: Se abrirá el reproductor integrado. Usará el motor HLS interno para máxima compatibilidad.

### En SmartTV / VLC / TiviMate
Usa la lista M3U generada dinámicamente:
- **URL**: `http://TU_IP:8089/playlist.m3u`
- Esta lista usa enlaces directos HTTP (`http://TU_IP:Puerto_Acexy/ace/getstream...`) para que la carga sea instantánea y eficiente (sin transcodificación).

---

## 🗑️ Limpieza Automática
No te preocupes por dejar streams abiertos. El sistema detecta si dejas de descargar datos durante **60 segundos** y cierra la conexión AceStream automáticamente.