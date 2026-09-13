#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SCRIPT=${SCRIPT:-$(bash "$ROOT/tools/materialize-candidate.sh")}
MINIO_ENDPOINT=${MINIO_ENDPOINT:-http://127.0.0.1:9000}
MINIO_USER=${MINIO_USER:-ciadmin}
MINIO_PASSWORD=${MINIO_PASSWORD:-ci-minio-password-123456}
TEST_BUCKET=${TEST_BUCKET:-vps-dr-ci}
MINIO_IMAGE=${MINIO_IMAGE:-quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z}

source_candidate_once() {
  declare -F load_config >/dev/null 2>&1 || source "$SCRIPT"
}

wait_http() {
  local url=$1
  for _ in $(seq 1 60); do curl -fsS "$url" >/dev/null 2>&1 && return 0; sleep 1; done
  return 1
}

start_minio() {
  docker rm -f vps-dr-minio >/dev/null 2>&1 || true
  docker pull "$MINIO_IMAGE" >/dev/null
  docker run -d --name vps-dr-minio -p 9000:9000 \
    -e MINIO_ROOT_USER="$MINIO_USER" \
    -e MINIO_ROOT_PASSWORD="$MINIO_PASSWORD" \
    "$MINIO_IMAGE" server /data --console-address ':9001' >/dev/null
  wait_http "$MINIO_ENDPOINT/minio/health/live"
  docker exec vps-dr-minio sh -c \
    "mc alias set ci 'http://127.0.0.1:9000' '$MINIO_USER' '$MINIO_PASSWORD' >/dev/null && mc mb --ignore-existing ci/$TEST_BUCKET >/dev/null"
}

stop_minio() { docker rm -f vps-dr-minio >/dev/null 2>&1 || true; }

install_candidate_dependencies() {
  source_candidate_once
  ensure_directories
  install_packages
  validate_restic_version
}

write_ci_config() {
  local id=$1 prefix=$2 path=$3 module_docker=${4:-false}
  install -d -m 0700 /etc/vps-backup /var/lib/vps-backup /var/tmp/vps-backup
  cat > /etc/vps-backup/config.conf <<EOF_CFG
BACKUP_ID=$id
BACKUP_MODE=selected
ONE_FILE_SYSTEM=true
MODULE_POSTGRES=false
MODULE_MYSQL=false
MODULE_DOCKER=$module_docker
BACKUP_DOCKER_VOLUMES=false
MODULE_FUSIONPBX=false
KEEP_DAILY=2
KEEP_WEEKLY=1
KEEP_MONTHLY=1
KEEP_YEARLY=0
BACKUP_TIME=03:00
BACKUP_INTERVAL_HOURS=6
MAINTENANCE_TIME=04:00
MAINTENANCE_DAY=Sun
RANDOM_DELAY_BACKUP=0
RANDOM_DELAY_MAINT=0
CHECK_READ_DATA_SUBSET=1/1
CHECK_ROTATION_PARTS=1
POSTGRES_PROTECTION=ignore
MYSQL_PROTECTION=ignore
DOCKER_DB_PROTECTION=policy
DOCKER_VOLUME_PROTECTION=policy
MYSQL_NONTRANSACTIONAL_POLICY=fail
MIN_STAGING_FREE_MIB=64
STAGING_HEADROOM_PERCENT=110
MAX_BACKUP_AGE_HOURS=36
SYSTEM_RPO_HOURS=26
DATABASE_RPO_HOURS=6
VOLUME_RPO_HOURS=26
TARGET_RTO_MINUTES=90
LOCK_WAIT_SEC=30
BACKUP_TIMEOUT_SEC=1800
MAINTENANCE_TIMEOUT_SEC=1800
DR_TEST_DAY=Sun
DR_TEST_TIME=05:30
DR_TEST_MONTHLY=true
STORAGE_PROVIDER=s3
S3_ENDPOINT=$MINIO_ENDPOINT
S3_REGION=us-east-1
S3_BUCKET=$TEST_BUCKET
S3_PREFIX=$prefix
S3_BUCKET_LOOKUP=path
ALLOW_INSECURE_S3=true
S3_SESSION_TOKEN=
RESTIC_CACERT=
BACKBLAZE_USD_PER_TB_MONTH=6.95
MODULE_COOLIFY=false
COOLIFY_ROOT=/data/coolify
COOLIFY_CONTAINER=coolify
COOLIFY_DB_CONTAINER=coolify-db
COOLIFY_DB_NAME=coolify
COOLIFY_DB_USER=coolify
COOLIFY_BACKUP_LOCAL_WARN_GIB=5
COOLIFY_DR_RESTORE_SAFE_FILES=true
COOLIFY_CLI_ENABLED=false
COOLIFY_API_URL=http://127.0.0.1:8000
COOLIFY_API_TOKEN=
COOLIFY_CLI_CONTEXT=vps-backup
MYSQL_AUTH_MODE=socket
EOF_CFG
  cat > /etc/vps-backup/credentials <<EOF_CRED
AWS_ACCESS_KEY_ID=$MINIO_USER
AWS_SECRET_ACCESS_KEY=$MINIO_PASSWORD
AWS_DEFAULT_REGION=us-east-1
AWS_SESSION_TOKEN=
RESTIC_REPOSITORY=s3:$MINIO_ENDPOINT/$TEST_BUCKET/$prefix
RESTIC_PASSWORD_FILE=/etc/vps-backup/restic-password
EOF_CRED
  printf '%s\n' 'ci-restic-password-please-change' > /etc/vps-backup/restic-password
  printf '%s\n' "$path" > /etc/vps-backup/paths.txt
  cat > /etc/vps-backup/excludes.txt <<'EOF_EX'
/dev
/proc
/sys
/run
/tmp
/var/tmp
/var/cache
/var/lib/vps-backup/restore
/var/lib/vps-backup/disaster-recovery
/etc/vps-backup/credentials
/etc/vps-backup/restic-password
EOF_EX
  printf '# kind\tname\tengine\tstrategy\tmax_age_hours\textra\n' > /etc/vps-backup/workloads.tsv
  chmod 0600 /etc/vps-backup/{config.conf,credentials,restic-password,paths.txt,excludes.txt,workloads.tsv}
  source_candidate_once
  ensure_directories
  write_mount_baseline
}

init_repo() {
  source_candidate_once
  load_config
  if ! repo_exists; then restic_cmd init; fi
}

cleanup_candidate_state() {
  rm -rf /etc/vps-backup /var/lib/vps-backup /var/cache/vps-backup /var/tmp/vps-backup /var/log/vps-backup.log || true
}
