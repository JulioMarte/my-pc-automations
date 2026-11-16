#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SCRIPT=${SCRIPT:-$(bash "$ROOT/tools/materialize-candidate.sh")}
MINIO_ENDPOINT=${MINIO_ENDPOINT:-http://127.0.0.1:9000}
MINIO_USER=${MINIO_USER:-ciadmin}
MINIO_PASSWORD=${MINIO_PASSWORD:-ci-minio-password-123456}
TEST_BUCKET=${TEST_BUCKET:-vps-dr-ci}
MINIO_RELEASE="RELEASE.2025-09-07T16-13-09Z"
MINIO_ASSET="minio.linux-amd64.${MINIO_RELEASE}"
MINIO_DOWNLOAD_URL="https://github.com/minio/minio/releases/download/${MINIO_RELEASE}/${MINIO_ASSET}"
MINIO_SHA256="7c5bd8512c6e966455b1d198209358b2d191c77a83ab377c4073281065fb855f"
MC_RELEASE="RELEASE.2025-08-13T08-35-41Z"
MC_ASSET="mc.linux-amd64.${MC_RELEASE}"
MC_DOWNLOAD_URL="https://github.com/minio/mc/releases/download/${MC_RELEASE}/${MC_ASSET}"
MC_SHA256="01f866e9c5f9b87c2b09116fa5d7c06695b106242d829a8bb32990c00312e891"
MINIO_FIXTURE_DIR="/tmp/vps-dr-minio-fixture"
MINIO_BIN="${MINIO_FIXTURE_DIR}/minio"
MC_BIN="${MINIO_FIXTURE_DIR}/mc"
MINIO_PID_FILE="${MINIO_FIXTURE_DIR}/minio.pid"
MINIO_DATA_DIR="${MINIO_FIXTURE_DIR}/data"
MINIO_LOG="${MINIO_FIXTURE_DIR}/minio.log"

source_candidate_once() {
  declare -F load_config >/dev/null 2>&1 || source "$SCRIPT"
}

wait_http() {
  local url=$1
  for _ in $(seq 1 60); do curl -fsS "$url" >/dev/null 2>&1 && return 0; sleep 1; done
  return 1
}

# wait_container_ready <container> <intentos_consecutivos> <timeout_seg> -- <comando...>
# Ejecuta <comando...> con docker exec y solo devuelve 0 tras <intentos_consecutivos>
# exitos seguidos separados por 1s, dentro de <timeout_seg>. Evita dar por listo un
# servidor temporal (p.ej. el arranque de MariaDB) que luego se reinicia.
# Si expira, imprime un error claro con los ultimos logs del contenedor y devuelve 1.
wait_container_ready() {
  if (($# < 4)); then
    echo 'usage: wait_container_ready <container> <consecutive> <timeout_sec> -- <command...>' >&2
    return 2
  fi
  local container=$1 consecutive=$2 timeout=$3
  shift 3
  if [[ $1 == -- ]]; then shift; fi
  local ok=0 elapsed=0
  while ((elapsed < timeout)); do
    if docker exec "$container" "$@" >/dev/null 2>&1; then
      ok=$((ok + 1))
      if ((ok >= consecutive)); then
        return 0
      fi
    else
      ok=0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  echo "ERROR: container '$container' no respondio $consecutive veces seguidas en ${timeout}s" >&2
  echo "--- docker logs --tail 50 $container ---" >&2
  docker logs --tail 50 "$container" >&2 2>&1 || true
  echo "---------------------------------------" >&2
  return 1
}

verify_fixture_binary() {
  local file=$1 expected=$2
  [[ -f "$file" ]] || return 1
  printf '%s  %s\n' "$expected" "$file" | sha256sum -c - >/dev/null 2>&1
}

download_fixture_binary() {
  local url=$1 expected=$2 target=$3
  if verify_fixture_binary "$target" "$expected"; then
    return 0
  fi
  rm -f "$target"
  curl -fL --retry 3 --retry-all-errors --connect-timeout 20 --max-time 180 \
    "$url" -o "$target"
  verify_fixture_binary "$target" "$expected" || {
    echo "ERROR: checksum inválido para fixture $(basename "$target")" >&2
    rm -f "$target"
    return 1
  }
  chmod 0755 "$target"
}

install_minio_fixture() {
  case "$(uname -m)" in
    x86_64|amd64) ;;
    *) echo "ERROR: fixture MinIO pinneado solo para amd64 en este CI" >&2; return 1 ;;
  esac
  install -d -m 0700 "$MINIO_FIXTURE_DIR"
  download_fixture_binary "$MINIO_DOWNLOAD_URL" "$MINIO_SHA256" "$MINIO_BIN"
  download_fixture_binary "$MC_DOWNLOAD_URL" "$MC_SHA256" "$MC_BIN"
}

start_minio() {
  stop_minio
  install_minio_fixture
  install -d -m 0700 "$MINIO_DATA_DIR"

  MINIO_ROOT_USER="$MINIO_USER" MINIO_ROOT_PASSWORD="$MINIO_PASSWORD" \
    "$MINIO_BIN" server "$MINIO_DATA_DIR" \
      --address 127.0.0.1:9000 --console-address 127.0.0.1:9001 \
      >"$MINIO_LOG" 2>&1 &
  local pid=$!
  printf '%s\n' "$pid" > "$MINIO_PID_FILE"

  if ! wait_http "$MINIO_ENDPOINT/minio/health/live"; then
    echo 'ERROR: MinIO fixture no quedó healthy' >&2
    tail -n 100 "$MINIO_LOG" >&2 2>/dev/null || true
    return 1
  fi
  "$MC_BIN" alias set ci "$MINIO_ENDPOINT" "$MINIO_USER" "$MINIO_PASSWORD" >/dev/null
  "$MC_BIN" mb --ignore-existing "ci/$TEST_BUCKET" >/dev/null
}

stop_minio() {
  local pid=''
  if [[ -r "$MINIO_PID_FILE" ]]; then
    pid=$(cat "$MINIO_PID_FILE" 2>/dev/null || true)
  fi
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" >/dev/null 2>&1; then
    kill "$pid" >/dev/null 2>&1 || true
    for _ in $(seq 1 20); do
      kill -0 "$pid" >/dev/null 2>&1 || break
      sleep 0.25
    done
    kill -0 "$pid" >/dev/null 2>&1 && kill -KILL "$pid" >/dev/null 2>&1 || true
    wait "$pid" 2>/dev/null || true
  fi
  rm -rf "$MINIO_FIXTURE_DIR"
}

write_failure_context() {
  local out=${1:-/tmp/vps-dr-failure-context.txt}
  {
    echo '=== candidate ==='
    "$SCRIPT" version 2>&1 || true
    echo '=== os ==='
    cat /etc/os-release 2>/dev/null || true
    echo '=== restic ==='
    restic version 2>&1 || true
    echo '=== docker ==='
    docker version 2>&1 || true
    echo '=== docker ps ==='
    docker ps -a 2>&1 || true
    echo '=== docker volumes ==='
    docker volume ls 2>&1 || true
    echo '=== disk ==='
    df -h 2>&1 || true
    echo '=== vps-backup log tail ==='
    tail -n 250 /var/log/vps-backup.log 2>/dev/null || true
  } >"$out" 2>&1
  chmod 0644 "$out" 2>/dev/null || true
  echo '===== CI FAILURE CONTEXT =====' >&2
  cat "$out" >&2 || true
  echo '===== END FAILURE CONTEXT =====' >&2
}

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
