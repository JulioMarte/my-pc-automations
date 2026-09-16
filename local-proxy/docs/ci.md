# Integracion continua (CI)

Workflow: `.github/workflows/ci.yml` (en la raiz del monorepo). El proyecto vive
en `local-proxy/`, por eso todos los pasos usan
`defaults.run.working-directory: local-proxy`.

## Disparadores

- `push` a `dev` y `main`.
- `pull_request` hacia `dev` y `main`.

`concurrency` cancela las ejecuciones superadas de la misma rama/PR
(`cancel-in-progress: true`) para no gastar minutos en commits viejos.

## Que ejecuta

### Job `test` (ubuntu-latest)

1. `actions/checkout@v4`.
2. `actions/setup-node@v4` con Node 24 y cache de npm
   (`cache-dependency-path: local-proxy/package-lock.json`).
3. `npm ci`.
4. `npm run typecheck` (`tsc -p tsconfig.json`, sin emitir).
5. `npm test` (`node --test` sobre `test/*.test.ts`).
6. `npm run build` (`tsc -p tsconfig.build.json` -> `dist/`).

### Job `docker` (ubuntu-latest, `needs: test`)

1. `docker build -t local-proxy:ci .` (contexto `local-proxy/`).
2. Smoke test real: arranca un gateway con `GATEWAY_HOST=0.0.0.0`, un
   `exits.json` minimo (`[]`) montado de solo lectura y el puerto `18888:8888`;
   espera a que el `HEALTHCHECK` de la imagen marque `healthy`; comprueba que
   `GET /healthz` y `GET /panel` devuelven 200.
3. `bash scripts/e2e-docker.sh` con `E2E_IMAGE=local-proxy:ci` y
   `E2E_SKIP_BUILD=1` (reusa la imagen ya construida).
4. Limpieza (`if: always()`): borra el contenedor `lp-smoke` y la imagen
   `local-proxy:ci`.

Solo se usan acciones oficiales (`actions/checkout`, `actions/setup-node`).

## Reproducir localmente

Requisitos: Node 24, npm y Docker con contenedores Linux.

```sh
cd local-proxy
npm ci
npm run typecheck
npm test
npm run build
```

## Prueba end-to-end en Docker

`scripts/e2e-docker.sh` levanta en una red bridge propia:

- `origin`: servidor HTTP minimo (`node:24-alpine`) que devuelve un body conocido.
- `exit`: local-proxy con `ROLE=exit`.
- `gateway`: local-proxy con `ROLE=gateway`, con un `exits.json` temporal que
  apunta al contenedor del exit.

Despues, desde un contenedor cliente (`curlimages/curl`) en la misma red,
comprueba:

- `GET /healthz`, `GET /panel` y `GET /readyz` del gateway devuelven 200.
- Una peticion HTTP proxied (`curl -x http://agent:secret@gateway:8888 http://origin/`)
  devuelve el body del origin.
- Una peticion SOCKS5 proxied
  (`curl --proxy socks5h://agent:secret@gateway:1080 http://origin/`) devuelve el
  body del origin.
- Una password incorrecta devuelve 407.

Imprime lineas `PASS`/`FAIL`, sale con codigo distinto de cero si algo falla y
limpia contenedores, red, imagen (si la construyo el script) y el directorio
temporal al salir.

### Ejecutar a mano

```sh
cd local-proxy
bash scripts/e2e-docker.sh
```

Variables:

| Variable | Por defecto | Descripcion |
| --- | --- | --- |
| `E2E_IMAGE` | `local-proxy:e2e` | Imagen a construir/usar. |
| `E2E_SKIP_BUILD` | `0` | `1` para reusar `E2E_IMAGE` sin reconstruir. |
| `E2E_CLIENT_IMAGE` | `curlimages/curl:latest` | Imagen del cliente curl. |

Ejemplo reusando una imagen ya construida:

```sh
docker build -t local-proxy:ci .
E2E_IMAGE=local-proxy:ci E2E_SKIP_BUILD=1 bash scripts/e2e-docker.sh
```

### Alternativa con Compose

`docker-compose.e2e.yml` es una pila autocontenida para reproducir la prueba a
mano (no la usa el script). Publica el gateway en `127.0.0.1:18888` y usa
`scripts/e2e/exits.e2e.json` para apuntar al servicio `exit`.

```sh
cd local-proxy
docker build -t local-proxy:e2e .
docker compose -f docker-compose.e2e.yml up -d --wait
curl -x http://agent:secret@127.0.0.1:18888 http://origin/
docker compose -f docker-compose.e2e.yml down -v
```

## Notas de plataforma

- La prueba e2e necesita contenedores Linux y una red bridge con DNS por nombre
  de contenedor. Funciona en CI (ubuntu-latest) y en Docker Desktop con
  contenedores Linux.
- `EXIT_BLOCK_PRIVATE=false` solo se usa en esta prueba, para que el exit alcance
  el `origin` de la red bridge. En produccion el exit bloquea rangos privados.
- El smoke de CI no usa `network_mode: host` (no hay Tailscale en el runner): usa
  bridge con mapeo de puertos.
- El script monta `exits.json` con un volumen con nombre (no un bind del host) y
  exporta `MSYS_NO_PATHCONV=1`, para comportarse igual en Linux y en Git Bash de
  Windows.
