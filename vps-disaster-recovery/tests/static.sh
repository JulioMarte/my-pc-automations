#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SCRIPT=$(bash "$ROOT/tools/materialize-candidate.sh")

echo '== bash syntax =='
bash -n "$SCRIPT"

echo '== shellcheck errors =='
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck -S error -e SC1090,SC1091 "$SCRIPT"
  shellcheck -S error "$ROOT/tools/build-recovery-image.sh"
else
  echo 'shellcheck unavailable; skipping'
fi

echo '== version =='
[[ "$($SCRIPT version)" == 'vps-backup v1.4.1' ]]
grep -Fqx 'readonly APP_VERSION="1.4.1"' "$SCRIPT"
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

echo 'STATIC PASS'
