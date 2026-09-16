# local-proxy en Docker

Imagen unica para los dos roles (`gateway` y `exit`). Sin dependencias de
runtime: solo `dist/` + `package.json` sobre `node:24-alpine`.

## Construir

```sh
cd local-proxy
docker build -t local-proxy:latest .
```

## Ejecutar el gateway

Con red de host (necesario para la IP de Tailscale `100.x`):

```sh
docker run -d --name local-proxy-gateway \
  --network host \
  --env-file .env \
  -v "$PWD/exits.json:/app/exits.json:ro" \
  -v "$PWD/stats.jsonl:/app/stats.jsonl" \
  -v "$PWD/logs:/app/logs" \
  local-proxy:latest
```

El rol por defecto es `gateway`. Para forzarlo: `-e ROLE=gateway`.

## Ejecutar el exit

```sh
docker run -d --name local-proxy-exit \
  --network host \
  --env-file .env \
  -e ROLE=exit \
  -v "$PWD/logs:/app/logs" \
  local-proxy:latest
```

## Docker Compose

```sh
docker compose --profile gateway up -d
docker compose --profile exit up -d
docker compose --profile gateway --profile exit up -d
```

- `init: true` y `restart: unless-stopped` para ambos servicios.
- `network_mode: host`: los contenedores no mapean puertos; usan los del host.
- `env_file: .env`: las credenciales entran como variables de entorno, no se
  hornean en la imagen.

## Variables de entorno

Se leen de `.env` (via `env_file`/`--env-file`) o del entorno del contenedor.
Las relevantes para Docker:

| Variable | Rol | Por defecto | Descripcion |
| --- | --- | --- | --- |
| `ROLE` | ambos | `gateway` | `gateway` o `exit`. |
| `GATEWAY_HOST` | gateway | `127.0.0.1` | Bind del gateway (IP `100.x` de Tailscale). |
| `GATEWAY_HTTP_PORT` | gateway | `8888` | Puerto HTTP. |
| `GATEWAY_SOCKS_PORT` | gateway | `1080` | Puerto SOCKS5. |
| `PROXY_USERS` | gateway | vacio | `usuario:clave,usuario2:clave2`. |
| `STATS_TOKEN` | gateway | vacio | Requerido por `/__stats`. |
| `EXIT_HOST` | exit | `127.0.0.1` | Bind del exit (IP `100.x` de Tailscale). |
| `EXIT_PORT` | exit | `8899` | Puerto HTTP del exit. |
| `EXIT_USERS` | exit | vacio | Credenciales de salida (rotables). |

## Volumenes

- `./exits.json:/app/exits.json:ro` (gateway): lista de exits.
- `./stats.jsonl:/app/stats.jsonl` (gateway): estadisticas por peticion.
- `./logs:/app/logs`: logs del host. El proceso escribe a stdout/stderr, que
  Docker captura; el volumen es para paridad con el despliegue nativo.

Los ficheros `stats.jsonl` y `logs/` deben existir en el host antes de montar
el bind. En Linux, el usuario `node` (uid 1000) necesita permiso de escritura.

## Salud

El `HEALTHCHECK` de la imagen usa `scripts/docker-healthcheck.sh`:

- gateway -> `GET /healthz`
- exit -> `GET /__health`

Estado: `docker inspect --format '{{.State.Health.Status}}' <contenedor>`.

## Comprobar a mano

```sh
curl http://HOST:8888/healthz      # liveness del gateway -> {"ok":true,...}
curl http://HOST:8888/readyz       # readiness -> 200 si hay exits sanos, 503 si no
curl http://HOST:8888/panel        # panel HTML de estado
curl http://HOST:8899/__health     # liveness del exit -> {"ok":true,...}
```

Con `network_mode: host`, `HOST` es la IP `100.x` de Tailscale (o
`127.0.0.1` si se probo con `GATEWAY_HOST=0.0.0.0`).

## Tamano de la imagen

Ver `docker images local-proxy:latest`. Al no incluir `node_modules` (cero
dependencias de runtime) ni el toolchain de build, la imagen final queda en
torno a los ~60 MB (base `node:24-alpine`).

## Seguridad

- **No publicar puertos a Internet.** El proxy vive en la tailnet; exponerlo en
  una interfaz publica permite uso abierto del proxy.
- **Solo Tailscale.** Bind a la IP `100.x` (`GATEWAY_HOST`/`EXIT_HOST`). Si se
  usa `0.0.0.0`, el gateway lo advierte en los logs.
- **No hornear secretos.** `.env` y `exits.json` no se copian a la imagen
  (`.dockerignore` los excluye); se montan o se pasan por `env_file`.
- **Usuario sin privilegios.** El contenedor corre como `node` (uid 1000), no
  como root. `tini` es PID 1 y propaga senales para un apagado ordenado.

## Caveat de `network_mode: host` en Docker Desktop

En Docker Desktop (Windows/macOS) el modo host no equivale al de Linux nativo.
Segun la version puede requerir habilitar "host networking" en
Settings > Resources; si no esta disponible, el contenedor no vera la interfaz
`tailscale0` y no alcanzara las IPs `100.x`. Para pruebas se puede usar bridge
con `-p 8888:8888 -p 1080:1080` y `GATEWAY_HOST=0.0.0.0`, pero Tailscale
seguiria fuera del contenedor. En produccion, usar un host Linux.
