#!/bin/sh
# Punto de entrada comun del contenedor local-proxy.
# La variable ROLE decide que proceso arranca:
#   gateway (por defecto) -> dist/gateway.js
#   exit                  -> dist/exit.js
set -eu

ROLE="${ROLE:-gateway}"

case "$ROLE" in
  gateway | exit) ;;
  *)
    echo "local-proxy: ROLE invalido: '$ROLE' (esperado 'gateway' o 'exit')" >&2
    exit 64
    ;;
esac

# Ruta absoluta derivada de la ubicacion del script (robusto ante WORKDIR).
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "local-proxy: arrancando rol '${ROLE}' (${APP_DIR}/dist/${ROLE}.js)" >&2

exec node "${APP_DIR}/dist/${ROLE}.js"
