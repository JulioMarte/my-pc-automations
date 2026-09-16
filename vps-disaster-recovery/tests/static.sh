#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SCRIPT=$(bash "$ROOT/tools/materialize-candidate.sh")

echo '== pinned release candidate =='
expected_sha=$(awk 'NF{print $1; exit}' "$ROOT/candidate/RELEASE_SHA256")
actual_sha=$(sha256sum "$SCRIPT" | awk '{print $1}')
[[ "$expected_sha" =~ ^[0-9a-f]{64}$ ]]
[[ "$actual_sha" == "$expected_sha" ]]

echo '== bash syntax =='
bash -n "$SCRIPT"

echo '== shellcheck errors =='
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck -S error -e SC1090,SC1091 "$SCRIPT"
  shellcheck -S error "$ROOT/tools/build-recovery-image.sh"
  shellcheck -S error -s bash -e SC1090,SC1091 "$ROOT/modules/ops-integrations.sh"
  shellcheck -S error -s bash -e SC1090,SC1091 "$ROOT/modules/ops-contabo-safety.sh"
  shellcheck -S error -s bash -e SC1090,SC1091 "$ROOT/modules/same-os-recovery.sh"
else
  echo 'shellcheck unavailable; skipping'
fi

echo '== version =='
[[ "$($SCRIPT version)" == 'vps-backup v1.4.3' ]]
grep -Fqx 'readonly APP_VERSION="1.4.3"' "$SCRIPT"
! grep -Eq '^readonly VERSION=' "$SCRIPT"

echo '== helper invariants =='
# shellcheck disable=SC1090
source "$SCRIPT"
validate_os
validate_backup_id 'coolify-prod-01'
! validate_backup_id '../bad'
validate_b2_bucket 'vps-backups'
! validate_b2_bucket 'bad..bucket'
validate_hhmm '23:59'
! validate_hhmm '24:00'
version_ge '0.19.1' '0.19.1'
version_ge '0.20.0' '0.19.1'
! version_ge '0.18.9' '0.19.1'

echo '== backup profiles =='
apply_backup_profile economy
[[ "$BACKUP_PROFILE/$BACKUP_INTERVAL_HOURS/$DATABASE_RPO_HOURS" == 'economy/12/12' ]]
apply_backup_profile balanced
[[ "$BACKUP_PROFILE/$BACKUP_INTERVAL_HOURS/$DATABASE_RPO_HOURS" == 'balanced/6/6' ]]
apply_backup_profile critical
[[ "$BACKUP_PROFILE/$BACKUP_INTERVAL_HOURS/$DATABASE_RPO_HOURS" == 'critical/2/2' ]]
! apply_backup_profile nonsense

echo '== systemd calendar matrix =='
if command -v systemd-analyze >/dev/null 2>&1; then
  for start in $(seq -w 0 23); do
    for interval in 1 2 3 4 6 8 12 24; do
      hours=$(calendar_hours_for_interval "$start" "$interval")
      systemd-analyze calendar "*-*-* ${hours}:17:00" >/dev/null
    done
  done
fi

echo '== set -u restore regressions =='
grep -Fq 'local restore_root="$1" policy=""' "$SCRIPT"
grep -Fq 'local restore_root="$1" volumes_root="$2" policy=""' "$SCRIPT"
! grep -Fq 'policy="${restore_root}/' "$SCRIPT"
! grep -Fq 'restore_hashes="${dir}/restore-hooks.sha256"' "$SCRIPT"

echo '== Restic timestamp regression =='
! grep -Fq -- '--time "$BACKUP_RUN_TIME"' "$SCRIPT"

echo '== recovery safety =='
grep -Fq -- '--require-same-os' "$SCRIPT"
grep -Fq 'schema:3' "$SCRIPT"
grep -Fq 'backup_profile:$profile' "$SCRIPT"
grep -Fq 'apt-mark showmanual' "$SCRIPT"
grep -Fq 'Recovery bloquea S3 sin TLS' "$SCRIPT"
grep -Fq 'recover_same_os_portable "$sid"' "$SCRIPT"
grep -Fq 'same_os_recovery_verify_os' "$SCRIPT"
grep -Fq "--exclude='/netplan/***'" "$SCRIPT"
grep -Fq "--exclude='/ssh/ssh_host_*'" "$SCRIPT"
grep -Fq '/var/lib/docker|/var/lib/docker/*' "$SCRIPT"
! grep -Fq 'Recovery automático genérico de rootfs todavía no es seguro' "$SCRIPT"

echo '== operational integrations =='
grep -Fq 'provider) cmd_provider "$@" ;;' "$SCRIPT"
grep -Fq 'coolify-policy) cmd_coolify_policy "$@" ;;' "$SCRIPT"
grep -Fq 'dr_plan_ops_extension "$sid"' "$SCRIPT"
grep -Fq 'CONTABO_REQUIRE_RECENT_RESTIC="true"' "$SCRIPT"
grep -Fq 'CONTABO_SNAPSHOT_KEEP="1"' "$SCRIPT"
grep -Fq 'CONTABO_SNAPSHOT_SLOT_LIMIT="2"' "$SCRIPT"
grep -Fq 'CONTABO_SNAPSHOT_VERIFY_TIMEOUT_SECONDS="300"' "$SCRIPT"
grep -Fq 'Rotación segura requiere KEEP < SLOT_LIMIT' "$SCRIPT"
grep -Fq '/snapshots?size=100' "$SCRIPT"
grep -Fq 'contabo_snapshot_wait_visible "$sid"' "$SCRIPT"
grep -Fq 'no rotaré con inventario paginado incompleto' "$SCRIPT"
grep -Fq 'COOLIFY_DB_BACKUP_AUTHORITY="vps-backup"' "$SCRIPT"
grep -Fq 'COOLIFY_DB_NATIVE_SUPPLEMENTAL="false"' "$SCRIPT"
grep -Fq 'coolify-native no puede declarar AUTO_DR_READY' "$SCRIPT"

echo 'STATIC PASS'
