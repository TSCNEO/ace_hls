# Despliegue con AceStream Orchestrator

AceHLS puede usar AceStream Orchestrator de dos maneras: dentro del mismo Compose o instalado en otro equipo de la LAN/VPN. En ambos casos, el Orchestrator entrega los streams por el puerto `8000` y AceHLS usa su API de gestión para mostrar estado, motores y métricas.

> Este despliegue está pensado para una red privada, LAN o VPN. AceHLS no incorpora autenticación y el endpoint de reproducción del Orchestrator es público. No expongas los puertos `8088` ni `8000` directamente a Internet.

## Requisitos

- Docker Engine con Docker Compose v2.
- Un host AMD64/Intel o ARM64 para AceHLS.
- Puertos TCP `8088` y `8000` libres en modo local.
- En modo remoto, conectividad desde el contenedor AceHLS hacia `ORCHESTRATOR_HOST:ORCHESTRATOR_PORT`.
- El mismo token configurado como `ORCHESTRATOR_API_TOKEN` en AceHLS y `API_KEY` en el Orchestrator.

Los datos de AceHLS viven en el volumen `ace_hls_data`. Actualizar o cambiar de backend no requiere borrarlo.

## Opción 1: Orchestrator local

Es el modo recomendado para una instalación nueva. El Compose crea AceHLS, Orchestrator, la red `ace_hls_stream`, el volumen `orchestrator_data` y monta el Docker socket para que el Orchestrator pueda crear motores.

```bash
cp .env.example .env
```

Edita `.env` y cambia al menos `ORCHESTRATOR_API_TOKEN`. Después levanta el entorno:

```bash
docker compose --env-file .env up -d --build --remove-orphans
docker compose ps
```

Servicios disponibles:

- WebUI: `http://IP_DEL_HOST:8088`
- Panel: `http://IP_DEL_HOST:8000/panel`
- Reproducción: `http://IP_DEL_HOST:8000/ace/getstream?id=...`

Para usar la imagen publicada en lugar de construir el repositorio:

```bash
ACE_HLS_IMAGE=tscneo/ace-hls-viewer:2.6.0-dev \
docker compose -f release/docker-compose.yml --env-file .env up -d --remove-orphans
```

## Opción 2: Orchestrator externo

El Orchestrator debe estar instalado y funcionando en el otro equipo. Su configuración, motores, Docker socket y VPN se administran allí; el Compose remoto de AceHLS no intenta gestionarlos localmente.

```bash
cp .env.orchestrator-remote.example .env
```

Edita estas variables:

```dotenv
ORCHESTRATOR_MODE=remote
ORCHESTRATOR_HOST=192.168.1.50
ORCHESTRATOR_PORT=8000
ORCHESTRATOR_API_TOKEN=el-mismo-valor-que-API_KEY-remota
```

`ORCHESTRATOR_HOST` admite una IPv4, un hostname resoluble desde Docker o una IPv6 sin corchetes. El Compose falla antes de arrancar si la variable está vacía.

Desarrollo/construcción local:

```bash
docker compose -f docker-compose.orchestrator-remote.yml --env-file .env \
  up -d --build --remove-orphans
```

Imagen publicada:

```bash
ACE_HLS_IMAGE=tscneo/ace-hls-viewer:2.6.0-dev \
docker compose -f release/docker-compose.orchestrator-remote.yml --env-file .env \
  up -d --remove-orphans
```

Este Compose solo ejecuta AceHLS: no publica el puerto `8000`, no monta `/var/run/docker.sock` y no crea `orchestrator_data`.

## Direcciones internas y públicas

La configuración normal necesita únicamente `ORCHESTRATOR_HOST` y `ORCHESTRATOR_PORT`:

- AceHLS y FFmpeg conectan a ese host y puerto.
- La API de gestión usa `http://ORCHESTRATOR_HOST:ORCHESTRATOR_PORT/api/v1`.
- La playlist `direct` apunta al mismo host y puerto.

Los overrides se aplican en este orden:

1. `STREAM_PROXY_HOST` y `STREAM_PROXY_PORT` cambian el destino interno de reproducción.
2. `ORCHESTRATOR_URL` cambia exclusivamente la base de la API de gestión.
3. `STREAM_PUBLIC_ENDPOINT` tiene prioridad absoluta para los enlaces entregados a clientes IPTV.

Ejemplo con nombre DNS y HTTPS público:

```dotenv
ORCHESTRATOR_HOST=192.168.1.50
ORCHESTRATOR_PORT=8000
STREAM_PUBLIC_ENDPOINT=https://tv.example.lan
```

Ejemplo IPv6:

```dotenv
ORCHESTRATOR_HOST=fd00::50
ORCHESTRATOR_PORT=8000
```

AceHLS añadirá automáticamente los corchetes al formar `http://[fd00::50]:8000`.

## Verificación

Comprueba primero el Orchestrator desde el host de AceHLS:

```bash
curl --fail http://192.168.1.50:8000/proxy/health
curl --fail \
  -H "Authorization: Bearer EL_TOKEN_COMPARTIDO" \
  http://192.168.1.50:8000/api/v1/engines
```

Después comprueba AceHLS:

```bash
curl --fail http://127.0.0.1:8088/api/version
curl --fail http://127.0.0.1:8088/api/orchestrator/config
curl --fail http://127.0.0.1:8088/health
curl --fail "http://127.0.0.1:8088/playlist.m3u?profile=direct"
```

En `/api/orchestrator/config` deben aparecer `deployment: "remote"`, el host configurado, `authenticated: true` y el endpoint público esperado. El token nunca aparece en la respuesta. Abre también `http://192.168.1.50:8000/panel` y revisa en Ajustes de AceHLS que el estado figure como conectado.

## Actualizar, detener y cambiar de modo

Actualización local:

```bash
docker compose --env-file .env pull
docker compose --env-file .env up -d --force-recreate --remove-orphans
```

Actualización remota:

```bash
docker compose -f release/docker-compose.orchestrator-remote.yml --env-file .env pull
docker compose -f release/docker-compose.orchestrator-remote.yml --env-file .env \
  up -d --force-recreate --remove-orphans
```

Detén el Compose utilizado, sin `-v`, para conservar los datos:

```bash
docker compose -f release/docker-compose.orchestrator-remote.yml --env-file .env down
```

Para pasar de local a remoto, crea el `.env` remoto y ejecuta el Compose remoto con `--remove-orphans`. Para volver al Orchestrator local, restaura `.env.example` como base y usa el Compose normal. Para AceXY legacy, usa `release/docker-compose.acexy.yml`. No ejecutes `docker compose down -v`, porque eliminaría los volúmenes del proyecto.

## Solución de problemas

### `ORCHESTRATOR_HOST` no está definido

Se está usando el Compose remoto sin su `.env`. Copia `.env.orchestrator-remote.example`, configura la IP y ejecuta siempre con `--env-file .env`.

### AceHLS muestra `connection_error` o `/health` está degradado

Comprueba ruta, DNS y firewall desde un contenedor en la misma red Docker:

```bash
docker run --rm curlimages/curl:8.10.1 \
  http://192.168.1.50:8000/proxy/health
```

El host remoto debe aceptar TCP `8000` desde el host Docker de AceHLS. Si se usa un hostname, Docker también debe poder resolverlo.

### La salud funciona, pero la API devuelve 401/403

`ORCHESTRATOR_API_TOKEN` no coincide con `API_KEY` en el Orchestrator. Corrige el token y recrea AceHLS. La reproducción puede seguir funcionando porque `/ace/getstream` no usa el token de gestión.

### La playlist apunta a una dirección inaccesible

Por defecto, el modo remoto publica la misma IP y puerto configurados. Si los reproductores acceden mediante DNS, HTTPS, NAT o un puerto distinto, configura `STREAM_PUBLIC_ENDPOINT` con la URL completa visible para esos clientes.

### El panel abre, pero no hay motores

En modo remoto, los motores pertenecen al Orchestrator externo. Revisa allí el Docker socket, su red y sus logs; el Compose remoto de AceHLS no crea motores ni modifica esa instalación.

### IPv6 no conecta

Escribe `ORCHESTRATOR_HOST` sin corchetes y confirma que Docker dispone de ruta IPv6. Los corchetes se añaden solo al construir URLs. Para un endpoint público con IPv6 usa, por ejemplo, `STREAM_PUBLIC_ENDPOINT=http://[fd00::50]:8000`.
