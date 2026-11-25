#!/usr/bin/env bash
#
# Prueba end-to-end real de local-proxy en Docker.
#
# Levanta, en una red bridge propia:
#   origin  -> servidor HTTP minimo (node:24-alpine)
#   exit    -> local-proxy con ROLE=exit
#   gateway -> local-proxy con ROLE=gateway
# y comprueba, desde un contenedor cliente, que el trafico HTTP y SOCKS5
# atraviesa gateway -> exit -> origin, ademas de la autenticacion (407).
#
# Uso (desde local-proxy/):
#   bash scripts/e2e-docker.sh
#
# Variables:
#   E2E_IMAGE        imagen a construir/usar (def. local-proxy:e2e)
#   E2E_SKIP_BUILD   1 = no construir la imagen (reusa E2E_IMAGE)
#   E2E_CLIENT_IMAGE imagen del cliente curl (def. curlimages/curl:latest)
#
# NOTA: EXIT_BLOCK_PRIVATE=false se usa SOLO en esta prueba. Nunca en produccion.
set -euo pipefail

# Git Bash (MSYS) reescribe rutas dentro de argumentos como -v y -e, rompiendo
# los binds y EXITS_FILE. En Linux (CI) esta variable no existe y no afecta.
export MSYS_NO_PATHCONV=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

IMAGE="${E2E_IMAGE:-local-proxy:e2e}"
CLIENT_IMAGE="${E2E_CLIENT_IMAGE:-curlimages/curl:latest}"
PREFIX="local-proxy-e2e-$$"
NET="${PREFIX}-net"
VOL="${PREFIX}-exits"
ORIGIN="${PREFIX}-origin"
EXIT="${PREFIX}-exit"
GATEWAY="${PREFIX}-gateway"
CLIENT="${PREFIX}-client"
ORIGIN_BODY="origin-e2e-ok"

TMP_DIR="$(mktemp -d)"
BUILT_IMAGE=0
PASS=0
FAIL=0
FAILURES=()

log() { printf '%s\n' "$*"; }
pass() { PASS=$((PASS + 1)); log "PASS: $*"; }
fail() { FAIL=$((FAIL + 1)); FAILURES+=("$*"); log "FAIL: $*"; }

cleanup() {
  local status=$?
  log "--- limpieza ---"
  docker rm -f "$CLIENT" "$GATEWAY" "$EXIT" "$ORIGIN" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  docker volume rm "$VOL" >/dev/null 2>&1 || true
  if [ "$BUILT_IMAGE" = "1" ]; then
    docker image rm -f "$IMAGE" >/dev/null 2>&1 || true
  fi
  rm -rf "$TMP_DIR" >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT INT TERM

# Ejecuta curl en un contenedor efimero dentro de la red de la prueba.
curl_net() {
  docker run --rm --name "$CLIENT" --network "$NET" "$CLIENT_IMAGE" "$@"
}

# Espera a que el HEALTHCHECK de la imagen marque el contenedor como sano.
wait_healthy() {
  local name="$1" attempts="${2:-90}" i=0 status="missing"
  while [ "$i" -lt "$attempts" ]; do
    status="$(docker inspect --format '{{.State.Health.Status}}' "$name" 2>/dev/null || echo missing)"
    case "$status" in
      healthy) return 0 ;;
      unhealthy) log "contenedor $name unhealthy"; return 1 ;;
    esac
    i=$((i + 1))
    sleep 1
  done
  log "timeout esperando salud de $name (ultimo estado: $status)"
  return 1
}

expect_code() {
  local label="$1" expected="$2" actual="$3"
  if [ "$actual" = "$expected" ]; then
    pass "$label -> $expected"
  else
    fail "$label -> $actual (esperado $expected)"
  fi
}

expect_body() {
  local label="$1" expected="$2" actual="$3"
  if [ "$actual" = "$expected" ]; then
    pass "$label"
  else
    fail "$label (esperado '$expected', recibido '$actual')"
  fi
}

log "=== local-proxy e2e (imagen: $IMAGE) ==="

if [ "${E2E_SKIP_BUILD:-0}" != "1" ]; then
  log "construyendo imagen..."
  (cd "$PROJECT_DIR" && docker build -t "$IMAGE" .)
  BUILT_IMAGE=1
else
  log "E2E_SKIP_BUILD=1: reusando la imagen $IMAGE"
fi

log "creando red $NET"
docker network create "$NET" >/dev/null

# El exits.json se monta en el gateway como volumen con nombre (ro). Se usa un
# volumen en vez de un bind del host para que el script funcione igual en Linux
# y en Docker Desktop sobre Windows (Git Bash manglea las rutas de bind).
log "creando volumen $VOL"
docker volume create "$VOL" >/dev/null

log "arrancando origin"
docker run -d --name "$ORIGIN" --network "$NET" \
  -e "ORIGIN_BODY=$ORIGIN_BODY" \
  node:24-alpine node -e '
const http = require("http");
const body = process.env.ORIGIN_BODY;
http.createServer((req, res) => {
  res.writeHead(200, { "content-type": "text/plain" });
  res.end(body);
}).listen(80, "0.0.0.0");
' >/dev/null

log "arrancando exit"
docker run -d --name "$EXIT" --network "$NET" \
  -e ROLE=exit \
  -e EXIT_NAME=e2e-exit \
  -e EXIT_HOST=0.0.0.0 \
  -e EXIT_PORT=8899 \
  -e EXIT_BLOCK_PRIVATE=false \
  -e EXIT_USERS=e2e-exit:e2e-secret \
  -e LOG_LEVEL=warn \
  "$IMAGE" >/dev/null

log "escribiendo exits.json temporal"
cat > "$TMP_DIR/exits.json" <<JSON
[
  { "name": "e2e-exit", "location": "e2e", "host": "$EXIT", "port": 8899, "user": "e2e-exit", "pass": "e2e-secret" }
]
JSON
docker run --rm -i -v "$VOL:/data" node:24-alpine sh -c 'cat > /data/exits.json' \
  < "$TMP_DIR/exits.json"

log "arrancando gateway"
docker run -d --name "$GATEWAY" --network "$NET" \
  -e ROLE=gateway \
  -e GATEWAY_HOST=0.0.0.0 \
  -e PROXY_USERS=agent:secret \
  -e STATS_TOKEN=tok \
  -e METRICS_TOKEN= \
  -e EXITS_FILE=/app/exits/exits.json \
  -e "HEALTH_TARGETS=$ORIGIN:80" \
  -e HEALTH_INTERVAL_MS=3600000 \
  -e LOG_LEVEL=warn \
  -v "$VOL:/app/exits:ro" \
  "$IMAGE" >/dev/null

log "esperando a que exit y gateway esten sanos..."
if wait_healthy "$EXIT" 60; then pass "exit healthy"; else fail "exit healthy"; fi
if wait_healthy "$GATEWAY" 90; then pass "gateway healthy"; else fail "gateway healthy"; fi

log "--- comprobaciones ---"
expect_code "GET /healthz" 200 \
  "$(curl_net -s -o /dev/null -w '%{http_code}' "http://$GATEWAY:8888/healthz")"
expect_code "GET /panel" 200 \
  "$(curl_net -s -o /dev/null -w '%{http_code}' "http://$GATEWAY:8888/panel")"
expect_code "GET /readyz" 200 \
  "$(curl_net -s -o /dev/null -w '%{http_code}' "http://$GATEWAY:8888/readyz")"

expect_body "HTTP proxied devuelve el body del origin" "$ORIGIN_BODY" \
  "$(curl_net -s -x "http://agent:secret@$GATEWAY:8888" "http://$ORIGIN/")"

expect_body "SOCKS5 proxied devuelve el body del origin" "$ORIGIN_BODY" \
  "$(curl_net -s --proxy "socks5h://agent:secret@$GATEWAY:1080" "http://$ORIGIN/")"

expect_code "HTTP proxied con password incorrecta" 407 \
  "$(curl_net -s -o /dev/null -w '%{http_code}' -x "http://agent:wrong@$GATEWAY:8888" "http://$ORIGIN/")"

log "----------------------------------------"
log "Resultado: $PASS PASS / $FAIL FAIL"
if [ "$FAIL" -ne 0 ]; then
  for item in "${FAILURES[@]}"; do log "  - $item"; done
  exit 1
fi
log "E2E OK"
exit 0
