#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck disable=SC1091
source "$ROOT/tests/lib.sh"
trap 'rc=$?; write_failure_context /tmp/vps-dr-failure-context.txt; exit $rc' ERR
trap 'docker rm -f ci-mariadb >/dev/null 2>&1 || true; docker volume rm ci-maria-data >/dev/null 2>&1 || true; stop_minio; rm -rf /srv/vps-dr-ci-maria /tmp/maria-restore-root; cleanup_candidate_state' EXIT

install_candidate_dependencies
start_minio
cleanup_candidate_state
install -d /srv/vps-dr-ci-maria
printf 'mariadb integration fixture\n' > /srv/vps-dr-ci-maria/fixture.txt

docker volume create ci-maria-data >/dev/null
docker run -d --name ci-mariadb \
  -e MARIADB_ROOT_PASSWORD=ci-secret \
  -e MARIADB_DATABASE=app \
  -v ci-maria-data:/var/lib/mysql \
  mariadb:11.4 >/dev/null
for _ in $(seq 1 90); do docker exec -e MYSQL_PWD=ci-secret ci-mariadb mariadb -uroot -e 'SELECT 1' >/dev/null 2>&1 && break; sleep 1; done
docker exec -e MYSQL_PWD=ci-secret ci-mariadb mariadb -uroot app -e \
  "CREATE TABLE dr_probe(id INT PRIMARY KEY, payload CHAR(32)) ENGINE=InnoDB; INSERT INTO dr_probe SELECT seq, MD5(seq) FROM seq_1_to_5000;" >/dev/null
expected=$(docker exec -e MYSQL_PWD=ci-secret ci-mariadb mariadb -uroot app --batch --skip-column-names -e \
  "SET SESSION group_concat_max_len=10485760; SELECT MD5(GROUP_CONCAT(CONCAT(id,payload) ORDER BY id SEPARATOR ',')) FROM dr_probe;")
[[ -n "$expected" ]]

write_ci_config ci-mariadb-test ci-mariadb-test /srv/vps-dr-ci-maria true
cat >> /etc/vps-backup/workloads.tsv <<'EOF_POLICY'
docker-db	ci-mariadb	mariadb	builtin	6	mariadb:11.4
docker-volume	ci-maria-data	volume	database-skip	26	ci-mariadb
EOF_POLICY
init_repo
"$SCRIPT" backup
sid=$(cat /var/lib/vps-backup/state/last_backup_snapshot_id)

rm -rf /tmp/maria-restore-root
"$SCRIPT" restore --snapshot "$sid" --tag system --target /tmp/maria-restore-root
[[ -s /tmp/maria-restore-root/var/lib/vps-backup/staging/workloads/docker-db/ci-mariadb/SHA256SUMS ]]

docker rm -f ci-mariadb >/dev/null
docker volume rm ci-maria-data >/dev/null
docker volume create ci-maria-data >/dev/null
docker run -d --name ci-mariadb \
  -e MARIADB_ROOT_PASSWORD=ci-secret \
  -v ci-maria-data:/var/lib/mysql \
  mariadb:11.4 >/dev/null
for _ in $(seq 1 90); do docker exec -e MYSQL_PWD=ci-secret ci-mariadb mariadb -uroot -e 'SELECT 1' >/dev/null 2>&1 && break; sleep 1; done

source_candidate_once
restore_policy_databases /tmp/maria-restore-root
actual=$(docker exec -e MYSQL_PWD=ci-secret ci-mariadb mariadb -uroot app --batch --skip-column-names -e \
  "SET SESSION group_concat_max_len=10485760; SELECT MD5(GROUP_CONCAT(CONCAT(id,payload) ORDER BY id SEPARATOR ',')) FROM dr_probe;")
[[ "$actual" == "$expected" ]]

echo "MARIADB ROUNDTRIP PASS checksum=$actual"
