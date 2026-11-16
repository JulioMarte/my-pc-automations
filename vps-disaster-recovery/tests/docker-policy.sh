#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck disable=SC1091
source "$ROOT/tests/lib.sh"
VOL=vps-dr-policy-volume
CTR=vps-dr-policy-consumer
trap 'docker rm -f "$CTR" >/dev/null 2>&1 || true; docker volume rm "$VOL" >/dev/null 2>&1 || true; stop_minio; rm -rf /srv/vps-dr-policy; cleanup_candidate_state' EXIT

install_candidate_dependencies
start_minio
cleanup_candidate_state
install -d /srv/vps-dr-policy
printf 'docker policy fixture\n' > /srv/vps-dr-policy/fixture.txt

docker rm -f "$CTR" >/dev/null 2>&1 || true
docker volume rm "$VOL" >/dev/null 2>&1 || true
docker volume create "$VOL" >/dev/null
docker run -d --name "$CTR" -v "$VOL:/state" alpine:3.22 sh -c 'echo protected-state >/state/probe && sleep 3600' >/dev/null

write_ci_config ci-docker-policy ci-docker-policy /srv/vps-dr-policy true
init_repo

set +e
first_output=$("$SCRIPT" backup 2>&1)
first_rc=$?
set -e
printf '%s\n' "$first_output"
[[ $first_rc -ne 0 ]]
grep -Fq "$VOL" <<<"$first_output"
grep -Eq 'sin política DR|sin politica DR|política|politica' <<<"$first_output"

printf 'docker-volume\t%s\tvolume\tignore\t26\t%s\n' "$VOL" "$CTR" >> /etc/vps-backup/workloads.tsv
"$SCRIPT" backup
[[ -s /var/lib/vps-backup/state/last_backup_snapshot_id ]]

echo "DOCKER POLICY FAIL-CLOSED PASS volume=$VOL"
