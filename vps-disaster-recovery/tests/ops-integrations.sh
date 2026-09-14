#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck disable=SC1091
source "$ROOT/tests/lib.sh"

install_candidate_dependencies
cleanup_candidate_state
source_candidate_once
# shellcheck disable=SC1091
source "$ROOT/modules/ops-integrations.sh"

T=$(mktemp -d)
trap 'rm -rf "$T"; cleanup_candidate_state' EXIT

# ---------------------------------------------------------------------------
# Contabo: create -> verify -> prune. Never prune before the new snapshot is
# visible. API calls are mocked but use the exact public adapter functions.
# ---------------------------------------------------------------------------
load_contabo_config() { :; }
repo_exists() { return 0; }
latest_system_snapshot_id() { printf '%s\n' 'abcdef1234567890'; }
snapshot_time_by_id() { date -u +%Y-%m-%dT%H:%M:%SZ; }
age_hours_from_iso() { printf '0\n'; }

CONTABO_ENABLED=true
CONTABO_INSTANCE_ID=12345
CONTABO_SNAPSHOT_KEEP=3
CONTABO_SNAPSHOT_PREFIX=vps-dr
CONTABO_SNAPSHOT_MAX_AGE_HOURS=192
CONTABO_SNAPSHOT_REQUIRED_FOR_DR=false
CONTABO_REQUIRE_RECENT_RESTIC=true
CONTABO_CLIENT_ID=test-client
CONTABO_CLIENT_SECRET=test-secret
CONTABO_API_USER=test-user
CONTABO_API_PASSWORD=test-password
CONTABO_AUTH_URL=http://127.0.0.1:9/token
CONTABO_API_BASE_URL=http://127.0.0.1:9/v1
BACKUP_ID=ci-ops
MAX_BACKUP_AGE_HOURS=36
# STATE_DIR is deliberately readonly in the production candidate. The fixture
# uses that real state path and cleanup_candidate_state removes it afterward.
install -d -m 0700 "$STATE_DIR"
CONTABO_STATE="$T/contabo.json"
CONTABO_LOG="$T/contabo.log"
cat >"$CONTABO_STATE" <<'JSON'
{"data":[
 {"snapshotId":"snap-old-1","name":"vps-dr-20260901","createdDate":"2026-09-01T00:00:00Z"},
 {"snapshotId":"snap-old-2","name":"vps-dr-20260902","createdDate":"2026-09-02T00:00:00Z"},
 {"snapshotId":"snap-old-3","name":"vps-dr-20260903","createdDate":"2026-09-03T00:00:00Z"},
 {"snapshotId":"unmanaged","name":"manual-snapshot","createdDate":"2026-08-01T00:00:00Z"}
]}
JSON

contabo_api_request() {
  local method="$1" path="$2" body="${3:-}"
  printf '%s %s\n' "$method" "$path" >>"$CONTABO_LOG"
  case "$method:$path" in
    GET:/compute/instances/12345/snapshots)
      cat "$CONTABO_STATE"
      ;;
    POST:/compute/instances/12345/snapshots)
      local name
      name=$(printf '%s' "$body" | jq -r '.name')
      jq --arg name "$name" '.data += [{snapshotId:"snap-new",name:$name,createdDate:"2026-09-14T04:00:00Z"}]' "$CONTABO_STATE" >"$CONTABO_STATE.tmp"
      mv "$CONTABO_STATE.tmp" "$CONTABO_STATE"
      printf '%s\n' '{"data":[{"snapshotId":"snap-new"}]}'
      ;;
    DELETE:/compute/instances/12345/snapshots/*)
      local sid=${path##*/}
      jq --arg sid "$sid" '.data |= map(select(.snapshotId != $sid))' "$CONTABO_STATE" >"$CONTABO_STATE.tmp"
      mv "$CONTABO_STATE.tmp" "$CONTABO_STATE"
      ;;
    *)
      echo "unexpected mock Contabo request: $method $path" >&2
      return 1
      ;;
  esac
}

contabo_snapshot_create --prune
[[ "$(grep -n '^POST ' "$CONTABO_LOG" | head -1 | cut -d: -f1)" -lt "$(grep -n '^DELETE ' "$CONTABO_LOG" | head -1 | cut -d: -f1)" ]]
jq -e '[.data[] | select(.name|startswith("vps-dr"))] | length == 3' "$CONTABO_STATE" >/dev/null
jq -e 'any(.data[]; .snapshotId=="snap-new")' "$CONTABO_STATE" >/dev/null
jq -e 'any(.data[]; .snapshotId=="unmanaged")' "$CONTABO_STATE" >/dev/null
! jq -e 'any(.data[]; .snapshotId=="snap-old-1")' "$CONTABO_STATE" >/dev/null

actions_before=$(wc -l <"$CONTABO_LOG")
contabo_snapshot_create --dry-run
actions_after=$(wc -l <"$CONTABO_LOG")
[[ "$actions_before" -eq "$actions_after" ]]

# ---------------------------------------------------------------------------
# Coolify: automatic DR stays authoritative in vps-backup. Enforce may create a
# short-retention S3 schedule as a supplemental copy, but native authority is
# deliberately rejected from AUTO_DR_READY until a programmatic restore path is
# proven in destructive CI.
# ---------------------------------------------------------------------------
load_coolify_policy_config() { :; }
detect_coolify() { return 0; }
validate_workload_protection() { return 0; }
COOLIFY_POLICY_MODE=enforce
COOLIFY_DB_BACKUP_AUTHORITY=vps-backup
COOLIFY_DB_NATIVE_SUPPLEMENTAL=true
COOLIFY_STORAGE_AUTHORITY=restic
COOLIFY_POLICY_REQUIRE_S3=true
COOLIFY_POLICY_S3_STORAGE_UUID=s3-ci
COOLIFY_API_TOKEN=ci-token
BACKUP_PROFILE=balanced
COOLIFY_DB_FREQUENCY=''
COOLIFY_DB_RETENTION_S3=''
COOLIFY_DB_RETENTION_LOCAL=1
COOLIFY_DB_BACKUP_TIMEOUT=3600
COOLIFY_STORAGE_FREQUENCY=''
COOLIFY_POLICY_FAIL_ON_UNSUPPORTED_DB=true
COOLIFY_STATE="$T/coolify-schedule.json"
COOLIFY_CALLS="$T/coolify-calls.log"
printf '%s\n' '[]' >"$COOLIFY_STATE"

coolify_policy_api() {
  local method="$1" path="$2" body="${3:-}"
  printf '%s %s\n' "$method" "$path" >>"$COOLIFY_CALLS"
  case "$method:$path" in
    GET:/databases)
      printf '%s\n' '[{"uuid":"db-postgres","name":"postgres-ci","type":"postgresql"}]'
      ;;
    GET:/databases/db-postgres/backups)
      cat "$COOLIFY_STATE"
      ;;
    POST:/databases/db-postgres/backups)
      jq -e '.enabled==true and .save_s3==true and .s3_storage_uuid=="s3-ci" and .dump_all==true' <<<"$body" >/dev/null
      printf '%s\n' '[{"uuid":"schedule-1","enabled":true,"save_s3":true,"s3_storage_uuid":"s3-ci"}]' >"$COOLIFY_STATE"
      printf '%s\n' '{"uuid":"schedule-1"}'
      ;;
    *)
      echo "unexpected mock Coolify request: $method $path" >&2
      return 1
      ;;
  esac
}

coolify_policy_enforce
grep -q '^POST /databases/db-postgres/backups$' "$COOLIFY_CALLS"
coolify_policy_audit

COOLIFY_DB_BACKUP_AUTHORITY=coolify-native
if coolify_policy_audit; then
  echo 'coolify-native authority unexpectedly claimed AUTO_DR readiness' >&2
  exit 1
fi

# Unsupported engines remain fail-closed instead of silently pretending all
# containers are protected by generic storage archives.
coolify_policy_api() {
  local method="$1" path="$2"
  case "$method:$path" in
    GET:/databases) printf '%s\n' '[{"uuid":"db-redis","name":"redis-ci","type":"redis"}]' ;;
    *) return 1 ;;
  esac
}
COOLIFY_DB_BACKUP_AUTHORITY=vps-backup
COOLIFY_DB_NATIVE_SUPPLEMENTAL=false
if coolify_policy_audit; then
  echo 'Redis without explicit persistence policy unexpectedly passed' >&2
  exit 1
fi

printf 'Operational integrations regression PASS\n'
