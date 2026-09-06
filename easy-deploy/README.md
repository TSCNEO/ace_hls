# AceHLS Easy Deploy

Este paquete instala AceHLS utilizando imágenes ya construidas. No necesita clonar el código, ejecutar `docker build` ni instalar Python. Está pensado para Docker Compose v2 en una red interna, LAN o VPN.

## Obtener el paquete

Desde Git:

```bash
git clone https://github.com/TSCNEO/ace_hls.git
cd ace_hls/easy-deploy
```

O mediante el ZIP sin código fuente:

```bash
curl -LO https://github.com/TSCNEO/ace_hls/releases/download/v2.9.0/ace-hls-easy-deploy-v2.9.0.zip
unzip ace-hls-easy-deploy-v2.9.0.zip
cd ace-hls-easy-deploy-v2.9.0
```

En ambos casos, continúa con una de las variantes siguientes.

## Elegir variante

| Carpeta | Servicios | Uso |
|---|---|---|
| `orchestrator-local` | AceHLS + Orchestrator | Instalación nueva y autónoma en un único host. |
| `orchestrator-remote` | Solo AceHLS | El Orchestrator ya funciona en otra IP o equipo. |

AceXY no forma parte de Easy Deploy porque permanece únicamente como compatibilidad legacy.

## Orchestrator local

```bash
cd orchestrator-local
cp .env.example .env
```

Edita `.env` y sustituye `cambia-este-token-compartido` por un token largo y privado. Después ejecuta:

```bash
docker compose pull
docker compose up -d --remove-orphans
docker compose ps
```

- AceHLS: `http://IP_DEL_HOST:8088`
- Panel del Orchestrator: `http://IP_DEL_HOST:8000/panel`
- Reproducción directa: puerto `8000`

El Orchestrator local monta `/var/run/docker.sock` para crear motores AceStream. No expongas estos servicios directamente a Internet.

## Orchestrator remoto

```bash
cd orchestrator-remote
cp .env.example .env
```

Edita como mínimo:

```dotenv
ORCHESTRATOR_HOST=192.168.1.50
ORCHESTRATOR_PORT=8000
ORCHESTRATOR_API_TOKEN=el-mismo-valor-que-API_KEY-remota
```

Arranca AceHLS:

```bash
docker compose pull
docker compose up -d --remove-orphans
docker compose ps
```

El Compose remoto no crea Orchestrator, no monta Docker socket y no publica el puerto `8000`. Ese puerto debe estar accesible en el host remoto desde AceHLS y desde los reproductores de la LAN/VPN.

## Datos y cambio de variante

Las dos variantes usan por defecto el volumen Docker `ace_hls_data`. Para pasar de una a otra:

```bash
# En la variante activa; no añadir -v
docker compose down

# En la nueva variante
cp .env.example .env
docker compose up -d --remove-orphans
```

Conserva `ACE_HLS_DATA_VOLUME=ace_hls_data` en ambos `.env`. El Orchestrator local guarda su configuración separadamente en `ace_hls_orchestrator_data`.

Si vienes de los Compose antiguos, localiza el volumen existente:

```bash
docker volume ls
```

Pon su nombre en `ACE_HLS_DATA_VOLUME`; por ejemplo, `release_ace_hls_data`. Así Easy Deploy montará los datos existentes sin copiarlos.

## Actualizar

Cada ZIP fija una versión concreta. Descarga el paquete de la versión nueva, copia tu `.env` anterior en la misma variante y revisa si `.env.example` incorpora variables nuevas. Después:

```bash
docker compose pull
docker compose up -d --remove-orphans
```

No borres los volúmenes. Para volver atrás, conserva el ZIP anterior, inicia su Compose con el mismo `.env` y el mismo `ACE_HLS_DATA_VOLUME`.

## Comprobación

```bash
curl --fail http://127.0.0.1:8088/api/version
curl --fail http://127.0.0.1:8088/api/orchestrator/config
curl --fail http://127.0.0.1:8088/health
```

En remoto también puedes comprobar directamente:

```bash
curl --fail http://192.168.1.50:8000/proxy/health
```

Los errores habituales de conectividad, token, IPv6 y endpoint público están explicados en la documentación completa del proyecto.
