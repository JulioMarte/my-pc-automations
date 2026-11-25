#!/usr/bin/env bash
# Instala en este host (como root) las alertas de backup y la herramienta de
# snapshots. Idempotente. No crea secretos: deja plantillas de alert.env y
# contabo.env si no existen.
#
#   ops/install.sh            alertas + vps-snapshot (el timer de snapshots solo se
#                             activa si contabo.env esta completo)
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")"
[[ $EUID -eq 0 ]] || { echo "ejecutar como root" >&2; exit 1; }
command -v jq >/dev/null || apt-get install -y -q jq

install -m 0755 vps-alert vps-backup-freshness vps-snapshot /usr/local/sbin/
install -m 0644 systemd/vps-alert-failed@.service systemd/vps-backup-freshness.service \
  systemd/vps-backup-freshness.timer systemd/vps-snapshot.service systemd/vps-snapshot.timer \
  /etc/systemd/system/
for u in vps-backup vps-backup-maintenance vps-backup-dr-test; do
  install -d -m 0755 "/etc/systemd/system/$u.service.d"
  install -m 0644 systemd/onfailure-alert.conf "/etc/systemd/system/$u.service.d/onfailure-alert.conf"
done

if [[ ! -e /etc/vps-backup/alert.env ]]; then
  topic="vps-$(hostname -s)-$(head -c 18 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | cut -c1-20)"
  printf 'NTFY_URL=https://ntfy.sh/%s\nNTFY_TOKEN=\nFRESHNESS_MAX_AGE_HOURS=8\n' "$topic" > /etc/vps-backup/alert.env
  chmod 600 /etc/vps-backup/alert.env
  echo "creado /etc/vps-backup/alert.env (topic nuevo)"
fi
if [[ ! -e /etc/vps-backup/contabo.env ]]; then
  cat > /etc/vps-backup/contabo.env <<'TPL'
# Usuario de API de Contabo con el rol limitado a snapshots de esta instancia.
CONTABO_CLIENT_ID=
CONTABO_CLIENT_SECRET=
CONTABO_API_USER=
CONTABO_API_PASSWORD=
CONTABO_INSTANCE_ID=
SNAPSHOT_PREFIX=vps-snap
SNAPSHOT_MAX=2
TPL
  chmod 600 /etc/vps-backup/contabo.env
  echo "creada plantilla /etc/vps-backup/contabo.env (rellenar)"
fi

systemctl daemon-reload
systemctl enable --now vps-backup-freshness.timer
if grep -qE '^CONTABO_API_PASSWORD=.+' /etc/vps-backup/contabo.env; then
  systemctl enable --now vps-snapshot.timer
else
  echo "vps-snapshot.timer sin activar: falta completar contabo.env"
fi
echo "instalado"
