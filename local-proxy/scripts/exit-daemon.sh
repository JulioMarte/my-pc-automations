#!/usr/bin/env bash
# Mantiene el exit corriendo en Linux sin systemd/sudo.
# Uso: cron @reboot + keepalive cada 2 minutos.
set -u

DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$DIR/exit.log"
LOCK="$DIR/exit.lock"
STATE="$DIR/exit.state"

# rotacion de log
if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt 5242880 ]; then
  mv -f "$LOG" "$LOG.1"
fi

read_env() {
  _key="$1"
  _def="$2"
  _val=""
  if [ -f "$DIR/.env" ]; then
    _val="$(grep -E "^[[:space:]]*${_key}[[:space:]]*=" "$DIR/.env" | tail -n 1 | cut -d= -f2- | tr -d '\r')"
    _val="$(printf '%s' "$_val" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  fi
  if [ -z "$_val" ]; then _val="$_def"; fi
  printf '%s' "$_val"
}

PORT="${EXIT_PORT:-$(read_env EXIT_PORT 8899)}"
HOST="${EXIT_HOST:-$(read_env EXIT_HOST 127.0.0.1)}"

# Sonda de salud real: HTTP con curl, o TCP si no hay curl.
probe() {
  _url="http://${HOST}:${PORT}/__health"
  if command -v curl >/dev/null 2>&1; then
    curl -fsS -m 5 "$_url" >/dev/null 2>&1
    return $?
  fi
  if command -v nc >/dev/null 2>&1; then
    nc -z -w 5 "$HOST" "$PORT" >/dev/null 2>&1
    return $?
  fi
  (exec 3<>"/dev/tcp/${HOST}/${PORT}") >/dev/null 2>&1
  return $?
}

# candado: evita carreras entre @reboot y el keepalive
exec 9>"$LOCK"
if ! flock -n 9; then
  exit 0
fi

# sano: no tocamos nada y reseteamos el backoff
if probe; then
  echo 0 > "$STATE" 2>/dev/null || true
  exit 0
fi

# la build debe existir antes de arrancar
if [ ! -f "$DIR/dist/exit.js" ]; then
  echo "$(date -Is) falta dist/exit.js; corre 'npm run build'" >> "$LOG"
  exit 1
fi

NODE="${NODE_BIN:-}"
if [ -z "$NODE" ]; then
  if command -v node >/dev/null 2>&1; then
    NODE="$(command -v node)"
  else
    NODE="$(ls "$HOME"/.local/node*/bin/node 2>/dev/null | head -n 1)"
  fi
fi

if [ -z "$NODE" ] || [ ! -x "$NODE" ]; then
  echo "$(date -Is) no encontre node; instala Node 20+ o define NODE_BIN" >> "$LOG"
  exit 1
fi

# backoff: fallos consecutivos persistidos en STATE
FAILS=0
if [ -f "$STATE" ]; then
  FAILS="$(tr -dc '0-9' < "$STATE" 2>/dev/null)"
  [ -n "$FAILS" ] || FAILS=0
fi

if [ "$FAILS" -gt 0 ]; then
  EXP="$FAILS"
  [ "$EXP" -gt 6 ] && EXP=6
  DELAY=$((2 * (1 << (EXP - 1))))
  [ "$DELAY" -gt 60 ] && DELAY=60
  if [ "$DELAY" -gt 0 ]; then
    echo "$(date -Is) sonda fallo; espero ${DELAY}s antes de relanzar (fallos=$FAILS)" >> "$LOG"
    sleep "$DELAY"
  fi
fi

cd "$DIR" || exit 1
nohup "$NODE" dist/exit.js >> "$LOG" 2>&1 &
echo "$(date -Is) exit iniciado pid=$! node=$NODE" >> "$LOG"
echo "$((FAILS + 1))" > "$STATE" 2>/dev/null || true
