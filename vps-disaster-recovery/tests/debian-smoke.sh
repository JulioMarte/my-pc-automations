#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=${1:-/workspace/vps-disaster-recovery}
apt-get update >/dev/null
apt-get install -y --no-install-recommends ca-certificates curl bzip2 dpkg bash coreutils grep sed gawk patch git >/dev/null
SCRIPT=$(bash "$ROOT/tools/materialize-candidate.sh" /tmp/vps-backup-v1.4.2.sh)
bash -n "$SCRIPT"
"$SCRIPT" version | grep -qx 'vps-backup v1.4.2'
# Source-only helper tests validate Debian/Ubuntu os-release handling and dpkg comparison.
# shellcheck disable=SC1090
source "$SCRIPT"
validate_os
version_ge 0.19.1 0.19.1
! version_ge 0.18.9 0.19.1
validate_backup_id debian-ci
apply_backup_profile balanced
[[ "$BACKUP_INTERVAL_HOURS/$DATABASE_RPO_HOURS" == '6/6' ]]
# The safety overlay must be present on every supported distro, not merely CI's Ubuntu host.
[[ "$CONTABO_SNAPSHOT_KEEP/$CONTABO_SNAPSHOT_SLOT_LIMIT/$CONTABO_SNAPSHOT_VERIFY_TIMEOUT_SECONDS" == '1/2/300' ]]
printf 'DEBIAN SMOKE PASS: '
. /etc/os-release; printf '%s\n' "$PRETTY_NAME"
