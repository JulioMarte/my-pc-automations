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
#
#   vps02-cutover.sh postgres-sql
#       Recrea postgres-sql-postgres-1 (compose fuera de Coolify, el DR no lo crea)
#       desde el dump del bundle DR mas reciente. 'dr' lo lanza solo al acabar el DR.
#
#   vps02-cutover.sh netdata [snapshot-de-vps-01]
#       Instala el agente de Netdata con la configuracion y el claim de vps-01
#       (sin su identidad de nodo: vps-02 aparece como nodo nuevo en el mismo
#       espacio) y el watchdog de ACLK. Por defecto, el ultimo snapshot de sistema.
set -Eeuo pipefail
umask 077

OWN_ID="vmi3456423"
SRC_ID="vmi2741977"
SRC_HOST="vmi2741977"
VPS01_IPS=(100.112.184.84 147.93.185.222)
VPS01_IP6="fd7a:115c:a1e0::8636:b855"
ETC=/etc/vps-backup
TIMERS=(vps-backup.timer vps-backup-maintenance.timer vps-backup-dr-test.timer)
DR_DIR=/var/lib/vps-backup/disaster-recovery
SELF=$(readlink -f "$0")
# postgres-sql: compose del host fuera de Coolify. La imagen se toma del registro de
# digests del bundle si viene; si no, esta.
PGSQL_NAME=postgres-sql-postgres-1
PGSQL_IMAGE=postgres:16.4
PGSQL_VOLUME=postgres_data
PGSQL_NETWORK=web_network

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
  # postgres-sql se recrea despues del DR aunque este acabe en EXIT=1: las apps de git
  # fallan con la salida bloqueada y eso no afecta al dump.
  systemd-run --unit=vps-dr-cutover --setenv=HOME=/root /bin/bash -c \
    "printf 'RECOVER-$SRC_HOST\n' | /usr/local/sbin/vps-backup disaster-recovery --execute --snapshot $snap --replace-existing > /root/dr-cutover.log 2>&1; echo EXIT=\$? >> /root/dr-cutover.log; $SELF postgres-sql >> /root/dr-cutover.log 2>&1; echo PGSQL_EXIT=\$? >> /root/dr-cutover.log"
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

# Bundle DR mas reciente (lo deja disaster-recovery --execute).
latest_bundle() {
  local b
  b=$(find "$DR_DIR" -maxdepth 1 -type d -name 'system-*' -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
  [[ -n "$b" && -d "$b/var/lib/vps-backup/staging" ]] || return 1
  printf '%s' "$b"
}

cmd_postgres_sql() {
  local B D img ref="" dig="" want got
  B=$(latest_bundle) || die "no hay bundle DR en $DR_DIR"
  D="$B/var/lib/vps-backup/staging/workloads/docker-db/$PGSQL_NAME"
  [[ -s "$D/SHA256SUMS" && -s "$D/globals.sql" ]] || die "el bundle no trae el dump de $PGSQL_NAME"
  (cd "$D" && sha256sum -c --quiet SHA256SUMS) || die "dump de $PGSQL_NAME con sha256 distinto"
  if docker inspect "$PGSQL_NAME" >/dev/null 2>&1; then
    die "$PGSQL_NAME ya existe; para recrearlo: docker rm -f $PGSQL_NAME && docker volume rm $PGSQL_VOLUME"
  fi
  img="$PGSQL_IMAGE"
  read -r ref dig < <(awk -F'\t' -v n="$PGSQL_NAME" '$1 == n { print $2, $3 }' \
    "$B/var/lib/vps-backup/staging/workloads/images/image-digests.tsv" 2>/dev/null) || true
  if [[ -n "$dig" ]] && docker pull -q "$dig" >/dev/null 2>&1 && docker tag "$dig" "$ref"; then
    img="$ref"
    log "imagen fijada al digest del origen: $dig"
  fi
  docker network inspect "$PGSQL_NETWORK" >/dev/null 2>&1 || docker network create "$PGSQL_NETWORK" >/dev/null
  docker volume create "$PGSQL_VOLUME" >/dev/null
  # Contrasena temporal: globals.sql restaura los roles con la del origen.
  docker run -d --name "$PGSQL_NAME" --restart unless-stopped --network "$PGSQL_NETWORK" \
    -v "$PGSQL_VOLUME:/var/lib/postgresql/data" \
    -l com.docker.compose.project=postgres-sql -l com.docker.compose.service=postgres \
    -e POSTGRES_PASSWORD="$(openssl rand -hex 24)" "$img" >/dev/null
  for _ in $(seq 1 60); do
    docker exec "$PGSQL_NAME" pg_isready -U postgres -q 2>/dev/null && break
    sleep 2
  done
  docker exec "$PGSQL_NAME" pg_isready -U postgres -q || die "$PGSQL_NAME no arranca"
  docker exec -i "$PGSQL_NAME" psql -U postgres -X -q -d postgres < "$D/globals.sql" 2>&1 \
    | grep -v 'already exists' >&2 || true
  # shellcheck disable=SC1091
  ( export HOME=/root; source /usr/local/sbin/vps-backup; restore_builtin_postgres_container "$PGSQL_NAME" "$D" ) \
    || die "fallo la restauracion de los dumps de $PGSQL_NAME"
  want=$(grep -c . "$D/database-list.txt" 2>/dev/null || echo 0)
  got=$(docker exec "$PGSQL_NAME" psql -U postgres -XAtc "select count(*) from pg_database where not datistemplate")
  log "$PGSQL_NAME recreado ($img): bases=$got (lista del dump: $want)"
}

cmd_netdata() {
  local snap="${1:-latest}" tmp line i
  command -v restic >/dev/null || die "restic no instalado"
  tmp=$(mktemp -d /root/netdata-src.XXXXXX)
  # El directorio trae el claim de Netdata Cloud: se borra siempre al salir.
  # shellcheck disable=SC2064
  trap "rm -rf '$tmp'" EXIT
  (
    set -a
    # shellcheck disable=SC1091
    . "$ETC/credentials"
    set +a
    export RESTIC_REPOSITORY="${RESTIC_REPOSITORY%/*}/$SRC_ID"
    restic restore "$snap" --host "$SRC_HOST" --tag system --target "$tmp" \
      --include /etc/netdata/netdata.conf --include /etc/netdata/claim.conf \
      --include /usr/share/keyrings/netdata-archive-keyring.gpg \
      --include /etc/apt/sources.list.d --include /usr/local/bin/netdata-aclk-watchdog.sh \
      --include /var/spool/cron/crontabs/root >/dev/null
  ) || die "no pude leer la configuracion de Netdata del repositorio de vps-01"
  [[ -s "$tmp/etc/netdata/claim.conf" ]] || die "el snapshot no trae /etc/netdata/claim.conf"
  if ! dpkg -s netdata >/dev/null 2>&1; then
    [[ -s "$tmp/usr/share/keyrings/netdata-archive-keyring.gpg" ]] || die "el snapshot no trae la clave del repositorio de Netdata"
    install -m 0644 "$tmp/usr/share/keyrings/netdata-archive-keyring.gpg" /usr/share/keyrings/
    for line in "$tmp"/etc/apt/sources.list.d/netdata*; do
      [[ -f "$line" ]] && install -m 0644 "$line" /etc/apt/sources.list.d/
    done
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq netdata >/dev/null
    log "netdata instalado: $(dpkg-query -W -f '${Version}' netdata)"
  fi
  systemctl stop netdata
  install -m 0644 -o root -g netdata "$tmp/etc/netdata/netdata.conf" /etc/netdata/netdata.conf
  install -m 0640 -o root -g netdata "$tmp/etc/netdata/claim.conf" /etc/netdata/claim.conf
  # Estado de claim previo de este host: fuera, para que reclame con claim.conf como
  # nodo propio (nunca se copia /var/lib/netdata de vps-01: es su identidad de nodo).
  rm -rf /var/lib/netdata/cloud.d
  if [[ -s "$tmp/usr/local/bin/netdata-aclk-watchdog.sh" ]]; then
    install -m 0755 "$tmp/usr/local/bin/netdata-aclk-watchdog.sh" /usr/local/bin/
    line=$(grep -h 'netdata-aclk-watchdog' "$tmp/var/spool/cron/crontabs/root" 2>/dev/null | head -1 || true)
    [[ -n "$line" ]] || line='*/5 * * * * /usr/local/bin/netdata-aclk-watchdog.sh'
    if ! crontab -l 2>/dev/null | grep -q netdata-aclk-watchdog; then
      { crontab -l 2>/dev/null || true; printf '%s\n' "$line"; } | crontab -
    fi
    log "watchdog de ACLK instalado"
  fi
  systemctl enable --now netdata >/dev/null 2>&1
  for i in $(seq 1 30); do
    curl -fsS --max-time 5 http://127.0.0.1:19999/api/v1/aclk 2>/dev/null | grep -q '"online":true' && break
    sleep 4
  done
  if curl -fsS --max-time 5 http://127.0.0.1:19999/api/v1/aclk 2>/dev/null | grep -q '"online":true'; then
    log "netdata en marcha y conectado a Netdata Cloud (intento $i)"
  else
    log "AVISO: netdata en marcha pero ACLK aun no conecta (curl -s localhost:19999/api/v1/aclk)"
  fi
}

case "${1:-}" in
  dr) shift; cmd_dr "$@" ;;
  finish) cmd_finish ;;
  go-live) cmd_go_live ;;
  postgres-sql) cmd_postgres_sql ;;
  netdata) shift; cmd_netdata "$@" ;;
  *) sed -n '2,/^set -E/p' "$0" | sed '$d'; exit 2 ;;
esac
