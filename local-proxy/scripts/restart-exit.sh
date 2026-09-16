#!/usr/bin/env bash
# Reinicia el exit de forma segura.
# Mata solo el proceso node del exit (dist/exit.js) y lo relanza con el daemon.
# Nota: el patron no aparece en la linea de comandos de este script, asi que pkill
# no se auto-mata (a diferencia de pasar el patron directamente por ssh).
set -u

DIR="$(cd "$(dirname "$0")/.." && pwd)"

pkill -f 'dist/exit\.js' 2>/dev/null || true
sleep 1
rm -f "$DIR/exit.state"
"$DIR/scripts/exit-daemon.sh"
sleep 2
