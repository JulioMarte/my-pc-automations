# v1.4.2 operational integrations: Contabo provider snapshots + Coolify backup-policy reconciler.
# This block is injected into the single-file candidate at build time.

readonly CONTABO_CONFIG_FILE="${CONFIG_DIR}/contabo.conf"
readonly CONTABO_CREDENTIALS_FILE="${CONFIG_DIR}/contabo.credentials"
readonly CONTABO_SNAPSHOT_SERVICE="/etc/systemd/system/vps-backup-provider-snapshot.service"
readonly CONTABO_SNAPSHOT_TIMER="/etc/systemd/system/vps-backup-provider-snapshot.timer"
readonly COOLIFY_POLICY_FILE="${CONFIG_DIR}/coolify-policy.conf"

# Provider snapshots are recovery accelerators, never authoritative application
# or database backups. Create/verify happens before pruning old snapshots.
CONTABO_ENABLED="false"
CONTABO_INSTANCE_ID=""
CONTABO_SNAPSHOT_KEEP="3"
CONTABO_SNAPSHOT_PREFIX="vps-dr"
CONTABO_SNAPSHOT_ONCALENDAR="Sun *-*-* 06:30:00"
CONTABO_SNAPSHOT_MAX_AGE_HOURS="192"
CONTABO_SNAPSHOT_REQUIRED_FOR_DR="false"
CONTABO_REQUIRE_RECENT_RESTIC="true"
CONTABO_AUTH_URL="https://auth.contabo.com/auth/realms/contabo/protocol/openid-connect/token"
CONTABO_API_BASE_URL="https://api.contabo.com/v1"
CONTABO_CLIENT_ID=""
CONTABO_CLIENT_SECRET=""
CONTABO_API_USER=""
CONTABO_API_PASSWORD=""

# Automatic DR authority deliberately remains the engine-aware dumps + Restic
# path already proven by destructive CI. Coolify-native database backups can be
# scheduled as a short-retention supplemental copy. Selecting coolify-native as
# authority is allowed for auditing, but cannot claim AUTO_DR_READY in v1.4
# until a programmatic restore adapter for those artifacts passes destructive CI.
COOLIFY_POLICY_MODE="audit"                    # off|audit|enforce
COOLIFY_DB_BACKUP_AUTHORITY="vps-backup"      # vps-backup|coolify-native
COOLIFY_DB_NATIVE_SUPPLEMENTAL="false"
COOLIFY_STORAGE_AUTHORITY="restic"            # restic|coolify-native-supplemental
COOLIFY_POLICY_REQUIRE_S3="true"
COOLIFY_POLICY_S3_STORAGE_UUID=""
COOLIFY_DB_FREQUENCY=""
COOLIFY_DB_RETENTION_S3=""
COOLIFY_DB_RETENTION_LOCAL="1"
COOLIFY_DB_BACKUP_TIMEOUT="3600"
COOLIFY_STORAGE_FREQUENCY=""
COOLIFY_STORAGE_RETENTION_S3="7"
COOLIFY_STORAGE_RETENTION_LOCAL="1"
COOLIFY_STORAGE_STOP_DURING_BACKUP="false"
COOLIFY_POLICY_FAIL_ON_UNSUPPORTED_DB="true"

ops_source_optional_root_file() {
  local file="$1"
  [[ -f "$file" ]] || return 1
  secure_file_or_die "$file"
  # shellcheck disable=SC1090
  source "$file"
}

load_contabo_config() {
  CONTABO_ENABLED="false"
  CONTABO_INSTANCE_ID=""
  CONTABO_SNAPSHOT_KEEP="3"
  CONTABO_SNAPSHOT_PREFIX="vps-dr"
  CONTABO_SNAPSHOT_ONCALENDAR="Sun *-*-* 06:30:00"
  CONTABO_SNAPSHOT_MAX_AGE_HOURS="192"
  CONTABO_SNAPSHOT_REQUIRED_FOR_DR="false"
  CONTABO_REQUIRE_RECENT_RESTIC="true"
  CONTABO_AUTH_URL="https://auth.contabo.com/auth/realms/contabo/protocol/openid-connect/token"
  CONTABO_API_BASE_URL="https://api.contabo.com/v1"
  CONTABO_CLIENT_ID=""
  CONTABO_CLIENT_SECRET=""
  CONTABO_API_USER=""
  CONTABO_API_PASSWORD=""
  ops_source_optional_root_file "$CONTABO_CONFIG_FILE" || true
  ops_source_optional_root_file "$CONTABO_CREDENTIALS_FILE" || true
}

load_coolify_policy_config() {
  COOLIFY_POLICY_MODE="audit"
  COOLIFY_DB_BACKUP_AUTHORITY="vps-backup"
  COOLIFY_DB_NATIVE_SUPPLEMENTAL="false"
  COOLIFY_STORAGE_AUTHORITY="restic"
  COOLIFY_POLICY_REQUIRE_S3="true"
  COOLIFY_POLICY_S3_STORAGE_UUID=""
  COOLIFY_DB_FREQUENCY=""
  COOLIFY_DB_RETENTION_S3=""
  COOLIFY_DB_RETENTION_LOCAL="1"
  COOLIFY_DB_BACKUP_TIMEOUT="3600"
  COOLIFY_STORAGE_FREQUENCY=""
  COOLIFY_STORAGE_RETENTION_S3="7"
  COOLIFY_STORAGE_RETENTION_LOCAL="1"
  COOLIFY_STORAGE_STOP_DURING_BACKUP="false"
  COOLIFY_POLICY_FAIL_ON_UNSUPPORTED_DB="true"
  ops_source_optional_root_file "$COOLIFY_POLICY_FILE" || true
}

ops_request_id() {
  if [[ -r /proc/sys/kernel/random/uuid ]]; then
    tr '[:lower:]' '[:upper:]' < /proc/sys/kernel/random/uuid
  elif command_exists uuidgen; then
    uuidgen | tr '[:lower:]' '[:upper:]'
  else
    printf '%08x-%04x-4%03x-8%03x-%012x\n' "$RANDOM" "$RANDOM" "$RANDOM" "$RANDOM" "$RANDOM$RANDOM"
  fi
}

contabo_validate_config() {
  [[ "$CONTABO_INSTANCE_ID" =~ ^[0-9]+$ ]] || { err "CONTABO_INSTANCE_ID debe ser numérico."; return 1; }
  [[ "$CONTABO_SNAPSHOT_KEEP" =~ ^[1-9][0-9]*$ ]] || { err "CONTABO_SNAPSHOT_KEEP debe ser >=1."; return 1; }
  [[ "$CONTABO_SNAPSHOT_PREFIX" =~ ^[A-Za-z0-9_-]{1,20}$ ]] || { err "CONTABO_SNAPSHOT_PREFIX debe tener 1-20 caracteres [A-Za-z0-9_-]."; return 1; }
  [[ "$CONTABO_AUTH_URL" == https://* || "$CONTABO_AUTH_URL" == http://127.0.0.1:* || "$CONTABO_AUTH_URL" == http://localhost:* ]] || { err "CONTABO_AUTH_URL debe usar HTTPS (excepto mock localhost)."; return 1; }
  [[ "$CONTABO_API_BASE_URL" == https://* || "$CONTABO_API_BASE_URL" == http://127.0.0.1:* || "$CONTABO_API_BASE_URL" == http://localhost:* ]] || { err "CONTABO_API_BASE_URL debe usar HTTPS (excepto mock localhost)."; return 1; }
  [[ -n "$CONTABO_CLIENT_ID" && -n "$CONTABO_CLIENT_SECRET" && -n "$CONTABO_API_USER" && -n "$CONTABO_API_PASSWORD" ]] || { err "Faltan credenciales API de Contabo."; return 1; }
  if command_exists systemd-analyze; then
    systemd-analyze calendar "$CONTABO_SNAPSHOT_ONCALENDAR" >/dev/null 2>&1 || { err "OnCalendar Contabo inválido: $CONTABO_SNAPSHOT_ONCALENDAR"; return 1; }
  fi
}

contabo_access_token() {
  local form tmp response token
  tmp=$(mktemp "${TMP_DIR}/contabo-auth.XXXXXX")
  chmod 0600 "$tmp"
  form=$(printf 'client_id=%s&client_secret=%s&username=%s&password=%s&grant_type=password' \
    "$(jq -rn --arg v "$CONTABO_CLIENT_ID" '$v|@uri')" \
    "$(jq -rn --arg v "$CONTABO_CLIENT_SECRET" '$v|@uri')" \
    "$(jq -rn --arg v "$CONTABO_API_USER" '$v|@uri')" \
    "$(jq -rn --arg v "$CONTABO_API_PASSWORD" '$v|@uri')")
  printf '%s' "$form" > "$tmp"
  if ! response=$(curl -fsS --retry 2 --retry-all-errors --connect-timeout 10 --max-time 60 \
      -H 'Content-Type: application/x-www-form-urlencoded' --data-binary "@$tmp" "$CONTABO_AUTH_URL"); then
    rm -f "$tmp"
    return 1
  fi
  rm -f "$tmp"
  token=$(printf '%s' "$response" | jq -er '.access_token // empty' 2>/dev/null) || return 1
  [[ -n "$token" ]] || return 1
  printf '%s' "$token"
}

contabo_api_request() {
  local method="$1" path="$2" body="${3:-}" token request_id cfg tmp response rc=0
  token=$(contabo_access_token) || { err "No pude autenticar con Contabo API."; return 1; }
  request_id=$(ops_request_id)
  cfg=$(mktemp "${TMP_DIR}/contabo-curl.XXXXXX")
  chmod 0600 "$cfg"
  [[ "$token" != *$'\n'* && "$token" != *'"'* ]] || { rm -f "$cfg"; err "Token Contabo contiene caracteres inesperados."; return 1; }
  {
    printf 'header = "Authorization: Bearer %s"\n' "$token"
    printf 'header = "x-request-id: %s"\n' "$request_id"
    printf 'header = "Accept: application/json"\n'
    printf 'connect-timeout = 10\nmax-time = 120\nfail-with-body\nsilent\nshow-error\n'
  } > "$cfg"
  if [[ -n "$body" ]]; then
    tmp=$(mktemp "${TMP_DIR}/contabo-body.XXXXXX.json")
    chmod 0600 "$tmp"
    printf '%s' "$body" > "$tmp"
    response=$(curl --config "$cfg" -X "$method" -H 'Content-Type: application/json' --data-binary "@$tmp" "${CONTABO_API_BASE_URL%/}${path}") || rc=$?
    rm -f "$tmp"
  else
    response=$(curl --config "$cfg" -X "$method" "${CONTABO_API_BASE_URL%/}${path}") || rc=$?
  fi
  rm -f "$cfg"
  (( rc == 0 )) || return "$rc"
  printf '%s' "$response"
}

contabo_relevant_snapshots_json() {
  local json
  json=$(contabo_api_request GET "/compute/instances/${CONTABO_INSTANCE_ID}/snapshots") || return 1
  printf '%s' "$json" | jq -c --arg p "$CONTABO_SNAPSHOT_PREFIX" '[.data[]? | select((.name // "") | startswith($p))] | sort_by(.createdDate // "")'
}

contabo_snapshot_preflight() {
  is_true "$CONTABO_REQUIRE_RECENT_RESTIC" || return 0
  repo_exists || { err "Contabo snapshot bloqueado: Restic/S3 no es accesible."; return 1; }
  local sid stime age
  sid=$(latest_system_snapshot_id || true)
  [[ -n "$sid" ]] || { err "Contabo snapshot bloqueado: no existe snapshot system de Restic."; return 1; }
  stime=$(snapshot_time_by_id "$sid")
  age=$(age_hours_from_iso "$stime")
  if (( age > ${MAX_BACKUP_AGE_HOURS:-36} )); then
    err "Contabo snapshot bloqueado: último Restic system tiene ${age}h (> ${MAX_BACKUP_AGE_HOURS:-36}h)."
    return 1
  fi
  ok "Pre-snapshot: Restic system ${sid:0:12} age=${age}h."
}

contabo_snapshot_list() {
  load_contabo_config
  contabo_validate_config || return 1
  local json
  json=$(contabo_relevant_snapshots_json) || return 1
  printf '%-24s %-31s %-25s %s\n' "SNAPSHOT" "NAME" "CREATED" "AUTO-DELETE"
  printf '%s' "$json" | jq -r '.[] | [(.snapshotId//"?"),(.name//"?"),(.createdDate//"?"),(.autoDeleteDate//"-")] | @tsv' | \
    while IFS=$'\t' read -r sid name created autodel; do printf '%-24s %-31s %-25s %s\n' "$sid" "$name" "$created" "$autodel"; done
}

contabo_snapshot_prune() {
  local dry_run="false"
  [[ "${1:-}" == "--dry-run" ]] && dry_run="true"
  load_contabo_config
  contabo_validate_config || return 1
  local json count remove sid name
  json=$(contabo_relevant_snapshots_json) || return 1
  count=$(printf '%s' "$json" | jq 'length')
  (( count > CONTABO_SNAPSHOT_KEEP )) || { info "Contabo snapshots: $count; keep=$CONTABO_SNAPSHOT_KEEP, nada que podar."; return 0; }
  remove=$((count - CONTABO_SNAPSHOT_KEEP))
  while IFS=$'\t' read -r sid name; do
    [[ -n "$sid" ]] || continue
    if is_true "$dry_run"; then
      printf 'DRY-RUN delete %s (%s)\n' "$sid" "$name"
    else
      info "Eliminando snapshot Contabo antiguo gestionado: $sid ($name)"
      contabo_api_request DELETE "/compute/instances/${CONTABO_INSTANCE_ID}/snapshots/${sid}" >/dev/null || return 1
    fi
  done < <(printf '%s' "$json" | jq -r --argjson n "$remove" '.[0:$n][] | [(.snapshotId//""),(.name//"")] | @tsv')
}

contabo_snapshot_create() {
  local dry_run="false" do_prune="false" arg
  for arg in "$@"; do
    case "$arg" in
      --dry-run) dry_run="true" ;;
      --prune) do_prune="true" ;;
      *) die "Opción snapshot Contabo desconocida: $arg" ;;
    esac
  done
  load_contabo_config
  is_true "$CONTABO_ENABLED" || die "Contabo snapshots no están habilitados. Ejecuta: $APP_NAME provider contabo configure"
  contabo_validate_config || return 1
  contabo_snapshot_preflight || return 1
  local ts name desc body response sid verify
  ts=$(date -u +%Y%m%d-%H%M)
  name="${CONTABO_SNAPSHOT_PREFIX}-${ts}"
  name="${name:0:30}"
  desc="vps-backup ${BACKUP_ID}; Restic system $(latest_system_snapshot_id | cut -c1-12)"
  body=$(jq -cn --arg name "$name" --arg description "$desc" '{name:$name,description:$description}')
  if is_true "$dry_run"; then
    printf 'DRY-RUN Contabo POST instance=%s name=%s keep=%s\n' "$CONTABO_INSTANCE_ID" "$name" "$CONTABO_SNAPSHOT_KEEP"
    return 0
  fi
  info "Creando snapshot Contabo: $name"
  response=$(contabo_api_request POST "/compute/instances/${CONTABO_INSTANCE_ID}/snapshots" "$body") || return 1
  sid=$(printf '%s' "$response" | jq -er '.data[0].snapshotId // empty' 2>/dev/null) || { err "Contabo no devolvió snapshotId."; return 1; }
  verify=$(contabo_relevant_snapshots_json) || return 1
  printf '%s' "$verify" | jq -e --arg sid "$sid" 'any(.snapshotId == $sid)' >/dev/null || { err "Snapshot $sid fue creado pero no aparece al verificar la lista."; return 1; }
  install -d -m 0700 "$STATE_DIR"
  printf '%s\n' "$sid" > "${STATE_DIR}/last_contabo_snapshot_id"
  printf '%s\n' "$(now)" > "${STATE_DIR}/last_contabo_snapshot_time"
  chmod 0600 "${STATE_DIR}/last_contabo_snapshot_id" "${STATE_DIR}/last_contabo_snapshot_time"
  ok "Snapshot Contabo verificado: $sid"
  is_true "$do_prune" && contabo_snapshot_prune
}

contabo_snapshot_status() {
  load_contabo_config
  if ! is_true "$CONTABO_ENABLED"; then
    printf 'Contabo snapshots: disabled\n'
    return 0
  fi
  contabo_validate_config || return 1
  local json count created age=999999
  json=$(contabo_relevant_snapshots_json) || return 1
  count=$(printf '%s' "$json" | jq 'length')
  created=$(printf '%s' "$json" | jq -r 'last?.createdDate // empty')
  if [[ -n "$created" ]]; then age=$(age_hours_from_iso "$created"); fi
  printf 'Contabo snapshots: enabled count=%s latest_age=%sh keep=%s required_for_dr=%s\n' "$count" "$age" "$CONTABO_SNAPSHOT_KEEP" "$CONTABO_SNAPSHOT_REQUIRED_FOR_DR"
  if (( count == 0 )); then return 1; fi
  (( age <= CONTABO_SNAPSHOT_MAX_AGE_HOURS ))
}

write_contabo_timer() {
  load_contabo_config
  contabo_validate_config || return 1
  command_exists systemctl || die "systemd requerido para programar snapshots Contabo."
  if command_exists systemd-analyze; then systemd-analyze calendar "$CONTABO_SNAPSHOT_ONCALENDAR" >/dev/null || die "OnCalendar inválido."; fi
  cat > "$CONTABO_SNAPSHOT_SERVICE" <<EOF_SERVICE
[Unit]
Description=vps-backup Contabo provider snapshot
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=${INSTALL_PATH} provider contabo snapshot --prune
TimeoutStartSec=2h
EOF_SERVICE
  cat > "$CONTABO_SNAPSHOT_TIMER" <<EOF_TIMER
[Unit]
Description=Schedule Contabo provider snapshots

[Timer]
OnCalendar=${CONTABO_SNAPSHOT_ONCALENDAR}
Persistent=true
RandomizedDelaySec=30m
Unit=vps-backup-provider-snapshot.service

[Install]
WantedBy=timers.target
EOF_TIMER
  chmod 0644 "$CONTABO_SNAPSHOT_SERVICE" "$CONTABO_SNAPSHOT_TIMER"
  systemctl daemon-reload
  systemctl enable --now vps-backup-provider-snapshot.timer
  ok "Timer Contabo habilitado: $CONTABO_SNAPSHOT_ONCALENDAR"
}

remove_contabo_timer() {
  command_exists systemctl || return 0
  systemctl disable --now vps-backup-provider-snapshot.timer >/dev/null 2>&1 || true
  rm -f "$CONTABO_SNAPSHOT_SERVICE" "$CONTABO_SNAPSHOT_TIMER"
  systemctl daemon-reload
}

configure_contabo_interactive() {
  require_root
  load_config
  install -d -m 0700 "$CONFIG_DIR"
  printf '\n%sContabo provider snapshots%s\n' "$C_BOLD" "$C_RESET"
  warn "Recomendación: usa un API user/role dedicado con acceso solo a snapshots de esta instancia."
  local instance prefix keep schedule client_id client_secret api_user api_password tmp tmpc choice
  instance=$(prompt_default "Contabo instance ID" "${CONTABO_INSTANCE_ID:-}")
  prefix=$(prompt_default "Prefijo de snapshots (máx. 20)" "vps-dr")
  keep=$(prompt_default "Snapshots gestionados a conservar" "3")
  printf 'Frecuencia sugerida: 1) weekly (recomendado)  2) daily  3) custom systemd OnCalendar\n'
  choice=$(prompt_default "Opción" "1")
  case "$choice" in
    1) schedule="Sun *-*-* 06:30:00" ;;
    2) schedule="*-*-* 06:30:00" ;;
    3) schedule=$(prompt_default "OnCalendar" "Sun *-*-* 06:30:00") ;;
    *) die "Opción inválida." ;;
  esac
  client_id=$(prompt_secret "Contabo Client ID")
  client_secret=$(prompt_secret "Contabo Client Secret")
  api_user=$(prompt_default "Contabo API user/email" "")
  api_password=$(prompt_secret "Contabo API password")
  tmp=$(atomic_begin "$CONTABO_CONFIG_FILE")
  write_kv "$tmp" CONTABO_ENABLED true
  write_kv "$tmp" CONTABO_INSTANCE_ID "$instance"
  write_kv "$tmp" CONTABO_SNAPSHOT_KEEP "$keep"
  write_kv "$tmp" CONTABO_SNAPSHOT_PREFIX "$prefix"
  write_kv "$tmp" CONTABO_SNAPSHOT_ONCALENDAR "$schedule"
  write_kv "$tmp" CONTABO_SNAPSHOT_MAX_AGE_HOURS 192
  write_kv "$tmp" CONTABO_SNAPSHOT_REQUIRED_FOR_DR false
  write_kv "$tmp" CONTABO_REQUIRE_RECENT_RESTIC true
  atomic_finish "$tmp" "$CONTABO_CONFIG_FILE" 0600
  tmpc=$(atomic_begin "$CONTABO_CREDENTIALS_FILE")
  write_kv "$tmpc" CONTABO_CLIENT_ID "$client_id"
  write_kv "$tmpc" CONTABO_CLIENT_SECRET "$client_secret"
  write_kv "$tmpc" CONTABO_API_USER "$api_user"
  write_kv "$tmpc" CONTABO_API_PASSWORD "$api_password"
  atomic_finish "$tmpc" "$CONTABO_CREDENTIALS_FILE" 0600
  load_contabo_config
  contabo_validate_config || return 1
  write_contabo_timer
  ok "Contabo snapshot adapter configurado. Ejecuta '$APP_NAME provider contabo snapshot --dry-run' primero."
}

cmd_provider() {
  require_root
  load_config
  local provider="${1:-}" action="${2:-status}"
  [[ "$provider" == "contabo" ]] || die "Provider soportado en v1.4: contabo"
  shift 2 2>/dev/null || true
  case "$action" in
    configure) configure_contabo_interactive ;;
    snapshot|create) contabo_snapshot_create "$@" ;;
    list) contabo_snapshot_list ;;
    prune) contabo_snapshot_prune "$@" ;;
    status) contabo_snapshot_status ;;
    install-timer) write_contabo_timer ;;
    remove-timer) remove_contabo_timer ;;
    *) die "Acción provider desconocida: $action" ;;
  esac
}

coolify_policy_api_base() {
  local base="${COOLIFY_API_URL:-http://127.0.0.1:8000}"
  base="${base%/}"
  if [[ "$base" == */api/v1 ]]; then printf '%s' "$base"; else printf '%s/api/v1' "$base"; fi
}

coolify_policy_api() {
  local method="$1" path="$2" body="${3:-}" cfg tmp response rc=0 token="${COOLIFY_API_TOKEN:-}"
  [[ -n "$token" ]] || { err "COOLIFY_API_TOKEN requerido para coolify-policy."; return 1; }
  [[ "$token" != *$'\n'* && "$token" != *'"'* ]] || { err "COOLIFY_API_TOKEN contiene caracteres inesperados."; return 1; }
  cfg=$(mktemp "${TMP_DIR}/coolify-curl.XXXXXX")
  chmod 0600 "$cfg"
  {
    printf 'header = "Authorization: Bearer %s"\n' "$token"
    printf 'header = "Accept: application/json"\n'
    printf 'connect-timeout = 10\nmax-time = 120\nfail-with-body\nsilent\nshow-error\n'
  } > "$cfg"
  if [[ -n "$body" ]]; then
    tmp=$(mktemp "${TMP_DIR}/coolify-body.XXXXXX.json")
    chmod 0600 "$tmp"; printf '%s' "$body" > "$tmp"
    response=$(curl --config "$cfg" -X "$method" -H 'Content-Type: application/json' --data-binary "@$tmp" "$(coolify_policy_api_base)${path}") || rc=$?
    rm -f "$tmp"
  else
    response=$(curl --config "$cfg" -X "$method" "$(coolify_policy_api_base)${path}") || rc=$?
  fi
  rm -f "$cfg"
  (( rc == 0 )) || return "$rc"
  printf '%s' "$response"
}

coolify_json_array() {
  jq -c 'if type=="array" then . elif ((.data? | type)=="array") then .data elif ((.resources? | type)=="array") then .resources else [] end'
}

coolify_profile_defaults() {
  local profile="${BACKUP_PROFILE:-balanced}"
  case "$profile" in
    economy)
      : "${COOLIFY_DB_FREQUENCY:=0 */6 * * *}"; : "${COOLIFY_DB_RETENTION_S3:=28}"; : "${COOLIFY_STORAGE_FREQUENCY:=0 3 * * *}" ;;
    balanced)
      : "${COOLIFY_DB_FREQUENCY:=0 * * * *}"; : "${COOLIFY_DB_RETENTION_S3:=168}"; : "${COOLIFY_STORAGE_FREQUENCY:=0 */6 * * *}" ;;
    critical)
      : "${COOLIFY_DB_FREQUENCY:=0 * * * *}"; : "${COOLIFY_DB_RETENTION_S3:=336}"; : "${COOLIFY_STORAGE_FREQUENCY:=0 */3 * * *}" ;;
    custom)
      [[ -n "$COOLIFY_DB_FREQUENCY" ]] || { err "Perfil custom requiere COOLIFY_DB_FREQUENCY."; return 1; }
      : "${COOLIFY_DB_RETENTION_S3:=168}"; : "${COOLIFY_STORAGE_FREQUENCY:=0 */6 * * *}" ;;
    *) err "BACKUP_PROFILE desconocido para Coolify: $profile"; return 1 ;;
  esac
}

coolify_db_engine() {
  local obj="$1" raw
  raw=$(printf '%s' "$obj" | jq -r '[.type?,.database_type?,.databaseType?,.image?,.docker_image?,.name?] | map(select(.!=null)) | join(" ")' | tr '[:upper:]' '[:lower:]')
  case "$raw" in
    *postgres*) printf 'postgresql' ;;
    *mariadb*) printf 'mariadb' ;;
    *mysql*) printf 'mysql' ;;
    *mongo*) printf 'mongodb' ;;
    *clickhouse*) printf 'clickhouse' ;;
    *dragonfly*) printf 'dragonfly' ;;
    *keydb*) printf 'keydb' ;;
    *redis*) printf 'redis' ;;
    *) printf 'unknown' ;;
  esac
}

coolify_backup_configs_array() {
  local json="$1"
  printf '%s' "$json" | jq -c 'if type=="array" then . elif ((.data? | type)=="array") then .data elif ((.backups? | type)=="array") then .backups else [] end'
}

coolify_backup_compliant_count() {
  local configs="$1"
  printf '%s' "$configs" | jq --arg s3 "$COOLIFY_POLICY_S3_STORAGE_UUID" --argjson req "$(is_true "$COOLIFY_POLICY_REQUIRE_S3" && echo true || echo false)" \
    '[.[] | select((.enabled // true)==true) | select(($req|not) or ((.save_s3 // false)==true and ($s3=="" or (.s3_storage_uuid // "")==$s3)))] | length'
}

coolify_db_policy_body() {
  jq -cn \
    --arg frequency "$COOLIFY_DB_FREQUENCY" \
    --arg s3 "$COOLIFY_POLICY_S3_STORAGE_UUID" \
    --argjson save_s3 "$(is_true "$COOLIFY_POLICY_REQUIRE_S3" && echo true || echo false)" \
    --argjson rs3 "$COOLIFY_DB_RETENTION_S3" \
    --argjson rlocal "$COOLIFY_DB_RETENTION_LOCAL" \
    --argjson timeout "$COOLIFY_DB_BACKUP_TIMEOUT" \
    '{frequency:$frequency,enabled:true,save_s3:$save_s3,dump_all:true,database_backup_retention_amount_locally:$rlocal,database_backup_retention_amount_s3:$rs3,timeout:$timeout} + (if ($s3|length)>0 then {s3_storage_uuid:$s3} else {} end)'
}

coolify_audit_databases() {
  local mode="${1:-audit}" dbs obj uuid name engine backups configs count failures=0 body backup_uuid
  dbs=$(coolify_policy_api GET /databases) || return 1
  dbs=$(printf '%s' "$dbs" | coolify_json_array)
  while IFS= read -r obj; do
    [[ -n "$obj" ]] || continue
    uuid=$(printf '%s' "$obj" | jq -r '.uuid // empty')
    name=$(printf '%s' "$obj" | jq -r '.name // .uuid // "unnamed"')
    [[ -n "$uuid" ]] || { err "Coolify database sin UUID; no puedo auditarla."; failures=$((failures+1)); continue; }
    engine=$(coolify_db_engine "$obj")
    case "$engine" in
      postgresql|mysql|mariadb|mongodb|clickhouse)
        if [[ "$COOLIFY_DB_BACKUP_AUTHORITY" == "vps-backup" ]] && ! is_true "$COOLIFY_DB_NATIVE_SUPPLEMENTAL"; then
          info "Coolify DB $name ($engine): authority=vps-backup; restore automático cubierto por workload policy local."
          continue
        fi
        if [[ "$COOLIFY_DB_BACKUP_AUTHORITY" != "vps-backup" && "$COOLIFY_DB_BACKUP_AUTHORITY" != "coolify-native" ]]; then
          err "COOLIFY_DB_BACKUP_AUTHORITY inválido: $COOLIFY_DB_BACKUP_AUTHORITY"
          failures=$((failures+1)); continue
        fi
        backups=$(coolify_policy_api GET "/databases/${uuid}/backups") || {
          if [[ "$COOLIFY_DB_BACKUP_AUTHORITY" == "coolify-native" ]]; then
            err "No pude leer backups autoritativos de Coolify DB $name."; failures=$((failures+1))
          else
            warn "No pude leer backup supplemental de Coolify DB $name; el restore automático local sigue siendo autoritativo."
          fi
          continue
        }
        configs=$(coolify_backup_configs_array "$backups")
        count=$(coolify_backup_compliant_count "$configs")
        if (( count > 0 )); then
          if [[ "$COOLIFY_DB_BACKUP_AUTHORITY" == "coolify-native" ]]; then
            warn "Coolify DB $name ($engine): backup nativo existe, pero v1.4 NO lo considera AUTO_DR_READY hasta que una restauración programática de ese artefacto pase CI."
          else
            ok "Coolify DB $name ($engine): copia supplemental S3 compliant; authority=vps-backup."
          fi
          continue
        fi
        if [[ "$mode" == "enforce" ]]; then
          body=$(coolify_db_policy_body)
          local total
          total=$(printf '%s' "$configs" | jq 'length')
          if (( total == 0 )); then
            coolify_policy_api POST "/databases/${uuid}/backups" "$body" >/dev/null || { err "No pude crear backup schedule para $name."; failures=$((failures+1)); continue; }
            ok "Coolify DB $name: schedule creado."
          elif (( total == 1 )); then
            backup_uuid=$(printf '%s' "$configs" | jq -r '.[0].uuid // .[0].id // empty')
            if [[ -z "$backup_uuid" ]]; then
              err "Coolify DB $name tiene un schedule pero no expone UUID; no lo mutaré a ciegas."
              failures=$((failures+1)); continue
            fi
            coolify_policy_api PATCH "/databases/${uuid}/backups/${backup_uuid}" "$body" >/dev/null || { err "No pude reconciliar backup schedule para $name."; failures=$((failures+1)); continue; }
            ok "Coolify DB $name: schedule reconciliado."
          else
            err "Coolify DB $name tiene $total schedules; enforce no elegirá uno arbitrariamente."
            failures=$((failures+1)); continue
          fi
          backups=$(coolify_policy_api GET "/databases/${uuid}/backups") || { failures=$((failures+1)); continue; }
          configs=$(coolify_backup_configs_array "$backups")
          count=$(coolify_backup_compliant_count "$configs")
          (( count > 0 )) || { err "Coolify DB $name sigue sin schedule compliant después de enforce."; failures=$((failures+1)); }
        else
          if [[ "$COOLIFY_DB_BACKUP_AUTHORITY" == "coolify-native" ]]; then
            err "Coolify DB $name ($engine) no tiene backup nativo S3 compliant."
            failures=$((failures+1))
          else
            warn "Coolify DB $name ($engine) no tiene copia supplemental Coolify-native; authority=vps-backup sigue siendo válida."
          fi
        fi
        ;;
      redis|dragonfly|keydb)
        if is_true "$COOLIFY_POLICY_FAIL_ON_UNSUPPORTED_DB"; then
          err "Coolify DB $name ($engine): Coolify no soporta scheduled DB backup para este engine; clasifica persistencia RDB/AOF/hook explícitamente."
          failures=$((failures+1))
        else
          warn "Coolify DB $name ($engine) requiere política externa RDB/AOF/hook."
        fi
        ;;
      *)
        err "Coolify DB $name: engine desconocido; fail-closed."
        failures=$((failures+1)) ;;
    esac
  done < <(printf '%s' "$dbs" | jq -c '.[]')
  [[ "$failures" -eq 0 ]]
}

coolify_storage_policy_body() {
  jq -cn \
    --arg frequency "$COOLIFY_STORAGE_FREQUENCY" \
    --arg s3 "$COOLIFY_POLICY_S3_STORAGE_UUID" \
    --argjson save_s3 true \
    --argjson stop "$(is_true "$COOLIFY_STORAGE_STOP_DURING_BACKUP" && echo true || echo false)" \
    --argjson rs3 "$COOLIFY_STORAGE_RETENTION_S3" \
    --argjson rlocal "$COOLIFY_STORAGE_RETENTION_LOCAL" \
    '{frequency:$frequency,enabled:true,save_s3:$save_s3,disable_local_backup:false,stop_during_backup:$stop,s3_storage_uuid:$s3,retention_amount_locally:$rlocal,retention_amount_s3:$rs3,timeout:3600}'
}

coolify_enforce_native_storage_supplement() {
  [[ "$COOLIFY_STORAGE_AUTHORITY" == "coolify-native-supplemental" ]] || return 0
  [[ -n "$COOLIFY_POLICY_S3_STORAGE_UUID" ]] || { err "Storage Coolify native requiere COOLIFY_POLICY_S3_STORAGE_UUID."; return 1; }
  local kind endpoint resources obj uuid name storages st suuid body failures=0
  body=$(coolify_storage_policy_body)
  for kind in applications services; do
    endpoint="/$kind"
    resources=$(coolify_policy_api GET "$endpoint") || { failures=$((failures+1)); continue; }
    resources=$(printf '%s' "$resources" | coolify_json_array)
    while IFS= read -r obj; do
      [[ -n "$obj" ]] || continue
      uuid=$(printf '%s' "$obj" | jq -r '.uuid // empty'); name=$(printf '%s' "$obj" | jq -r '.name // .uuid // "unnamed"')
      [[ -n "$uuid" ]] || { failures=$((failures+1)); continue; }
      storages=$(coolify_policy_api GET "/${kind}/${uuid}/storages") || { err "No pude listar storages de $kind/$name"; failures=$((failures+1)); continue; }
      while IFS= read -r st; do
        [[ -n "$st" ]] || continue
        suuid=$(printf '%s' "$st" | jq -r '.uuid // .id // empty')
        [[ -n "$suuid" ]] || { warn "$kind/$name contiene storage sin UUID; omitido."; continue; }
        coolify_policy_api PUT "/${kind}/${uuid}/storages/${suuid}/backups" "$body" >/dev/null || { err "No pude configurar storage $kind/$name/$suuid"; failures=$((failures+1)); continue; }
        ok "Storage supplemental Coolify configurado: $kind/$name/$suuid"
      done < <(printf '%s' "$storages" | jq -c '(.persistent_storages // [])[]?, (.file_storages // [])[]?')
    done < <(printf '%s' "$resources" | jq -c '.[]')
  done
  warn "Coolify storage archives son suplementales: no reemplazan Restic ni una prueba de restore; Coolify no ofrece restore de estos archives desde el dashboard."
  [[ "$failures" -eq 0 ]]
}

coolify_policy_audit() {
  load_coolify_policy_config
  [[ "$COOLIFY_POLICY_MODE" != "off" ]] || { info "Coolify policy reconciler desactivado."; return 0; }
  detect_coolify || { info "Coolify no detectado; policy audit omitido."; return 0; }
  coolify_profile_defaults || return 1
  [[ -n "${COOLIFY_API_TOKEN:-}" ]] || { err "Coolify policy audit requiere COOLIFY_API_TOKEN."; return 1; }
  if is_true "$COOLIFY_POLICY_REQUIRE_S3" && { is_true "$COOLIFY_DB_NATIVE_SUPPLEMENTAL" || [[ "$COOLIFY_STORAGE_AUTHORITY" == "coolify-native-supplemental" ]] || [[ "$COOLIFY_DB_BACKUP_AUTHORITY" == "coolify-native" ]]; } && [[ -z "$COOLIFY_POLICY_S3_STORAGE_UUID" ]]; then
    err "Coolify policy supplemental/native requiere S3 pero COOLIFY_POLICY_S3_STORAGE_UUID está vacío."
    return 1
  fi
  local failures=0
  if [[ "$COOLIFY_DB_BACKUP_AUTHORITY" == "coolify-native" ]]; then
    err "authority=coolify-native no puede declarar AUTO_DR_READY en v1.4: no existe aún un restore API/adapter probado en CI. Usa vps-backup como autoridad y Coolify-native como supplemental."
    failures=$((failures+1))
  fi
  coolify_audit_databases audit || failures=$((failures+1))
  if [[ "$COOLIFY_STORAGE_AUTHORITY" == "restic" ]]; then
    validate_workload_protection || { err "Storage authority=restic pero workload policy local no está completa."; failures=$((failures+1)); }
  else
    warn "Storage authority Coolify-native se considera SUPLEMENTAL; Restic sigue siendo la ruta autoritativa de DR de archivos."
    validate_workload_protection || failures=$((failures+1))
  fi
  [[ "$failures" -eq 0 ]]
}

coolify_policy_enforce() {
  load_coolify_policy_config
  [[ "$COOLIFY_POLICY_MODE" == "enforce" ]] || die "COOLIFY_POLICY_MODE debe ser enforce para mutar Coolify."
  detect_coolify || die "Coolify no detectado."
  coolify_profile_defaults || return 1
  [[ -n "${COOLIFY_API_TOKEN:-}" ]] || die "COOLIFY_API_TOKEN requerido."
  if is_true "$COOLIFY_POLICY_REQUIRE_S3" && { is_true "$COOLIFY_DB_NATIVE_SUPPLEMENTAL" || [[ "$COOLIFY_STORAGE_AUTHORITY" == "coolify-native-supplemental" ]] || [[ "$COOLIFY_DB_BACKUP_AUTHORITY" == "coolify-native" ]]; } && [[ -z "$COOLIFY_POLICY_S3_STORAGE_UUID" ]]; then
    die "Falta COOLIFY_POLICY_S3_STORAGE_UUID para la copia nativa/supplemental solicitada."
  fi
  local failures=0
  coolify_audit_databases enforce || failures=$((failures+1))
  coolify_enforce_native_storage_supplement || failures=$((failures+1))
  (( failures == 0 )) || return 1
  coolify_policy_audit
}

configure_coolify_policy_interactive() {
  require_root
  load_config
  detect_coolify || die "Coolify no detectado."
  local mode s3uuid storage supplemental tmp
  printf '\n%sCoolify backup policy reconciler%s\n' "$C_BOLD" "$C_RESET"
  printf 'Restore automático probado: databases=vps-backup builtin; app/service files=Restic.\n'
  printf 'Coolify-native puede añadirse con retención corta como copia operacional supplemental.\n'
  mode=$(prompt_default "Modo (audit/enforce)" "audit")
  [[ "$mode" == "audit" || "$mode" == "enforce" ]] || die "Modo inválido."
  supplemental=$(prompt_default "¿Crear/auditar copia DB Coolify-native supplemental? (true/false)" "false")
  [[ "$supplemental" == "true" || "$supplemental" == "false" ]] || die "Valor supplemental inválido."
  s3uuid=""
  if is_true "$supplemental"; then s3uuid=$(prompt_default "Coolify S3 storage UUID" ""); fi
  printf 'Storage: 1) Restic authoritative (recomendado)  2) Restic + Coolify supplemental archive\n'
  storage=$(prompt_default "Opción" "1")
  case "$storage" in 1) storage="restic" ;; 2) storage="coolify-native-supplemental" ;; *) die "Opción inválida." ;; esac
  tmp=$(atomic_begin "$COOLIFY_POLICY_FILE")
  write_kv "$tmp" COOLIFY_POLICY_MODE "$mode"
  write_kv "$tmp" COOLIFY_DB_BACKUP_AUTHORITY vps-backup
  write_kv "$tmp" COOLIFY_DB_NATIVE_SUPPLEMENTAL "$supplemental"
  write_kv "$tmp" COOLIFY_STORAGE_AUTHORITY "$storage"
  write_kv "$tmp" COOLIFY_POLICY_REQUIRE_S3 true
  write_kv "$tmp" COOLIFY_POLICY_S3_STORAGE_UUID "$s3uuid"
  write_kv "$tmp" COOLIFY_DB_RETENTION_LOCAL 1
  write_kv "$tmp" COOLIFY_STORAGE_RETENTION_LOCAL 1
  write_kv "$tmp" COOLIFY_POLICY_FAIL_ON_UNSUPPORTED_DB true
  atomic_finish "$tmp" "$COOLIFY_POLICY_FILE" 0600
  ok "Coolify policy guardada. Ejecuta '$APP_NAME coolify-policy audit'."
}

cmd_coolify_policy() {
  require_root
  load_config
  local action="${1:-audit}"
  shift || true
  case "$action" in
    configure) configure_coolify_policy_interactive ;;
    audit) coolify_policy_audit ;;
    enforce) coolify_policy_enforce ;;
    *) die "Acción coolify-policy desconocida: $action" ;;
  esac
}

# Called from dr-plan. Provider snapshots are optional accelerators unless the
# operator explicitly marks them required. When a Coolify policy file exists,
# its audit becomes part of readiness because the operator opted into that
# protection contract.
dr_plan_ops_extension() {
  local _sid="${1:-}"
  DR_EXTENSION_FAILURES=0
  DR_EXTENSION_WARNINGS=0
  if [[ -f "$COOLIFY_POLICY_FILE" ]]; then
    if coolify_policy_audit; then
      ok "Coolify backup policy audit PASS (AUTO_DR authority=vps-backup/Restic)."
    else
      err "Coolify backup policy audit FAIL."
      DR_EXTENSION_FAILURES=$((DR_EXTENSION_FAILURES+1))
    fi
  fi
  if [[ -f "$CONTABO_CONFIG_FILE" ]]; then
    load_contabo_config
    if is_true "$CONTABO_ENABLED"; then
      if contabo_snapshot_status; then
        ok "Contabo provider snapshot freshness PASS."
      elif is_true "$CONTABO_SNAPSHOT_REQUIRED_FOR_DR"; then
        err "Contabo snapshot requerido por política y no está fresco/disponible."
        DR_EXTENSION_FAILURES=$((DR_EXTENSION_FAILURES+1))
      else
        warn "Contabo snapshot no está fresco/disponible; core DR S3/Restic sigue siendo válido."
        DR_EXTENSION_WARNINGS=$((DR_EXTENSION_WARNINGS+1))
      fi
    fi
  fi
}
