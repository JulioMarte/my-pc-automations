#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck disable=SC1091
source "$ROOT/tests/lib.sh"
trap 'docker rm -f ci-postgres >/dev/null 2>&1 || true; docker volume rm ci-pg-data >/dev/null 2>&1 || true; stop_minio; rm -rf /srv/vps-dr-ci-data /tmp/pg-restore-root; cleanup_candidate_state' EXIT

install_candidate_dependencies
start_minio
cleanup_candidate_state
install -d /srv/vps-dr-ci-data
printf 'db integration fixture\n' > /srv/vps-dr-ci-data/fixture.txt

docker volume create ci-pg-data >/dev/null
docker run -d --name ci-postgres -e POSTGRES_PASSWORD=ci-secret -e POSTGRES_USER=ciuser -e POSTGRES_DB=app -v ci-pg-data:/var/lib/postgresql/data postgres:16 >/dev/null
for _ in $(seq 1 60); do docker exec ci-postgres pg_isready -U ciuser -d app >/dev/null 2>&1 && break; sleep 1; done
docker exec ci-postgres psql -U ciuser -d app -v ON_ERROR_STOP=1 -c 'CREATE TABLE dr_probe(id integer primary key, payload text); INSERT INTO dr_probe SELECT g, md5(g::text) FROM generate_series(1,5000) g;' >/dev/null
expected=$(docker exec ci-postgres psql -U ciuser -d app -Atc "SELECT md5(string_agg(id::text||payload, ',' ORDER BY id)) FROM dr_probe;")

write_ci_config ci-postgres-test ci-postgres-test /srv/vps-dr-ci-data true
cat >> /etc/vps-backup/workloads.tsv <<'EOF_POLICY'
docker-db	ci-postgres	postgres	builtin	6	postgres:16
docker-volume	ci-pg-data	volume	database-skip	26	ci-postgres
EOF_POLICY
init_repo
"$SCRIPT" backup
sid=$(cat /var/lib/vps-backup/state/last_backup_snapshot_id)

rm -rf /tmp/pg-restore-root
"$SCRIPT" restore --snapshot "$sid" --tag system --target /tmp/pg-restore-root
[[ -s /tmp/pg-restore-root/var/lib/vps-backup/staging/workloads/docker-db/ci-postgres/SHA256SUMS ]]

# Simulate data loss while preserving the reconstructable container recipe for this focused test.
docker rm -f ci-postgres >/dev/null
docker volume rm ci-pg-data >/dev/null
docker volume create ci-pg-data >/dev/null
docker run -d --name ci-postgres -e POSTGRES_PASSWORD=ci-secret -e POSTGRES_USER=ciuser -e POSTGRES_DB=app -v ci-pg-data:/var/lib/postgresql/data postgres:16 >/dev/null
for _ in $(seq 1 60); do docker exec ci-postgres pg_isready -U ciuser -d app >/dev/null 2>&1 && break; sleep 1; done

# Exercise the candidate's actual restore implementation against the restored bundle.
# shellcheck disable=SC1090
source "$SCRIPT"
restore_policy_databases /tmp/pg-restore-root
actual=$(docker exec ci-postgres psql -U ciuser -d app -Atc "SELECT md5(string_agg(id::text||payload, ',' ORDER BY id)) FROM dr_probe;")
[[ "$actual" == "$expected" ]]

echo "POSTGRES ROUNDTRIP PASS checksum=$actual"
