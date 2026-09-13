#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck disable=SC1091
source "$ROOT/tests/lib.sh"
SIZE_MIB=${SIZE_MIB:-256}
SMALL_FILES=${SMALL_FILES:-10000}
trap 'rc=$?; write_failure_context /tmp/vps-dr-failure-context.txt; exit $rc' ERR
trap 'stop_minio; rm -rf /srv/vps-dr-perf /tmp/vps-dr-perf-restore; cleanup_candidate_state' EXIT

install_candidate_dependencies
start_minio
cleanup_candidate_state
install -d /srv/vps-dr-perf
dd if=/dev/urandom of=/srv/vps-dr-perf/random.bin bs=1M count=$((SIZE_MIB/2)) status=none
yes 'compressible-vps-dr-fixture' | head -c $((SIZE_MIB/2*1024*1024)) > /srv/vps-dr-perf/compressible.txt || true
mkdir -p /srv/vps-dr-perf/small
for i in $(seq 1 "$SMALL_FILES"); do printf '%08d:%s\n' "$i" "$(printf '%032d' "$i")" > "/srv/vps-dr-perf/small/f-$i"; done

write_ci_config ci-perf ci-perf /srv/vps-dr-perf false
init_repo

before=$(date +%s%N)
"$SCRIPT" backup >/tmp/perf-backup1.log
backup1_ms=$(( ($(date +%s%N)-before)/1000000 ))
dd if=/dev/urandom of=/srv/vps-dr-perf/random.bin bs=1M count=1 seek=4 conv=notrunc status=none
for i in $(seq 1 100); do printf 'mutation-%s-%s\n' "$i" "$RANDOM" >> "/srv/vps-dr-perf/small/f-$i"; done

source_candidate_once
load_config
raw1=$(repository_raw_bytes)
before=$(date +%s%N)
"$SCRIPT" backup >/tmp/perf-backup2.log
backup2_ms=$(( ($(date +%s%N)-before)/1000000 ))
raw2=$(repository_raw_bytes)
sid=$(cat /var/lib/vps-backup/state/last_backup_snapshot_id)

before=$(date +%s%N)
"$SCRIPT" restore --snapshot "$sid" --tag system --target /tmp/vps-dr-perf-restore >/tmp/perf-restore.log
restore_ms=$(( ($(date +%s%N)-before)/1000000 ))
growth=$((raw2-raw1))
(( raw1 > 0 ))
(( growth >= 0 ))
(( growth < raw1 / 2 ))

mkdir -p "$ROOT/results"
cat > "$ROOT/results/performance.json" <<EOF_JSON
{"fixture_mib":$SIZE_MIB,"small_files":$SMALL_FILES,"backup1_ms":$backup1_ms,"backup2_ms":$backup2_ms,"restore_ms":$restore_ms,"repository_after_first_bytes":$raw1,"repository_after_second_bytes":$raw2,"incremental_growth_bytes":$growth}
EOF_JSON
cat > "$ROOT/results/performance.md" <<EOF_MD
# VPS DR CI benchmark

| Metric | Result |
|---|---:|
| Fixture | ${SIZE_MIB} MiB + ${SMALL_FILES} small files |
| First backup | ${backup1_ms} ms |
| Incremental backup | ${backup2_ms} ms |
| Restore | ${restore_ms} ms |
| Repo after first | ${raw1} bytes |
| Repo after second | ${raw2} bytes |
| Incremental growth | ${growth} bytes |
EOF_MD
cat "$ROOT/results/performance.md"
