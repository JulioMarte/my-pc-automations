# shellcheck shell=bash
# v1.4.2 Contabo safety overlay.
#
# This file intentionally overrides only the Contabo functions whose semantics
# must be stricter than the original operational integration module. It is
# injected immediately after ops-integrations.sh by materialize-candidate.sh.
# Restic/S3 remains the authoritative DR path; provider snapshots are only a
# recovery accelerator.

CONTABO_SNAPSHOT_KEEP="1"
CONTABO_SNAPSHOT_SLOT_LIMIT="2"
CONTABO_SNAPSHOT_VERIFY_TIMEOUT_SECONDS="300"

load_contabo_config() {
  CONTABO_ENABLED="false"
  CONTABO_INSTANCE_ID=""
  CONTABO_SNAPSHOT_KEEP="1"
  CONTABO_SNAPSHOT_SLOT_LIMIT="2"
  CONTABO_SNAPSHOT_PREFIX="vps-dr"
  CONTABO_SNAPSHOT_ONCALENDAR="Sun *-*-* 06:30:00"
  CONTABO_SNAPSHOT_MAX_AGE_HOURS="192"
  CONTABO_SNAPSHOT_VERIFY_TIMEOUT_SECONDS="300"
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

contabo_validate_config() {
  [[ "$CONTABO_INSTANCE_ID" =~ ^[0-9]+$ ]] || { err "CONTABO_INSTANCE_ID debe ser numérico."; return 1; }
  [[ "$CONTABO_SNAPSHOT_KEEP" =~ ^[1-9][0-9]*$ ]] || { err "CONTABO_SNAPSHOT_KEEP debe ser >=1."; return 1; }
  [[ "$CONTABO_SNAPSHOT_SLOT_LIMIT" =~ ^[1-9][0-9]*$ ]] || { err "CONTABO_SNAPSHOT_SLOT_LIMIT debe ser >=1."; return 1; }
  (( CONTABO_SNAPSHOT_KEEP < CONTABO_SNAPSHOT_SLOT_LIMIT )) || {
    err "Rotación segura requiere KEEP < SLOT_LIMIT para reservar un slot. Si tu plan solo permite 1 snapshot, usa snapshots manuales y conserva S3/Restic como DR autoritativo."
    return 1
  }
  [[ "$CONTABO_SNAPSHOT_PREFIX" =~ ^[A-Za-z0-9_-]{1,16}$ ]] || {
    err "CONTABO_SNAPSHOT_PREFIX debe tener 1-16 caracteres [A-Za-z0-9_-] para conservar el timestamp dentro del límite de 30 caracteres."
    return 1
  }
  [[ "$CONTABO_SNAPSHOT_VERIFY_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] || {
    err "CONTABO_SNAPSHOT_VERIFY_TIMEOUT_SECONDS debe ser >0."
    return 1
  }
  [[ "$CONTABO_AUTH_URL" == https://* || "$CONTABO_AUTH_URL" == http://127.0.0.1:* || "$CONTABO_AUTH_URL" == http://localhost:* ]] || {
    err "CONTABO_AUTH_URL debe usar HTTPS (excepto mock localhost)."
    return 1
  }
  [[ "$CONTABO_API_BASE_URL" == https://* || "$CONTABO_API_BASE_URL" == http://127.0.0.1:* || "$CONTABO_API_BASE_URL" == http://localhost:* ]] || {
    err "CONTABO_API_BASE_URL debe usar HTTPS (excepto mock localhost)."
    return 1
  }
  [[ -n "$CONTABO_CLIENT_ID" && -n "$CONTABO_CLIENT_SECRET" && -n "$CONTABO_API_USER" && -n "$CONTABO_API_PASSWORD" ]] || {
    err "Faltan credenciales API de Contabo."
    return 1
  }
  if command_exists systemd-analyze; then
    systemd-analyze calendar "$CONTABO_SNAPSHOT_ONCALENDAR" >/dev/null 2>&1 || {
      err "OnCalendar Contabo inválido: $CONTABO_SNAPSHOT_ONCALENDAR"
      return 1
    }
  fi
}

# Return a normalized JSON array. We request the largest page used by this
# adapter and fail closed if the API says there are more items than returned;
# undercounting snapshots could otherwise make slot rotation destructive.
contabo_all_snapshots_json() {
  local json listed total
  json=$(contabo_api_request GET "/compute/instances/${CONTABO_INSTANCE_ID}/snapshots?size=100") || return 1
  listed=$(printf '%s' "$json" | jq -er '(.data // []) | length') || return 1
  total=$(printf '%s' "$json" | jq -er --argjson listed "$listed" '._pagination.totalElements // ._pagination.total // $listed') || return 1
  [[ "$total" =~ ^[0-9]+$ ]] || { err "Contabo devolvió metadata de paginación inválida."; return 1; }
  if (( total > listed )); then
    err "Contabo devolvió $listed de $total snapshots; no rotaré con inventario paginado incompleto."
    return 1
  fi
  printf '%s' "$json" | jq -c '[.data[]?] | sort_by(.createdDate // "")'
}

contabo_relevant_snapshots_json() {
  local json
  json=$(contabo_all_snapshots_json) || return 1
  printf '%s' "$json" | jq -c --arg p "$CONTABO_SNAPSHOT_PREFIX" '[.[]? | select((.name // "") | startswith($p))] | sort_by(.createdDate // "")'
}

contabo_snapshot_wait_visible() {
  local sid="$1" deadline response got
  deadline=$(( $(date +%s) + CONTABO_SNAPSHOT_VERIFY_TIMEOUT_SECONDS ))
  while (( $(date +%s) <= deadline )); do
    if response=$(contabo_api_request GET "/compute/instances/${CONTABO_INSTANCE_ID}/snapshots/${sid}" 2>/dev/null); then
      got=$(printf '%s' "$response" | jq -r '.data[0].snapshotId // .snapshotId // empty' 2>/dev/null || true)
      [[ "$got" == "$sid" ]] && return 0
    fi
    sleep 5
  done
  return 1
}

# Make room only by removing managed snapshots in excess of KEEP. Never remove
# a manual snapshot and never remove the final KEEP known-good snapshots merely
# to create a new one.
contabo_snapshot_ensure_free_slot() {
  local all total
  all=$(contabo_all_snapshots_json) || return 1
  total=$(printf '%s' "$all" | jq 'length')
  (( total < CONTABO_SNAPSHOT_SLOT_LIMIT )) && return 0

  contabo_snapshot_prune || return 1
  all=$(contabo_all_snapshots_json) || return 1
  total=$(printf '%s' "$all" | jq 'length')
  if (( total >= CONTABO_SNAPSHOT_SLOT_LIMIT )); then
    err "No hay slot libre para snapshot Contabo (usados=$total límite=$CONTABO_SNAPSHOT_SLOT_LIMIT). No borraré el último snapshot gestionado ni snapshots manuales para hacer espacio."
    return 1
  fi
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

  # Dry-run is strictly read-only. It models whether managed excess could free
  # a slot, but never calls DELETE or POST.
  if is_true "$dry_run"; then
    local dry_all dry_total dry_managed dry_removable dry_after
    dry_all=$(contabo_all_snapshots_json) || return 1
    dry_total=$(printf '%s' "$dry_all" | jq 'length')
    dry_managed=$(printf '%s' "$dry_all" | jq --arg p "$CONTABO_SNAPSHOT_PREFIX" '[.[] | select((.name // "") | startswith($p))] | length')
    dry_removable=$(( dry_managed > CONTABO_SNAPSHOT_KEEP ? dry_managed - CONTABO_SNAPSHOT_KEEP : 0 ))
    dry_after=$((dry_total - dry_removable))
    if (( dry_after >= CONTABO_SNAPSHOT_SLOT_LIMIT )); then
      err "DRY-RUN: no existe rotación segura; usados=$dry_total gestionados=$dry_managed keep=$CONTABO_SNAPSHOT_KEEP límite=$CONTABO_SNAPSHOT_SLOT_LIMIT."
      return 1
    fi
    printf 'DRY-RUN Contabo POST instance=%s keep=%s slots=%s removable_before_create=%s\n' \
      "$CONTABO_INSTANCE_ID" "$CONTABO_SNAPSHOT_KEEP" "$CONTABO_SNAPSHOT_SLOT_LIMIT" "$dry_removable"
    return 0
  fi

  contabo_snapshot_ensure_free_slot || return 1

  local ts name desc body response sid
  ts=$(date -u +%Y%m%d-%H%M)
  name="${CONTABO_SNAPSHOT_PREFIX}-${ts}"
  [[ ${#name} -le 30 ]] || { err "Nombre de snapshot Contabo excede 30 caracteres: $name"; return 1; }
  desc="vps-backup ${BACKUP_ID}; Restic system $(latest_system_snapshot_id | cut -c1-12)"
  body=$(jq -cn --arg name "$name" --arg description "$desc" '{name:$name,description:$description}')

  info "Creando snapshot Contabo: $name"
  response=$(contabo_api_request POST "/compute/instances/${CONTABO_INSTANCE_ID}/snapshots" "$body") || return 1
  sid=$(printf '%s' "$response" | jq -er '.data[0].snapshotId // empty' 2>/dev/null) || {
    err "Contabo no devolvió snapshotId."
    return 1
  }
  contabo_snapshot_wait_visible "$sid" || {
    err "Snapshot $sid fue aceptado por Contabo pero no pudo verificarse en ${CONTABO_SNAPSHOT_VERIFY_TIMEOUT_SECONDS}s; NO podaré snapshots previos."
    return 1
  }

  install -d -m 0700 "$STATE_DIR"
  printf '%s\n' "$sid" > "${STATE_DIR}/last_contabo_snapshot_id"
  printf '%s\n' "$(now)" > "${STATE_DIR}/last_contabo_snapshot_time"
  chmod 0600 "${STATE_DIR}/last_contabo_snapshot_id" "${STATE_DIR}/last_contabo_snapshot_time"
  ok "Snapshot Contabo verificado: $sid"
  is_true "$do_prune" && contabo_snapshot_prune
}

configure_contabo_interactive() {
  require_root
  load_config
  install -d -m 0700 "$CONFIG_DIR"
  printf '\n%sContabo provider snapshots%s\n' "$C_BOLD" "$C_RESET"
  warn "Recomendación: usa un API user/role dedicado con acceso solo a snapshots de esta instancia."
  warn "Restic/S3 sigue siendo el DR autoritativo; el snapshot de proveedor es solo un acelerador."

  local instance prefix keep slots schedule client_id client_secret api_user api_password tmp tmpc choice
  instance=$(prompt_default "Contabo instance ID" "${CONTABO_INSTANCE_ID:-}")
  prefix=$(prompt_default "Prefijo de snapshots (máx. 16)" "vps-dr")
  slots=$(prompt_default "Máximo de snapshots permitido por tu plan Contabo" "2")
  keep=$(prompt_default "Snapshots gestionados a conservar (debe ser menor que el máximo)" "1")
  warn "La rotación reserva un slot libre. Nunca borra el último snapshot gestionado ni snapshots manuales solo para crear otro."

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
  write_kv "$tmp" CONTABO_SNAPSHOT_SLOT_LIMIT "$slots"
  write_kv "$tmp" CONTABO_SNAPSHOT_PREFIX "$prefix"
  write_kv "$tmp" CONTABO_SNAPSHOT_ONCALENDAR "$schedule"
  write_kv "$tmp" CONTABO_SNAPSHOT_MAX_AGE_HOURS 192
  write_kv "$tmp" CONTABO_SNAPSHOT_VERIFY_TIMEOUT_SECONDS 300
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
