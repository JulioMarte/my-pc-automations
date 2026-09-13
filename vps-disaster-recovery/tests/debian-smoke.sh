#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=${1:-/workspace/vps-disaster-recovery}
SCRIPT=$($ROOT/tools/materialize-candidate.sh /tmp/vps-backup-v1.3.sh)
apt-get update >/dev/null
apt-get install -y --no-install-recommends ca-certificates curl bzip2 dpkg bash coreutils grep sed gawk >/dev/null
bash -n "$SCRIPT"
"$SCRIPT" version | grep -qx 'vps-backup v1.3.0'
# Source-only helper tests validate the Debian-specific dpkg version comparison path.
# shellcheck disable=SC1090
source "$SCRIPT"
validate_os
version_ge 0.19.1 0.19.1
! version_ge 0.18.9 0.19.1
validate_backup_id debian-ci
printf 'DEBIAN SMOKE PASS: '
. /etc/os-release; printf '%s\n' "$PRETTY_NAME"
