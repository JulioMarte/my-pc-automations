#!/usr/bin/env bash
# Instala los servicios systemd de local-proxy (gateway y/o exit).
# Alternativa OPCIONAL a Task Scheduler (Windows) y al cron (Linux); ver docs/service.md.
#
# Uso (como root):
#   sudo ./install.sh            # gateway + exit
#   sudo ./install.sh all
#   sudo ./install.sh gateway
#   sudo ./install.sh exit
#
# Escribe en /etc/systemd/system (puedes cambiarlo con UNIT_DIR=...).
# Para una instalacion SIN root usa "systemctl --user" (ver docs/service.md):
# este script no la hace, solo la documenta.
#
# Es idempotente: reescribe las units y re-ejecuta daemon-reload + enable --now.
# Si la unit ya estaba activa, un cambio de contenido se aplica con:
#   sudo systemctl restart local-proxy-<rol>.service
set -eu

UNIT_DIR="${UNIT_DIR:-/etc/systemd/system}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

ROLE="${1:-all}"

log() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

if [ "$(id -u)" -ne 0 ]; then
  die "se requiere root. Ejecuta: sudo $0 $ROLE"
fi

command -v systemctl >/dev/null 2>&1 || die "systemctl no encontrado (se requiere systemd)"

case "$ROLE" in
  all | gateway | exit) ;;
  *) die "rol invalido '$ROLE' (usa: gateway | exit | all)" ;;
esac

# Lista de roles a procesar.
roles() {
  if [ "$1" = "all" ]; then
    printf '%s\n' gateway exit
  else
    printf '%s\n' "$1"
  fi
}

# Escapa el texto para usarlo como reemplazo literal en sed.
escape_sed() {
  printf '%s' "$1" | sed 's/[&|\\]/\\&/g'
}

PROJECT_SED="$(escape_sed "$PROJECT_DIR")"

log "Proyecto: $PROJECT_DIR"
log "Units en: $UNIT_DIR"

for role in $(roles "$ROLE"); do
  src="$SCRIPT_DIR/local-proxy-${role}.service"
  dst="$UNIT_DIR/local-proxy-${role}.service"
  [ -f "$src" ] || die "no existe la plantilla $src"

  if [ ! -f "$PROJECT_DIR/dist/${role}.js" ]; then
    log "AVISO: falta $PROJECT_DIR/dist/${role}.js; corre 'npm run build' antes de arrancar."
  fi

  # Sustituye el marcador solo en directivas, no en comentarios (asi el
  # encabezado de la plantilla conserva la explicacion del marcador).
  sed "/^[[:space:]]*#/!s|__PROJECT_DIR__|$PROJECT_SED|g" "$src" > "$dst"
  chmod 0644 "$dst"
  log "instalado $dst"
done

log "systemctl daemon-reload"
systemctl daemon-reload

for role in $(roles "$ROLE"); do
  log "systemctl enable --now local-proxy-${role}.service"
  systemctl enable --now "local-proxy-${role}.service"
done

log "OK. Estado actual:"
for role in $(roles "$ROLE"); do
  systemctl --no-pager --full status "local-proxy-${role}.service" || true
done

log ""
log "Logs:    journalctl -u local-proxy-gateway.service -f"
log "Aplicar cambios de la unit a un servicio ya activo:"
log "  sudo systemctl restart local-proxy-<rol>.service"
