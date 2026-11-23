#!/usr/bin/env bash
# Ayudante del corte vps-01 -> vps-02 (ver docs/corte-vps01-vps02.md). Se ejecuta en
# vps-02 como root. Pasos:
#
#   vps02-cutover.sh dr <snapshot-de-vps-01>
#       Para timers de backup de vps-02, limpia el estado de prueba (contenedores y
#       volumenes que no son del plano de control de Coolify, rutas montadas), cambia
#       TEMPORALMENTE la identidad de backup a la de vps-01 (solo lectura: el DR no
#       escribe en el repositorio) y lanza disaster-recovery --execute en una unidad
#       systemd (vps-dr-cutover). Log: /root/dr-cutover.log
#
#   vps02-cutover.sh finish
#       Vuelve a la identidad propia de vps-02 (vmi3456423), crea el token de API de
#       Coolify (la base de datos restaurada no trae el de vps-02), activa los timers
#       y lanza un backup.
#
#   vps02-cutover.sh go-live
#       Quita el bloqueo de salida de los contenedores y el bloqueo hacia vps-01, y
#       activa la sincronizacion del certificado de Mailu. Solo DESPUES de parar los
#       recursos de vps-01 y antes o junto al cambio de DNS.
set -Eeuo pipefail
umask 077

OWN_ID="vmi3456423"
SRC_ID="vmi2741977"
SRC_HOST="vmi2741977"
VPS01_IPS=(100.112.184.84 147.93.185.222)
VPS01_IP6="fd7a:115c:a1e0::8636:b855"
ETC=/etc/vps-backup
TIMERS=(vps-backup.timer vps-backup-maintenance.timer vps-backup-dr-test.timer)

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '[cutover] %s\n' "$*"; }
[[ $EUID -eq 0 ]] || die "ejecutar como root"

set_identity() {
  local id="$1"
  sed -i -e "s/^BACKUP_ID=.*/BACKUP_ID=$id/" -e "s/^S3_PREFIX=.*/S3_PREFIX=$id/" \
    -e "s/^REPOSITORY_PREFIX=.*/REPOSITORY_PREFIX=$id/" "$ETC/config.conf"
  sed -i "s#^\(RESTIC_REPOSITORY=s3:https://[^/]*/vps-backups/\)vmi[0-9]*\$#\1$id#" "$ETC/credentials"
  grep -q "^BACKUP_ID=$id\$" "$ETC/config.conf" && grep -q "/vps-backups/$id\$" "$ETC/credentials" \
    || die "no pude fijar la identidad $id"
  log "identidad de backup: $id"
}

cmd_dr() {
  local snap="${1:?uso: dr <snapshot-de-vps-01>}"
  [[ "$snap" =~ ^[0-9a-f]{8,64}$ ]] || die "snapshot invalido: $snap"
  systemctl is-active --quiet vps-backup.service && die "hay un backup de vps-02 en curso; espera"
  systemctl disable --now "${TIMERS[@]}" >/dev/null 2>&1 || true
  log "timers de vps-02 parados"
  cp -a "$ETC" "/root/vps-backup-etc.bak-$(date +%Y%m%d-%H%M%S)"
  log "limpiando estado de prueba"
  docker ps -a --format '{{.Names}}' | grep -v '^coolify' | xargs -r docker rm -f >/dev/null
  docker volume ls -q | grep -vx -e coolify-db -e coolify-redis | xargs -r docker volume rm >/dev/null
  rm -rf /data/compose /home/julio-marte/Docker-data /var/lib/vps-backup/disaster-recovery/*
  set_identity "$SRC_ID"
  # El token de vps-02 deja de valer cuando el DR restaura la base de datos de
  # Coolify de vps-01; vacio, el DR crea el suyo (asi se probo).
  sed -i "s/^COOLIFY_API_TOKEN=.*/COOLIFY_API_TOKEN=''/" "$ETC/credentials"
  systemd-run --unit=vps-dr-cutover --setenv=HOME=/root /bin/bash -c \
    "printf 'RECOVER-$SRC_HOST\n' | /usr/local/sbin/vps-backup disaster-recovery --execute --snapshot $snap --replace-existing > /root/dr-cutover.log 2>&1; echo EXIT=\$? >> /root/dr-cutover.log"
  log "DR lanzado (unidad vps-dr-cutover). Sigue el log: tail -f /root/dr-cutover.log"
  log "Al terminar (EXIT=0): vps02-cutover.sh finish"
}

cmd_finish() {
  local tok C T
  systemctl is-active --quiet vps-dr-cutover.service 2>/dev/null && die "el DR sigue en marcha"
  set_identity "$OWN_ID"
  # shellcheck disable=SC1091
  source /usr/local/sbin/vps-backup
  load_config
  tok=$(coolify_provision_api_token 2>/dev/null) || die "no pude crear el token de API de Coolify"
  [[ -n "$tok" ]] || die "token de Coolify vacio"
  C="$ETC/credentials"; T=$(mktemp "$C.tmp.XXXXXX"); chmod 600 "$T"
  grep -v '^COOLIFY_API_TOKEN=' "$C" > "$T"
  printf 'COOLIFY_API_TOKEN=%q\n' "$tok" >> "$T"
  unset tok
  mv -f "$T" "$C"; chmod 600 "$C"
  load_config
  configure_coolify_cli_context || die "el contexto de la CLI de Coolify no valida"
  log "token de Coolify creado y contexto CLI valido"
  systemctl enable --now "${TIMERS[@]}" >/dev/null
  systemctl reset-failed vps-backup.service 2>/dev/null || true
  systemctl start --no-block vps-backup.service
  log "timers activos y backup lanzado: journalctl -fu vps-backup.service"
}

cmd_go_live() {
  local ip
  systemctl disable --now dr-egress-block.timer >/dev/null 2>&1 || true
  [[ -x /usr/local/sbin/dr-egress-block ]] && /usr/local/sbin/dr-egress-block --remove
  for ip in "${VPS01_IPS[@]}"; do
    while iptables -D OUTPUT -d "$ip" -j REJECT 2>/dev/null; do :; done
    while iptables -D DOCKER-USER -d "$ip" -j REJECT 2>/dev/null; do :; done
  done
  while ip6tables -D OUTPUT -d "$VPS01_IP6" -j REJECT 2>/dev/null; do :; done
  log "bloqueos de salida y hacia vps-01 retirados"
  if [[ -f /etc/cron.d/mailu-cert-sync.cutover ]]; then
    mv -f /etc/cron.d/mailu-cert-sync.cutover /etc/cron.d/mailu-cert-sync
    log "sincronizacion del certificado de Mailu activada (cuando Traefik tenga el certificado)"
  fi
}

case "${1:-}" in
  dr) shift; cmd_dr "$@" ;;
  finish) cmd_finish ;;
  go-live) cmd_go_live ;;
  *) sed -n '2,26p' "$0"; exit 2 ;;
esac
