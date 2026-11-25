#!/bin/sh
# Healthcheck del contenedor local-proxy.
# Elige el endpoint segun ROLE y lo sondea con fetch de node (global en Node 18+).
# Sale 0 si la respuesta es 2xx; 1 en cualquier otro caso.
set -eu

ROLE="${ROLE:-gateway}"

if [ "$ROLE" = "exit" ]; then
  HOST="${EXIT_HOST:-127.0.0.1}"
  PORT="${EXIT_PORT:-8899}"
  PATHNAME="/__health"
else
  HOST="${GATEWAY_HOST:-127.0.0.1}"
  PORT="${GATEWAY_HTTP_PORT:-8888}"
  PATHNAME="/healthz"
fi

# Un bind comodin (0.0.0.0/::) no es una direccion de destino valida: usar loopback.
case "$HOST" in
  "" | 0.0.0.0 | :: | "[::]") HOST="127.0.0.1" ;;
esac

URL="http://${HOST}:${PORT}${PATHNAME}"

exec node -e '
const url = process.argv[1];
const controller = new AbortController();
const timer = setTimeout(() => controller.abort(), 4000);
fetch(url, { signal: controller.signal })
  .then((res) => {
    clearTimeout(timer);
    process.exit(res.ok ? 0 : 1);
  })
  .catch(() => {
    clearTimeout(timer);
    process.exit(1);
  });
' "$URL"
