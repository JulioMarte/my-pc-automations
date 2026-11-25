#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck disable=SC1091
source "$ROOT/tests/lib.sh"
trap 'rc=$?; write_failure_context /tmp/vps-dr-failure-context.txt; exit $rc' ERR
trap 'stop_minio; rm -rf /srv/vps-dr-ci-data /tmp/vps-dr-restore; cleanup_candidate_state' EXIT

install_candidate_dependencies
start_minio
cleanup_candidate_state
install -d /srv/vps-dr-ci-data
printf 'generation=1\n' > /srv/vps-dr-ci-data/state.txt
dd if=/dev/urandom of=/srv/vps-dr-ci-data/random.bin bs=1M count=16 status=none
for i in $(seq 1 2000); do printf 'small-file-%s-%s\n' "$i" "$RANDOM" > "/srv/vps-dr-ci-data/file-$i.txt"; done
(cd /srv/vps-dr-ci-data && sha256sum * | sort) > /tmp/expected-v1.sha256

write_ci_config ci-roundtrip ci-roundtrip /srv/vps-dr-ci-data false
init_repo

start_ns=$(date +%s%N)
"$SCRIPT" backup
first_ms=$(( ($(date +%s%N)-start_ns)/1000000 ))
first_sid=$(cat /var/lib/vps-backup/state/last_backup_snapshot_id)
[[ -n "$first_sid" ]]

printf 'generation=2\n' > /srv/vps-dr-ci-data/state.txt
for i in $(seq 1 20); do printf 'changed-%s-%s\n' "$i" "$RANDOM" >> "/srv/vps-dr-ci-data/file-$i.txt"; done
printf 'new file\n' > /srv/vps-dr-ci-data/new.txt
(cd /srv/vps-dr-ci-data && sha256sum * | sort) > /tmp/expected-v2.sha256

start_ns=$(date +%s%N)
"$SCRIPT" backup
second_ms=$(( ($(date +%s%N)-start_ns)/1000000 ))
second_sid=$(cat /var/lib/vps-backup/state/last_backup_snapshot_id)
[[ -n "$second_sid" && "$second_sid" != "$first_sid" ]]

rm -rf /tmp/vps-dr-restore
"$SCRIPT" restore --snapshot "$second_sid" --tag system --target /tmp/vps-dr-restore
(cd /tmp/vps-dr-restore/srv/vps-dr-ci-data && sha256sum * | sort) > /tmp/restored-v2.sha256
diff -u /tmp/expected-v2.sha256 /tmp/restored-v2.sha256

"$SCRIPT" check 1/1
"$SCRIPT" dr-plan --snapshot "$second_sid"
"$SCRIPT" dr-test

raw_bytes=$("$SCRIPT" storage-report | awk '/Unique repository data/{gsub(/[^0-9.]/,"",$0); print $0; exit}' || true)
mkdir -p "$ROOT/results"
cat > "$ROOT/results/s3-roundtrip.json" <<EOF_JSON
{"first_backup_ms":$first_ms,"second_backup_ms":$second_ms,"first_snapshot":"$first_sid","second_snapshot":"$second_sid","repository_report_numeric":"${raw_bytes:-unknown}"}
EOF_JSON
# The test runs under sudo with the product's secure umask. Artifacts are
# non-secret CI metrics, so make only this directory/file readable by the
# unprivileged Actions uploader without weakening production permissions.
chmod 0755 "$ROOT/results"
chmod 0644 "$ROOT/results/s3-roundtrip.json"
if [[ -n "${SUDO_UID:-}" && -n "${SUDO_GID:-}" ]]; then
  chown "$SUDO_UID:$SUDO_GID" "$ROOT/results" "$ROOT/results/s3-roundtrip.json" || true
fi

echo "ROUNDTRIP PASS first=${first_ms}ms second=${second_ms}ms"
