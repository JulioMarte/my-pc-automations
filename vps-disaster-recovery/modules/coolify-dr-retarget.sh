# shellcheck shell=bash
# Overlay v1.4.3: DR de Coolify en un host nuevo sin actuar sobre el host original.
#
# La base de datos de Coolify restaurada conserva el servidor "localhost" (id 0)
# con la IP del host ORIGINAL (p. ej. su IP de Tailscale) y el estado de cada
# recurso tal como estaba alli ("running:healthy"). Sin corregirlo, el Coolify
# restaurado se conecta por SSH al host original: en una prueba de DR con el
# original vivo, valida, arranca y reinicia recursos de PRODUCCION; ademas la API
# rechaza "start" porque cree que todo sigue corriendo.
#
# Tras restaurar la base de datos y antes de arrancar Coolify:
# 1. el servidor localhost apunta a ESTE host: la IP de Tailscale propia si la
#    original era de Tailscale (el ufw de la casa solo admite SSH desde la red de
#    Coolify hacia esa IP), si no host.docker.internal; el puerto es el de sshd.
#    VPS_BACKUP_DR_COOLIFY_LOCALHOST_IP fuerza la IP.
# 2. los estados heredados (running/restarting/starting) pasan a "exited".
# 3. se avisa de los servidores remotos: no se tocan y Coolify si los gestionara.
# Ademas "start" de un recurso que la API da por running cae a "restart".

# systemd-run no define HOME: la CLI de Coolify guardaria su contexto en /.config.
: "${HOME:=/root}"
export HOME

_coolify_db_psql() {
  docker exec -i "${COOLIFY_DB_CONTAINER:-coolify-db}" \
    psql -X -v ON_ERROR_STOP=1 -At -U "${COOLIFY_DB_USER:-coolify}" -d "${COOLIFY_DB_NAME:-coolify}" "$@"
}

coolify_dr_ssh_port() {
  local p
  p=$(sshd -T 2>/dev/null | awk '$1 == "port" {print $2; exit}')
  [[ "$p" =~ ^[0-9]+$ ]] || p=22
  printf '%s' "$p"
}

_ip_is_tailscale() {
  local a b
  IFS=. read -r a b _ _ <<<"$1"
  [[ "$a" == 100 && "$b" =~ ^[0-9]+$ ]] && (( b >= 64 && b <= 127 ))
}

_ip_is_local() {
  ip -o addr show 2>/dev/null | awk '{split($4, a, "/"); print a[1]}' | grep -Fxq -- "$1"
}

# Imprime la IP/host que debe usar el servidor localhost restaurado.
coolify_dr_localhost_target() {
  local old_ip="$1" ts=""
  if [[ -n "${VPS_BACKUP_DR_COOLIFY_LOCALHOST_IP:-}" ]]; then
    printf '%s' "$VPS_BACKUP_DR_COOLIFY_LOCALHOST_IP"; return 0
  fi
  if _ip_is_tailscale "$old_ip" && command -v tailscale >/dev/null 2>&1; then
    ts=$(tailscale ip -4 2>/dev/null | head -1 || true)
    if [[ -n "$ts" ]]; then printf '%s' "$ts"; return 0; fi
    warn "La IP original ($old_ip) es de Tailscale pero este host no tiene Tailscale activo; uso host.docker.internal."
  fi
  printf 'host.docker.internal'
}

coolify_retarget_localhost_server() {
  local row old_ip old_port target port t tables remotes
  row=$(_coolify_db_psql -F $'\t' -c 'SELECT ip, port FROM servers WHERE id = 0') \
    || { err "No pude leer el servidor localhost del Coolify restaurado."; return 1; }
  [[ -n "$row" ]] || { err "El Coolify restaurado no tiene servidor localhost (id 0)."; return 1; }
  IFS=$'\t' read -r old_ip old_port <<<"$row"
  target=$(coolify_dr_localhost_target "$old_ip")
  port=$(coolify_dr_ssh_port)
  if [[ "$target" != "host.docker.internal" ]] && ! _ip_is_local "$target"; then
    err "La IP elegida para el servidor localhost ($target) no pertenece a este host; no la uso."
    return 1
  fi
  # Por stdin: psql no interpola variables (:'ip') en -c.
  printf '%s\n' "UPDATE servers SET ip = :'ip', port = :port, \"user\" = 'root' WHERE id = 0;" \
    | _coolify_db_psql -v ip="$target" -v port="$port" >/dev/null \
    || { err "No pude reapuntar el servidor localhost de Coolify."; return 1; }
  row=$(_coolify_db_psql -F $'\t' -c 'SELECT ip, port FROM servers WHERE id = 0') || return 1
  [[ "$row" == "${target}"$'\t'"${port}" ]] || { err "El servidor localhost no quedó en ${target}:${port} (leído: ${row//$'\t'/:})."; return 1; }
  ok "Coolify: servidor localhost reapuntado de ${old_ip}:${old_port} a ${target}:${port} (este host)."

  tables=$(_coolify_db_psql -c "SELECT table_name FROM information_schema.columns WHERE table_schema = current_schema() AND column_name = 'status' AND (table_name IN ('applications', 'service_applications', 'service_databases') OR table_name LIKE 'standalone\\_%')") \
    || { err "No pude listar las tablas de recursos de Coolify."; return 1; }
  for t in $tables; do
    [[ "$t" =~ ^[a-z_]+$ ]] || continue
    _coolify_db_psql -c "UPDATE \"$t\" SET status = 'exited' WHERE status LIKE 'running%' OR status LIKE 'restarting%' OR status LIKE 'starting%'" >/dev/null \
      || { err "No pude resetear el estado heredado en $t."; return 1; }
  done
  info "Coolify: estados heredados del host original marcados como 'exited'."

  remotes=$(_coolify_db_psql -F ' ' -c "SELECT name, ip || ':' || port FROM servers WHERE id <> 0") || remotes=""
  if [[ -n "$remotes" ]]; then
    warn "Servidores remotos en el Coolify restaurado (no se reapuntan; Coolify volverá a gestionarlos):"
    printf '    %s\n' "$remotes" >&2
  fi
}

# start de la CLI; si la API da el recurso por running, restart (despliega en este host).
_coolify_start_resource() {
  local kind="$1" uuid="$2" out rc=0
  out=$(coolify_cli "$kind" start "$uuid" 2>&1 >/dev/null) || rc=$?
  (( rc == 0 )) && return 0
  if grep -qi 'already running' <<<"$out"; then
    warn "Coolify: $kind $uuid figura como running; lo reinicio para desplegarlo en este host."
    coolify_cli "$kind" restart "$uuid" >/dev/null && return 0
  fi
  printf '%s\n' "$out" >&2
  return 1
}

coolify_start_databases_from_inventory() {
  local file="$1" uuid
  [[ -s "$file" ]] || return 0
  while IFS= read -r uuid; do
    [[ -n "$uuid" ]] || continue
    info "Coolify: start database $uuid"
    _coolify_start_resource database "$uuid" || return 1
  done < <(json_top_uuids "$file")
}

coolify_start_apps_services_from_inventory() {
  local adir="$1" uuid
  if [[ -s "$adir/services.json" ]]; then
    while IFS= read -r uuid; do
      [[ -n "$uuid" ]] || continue
      info "Coolify: start service $uuid"
      _coolify_start_resource service "$uuid" || return 1
    done < <(json_top_uuids "$adir/services.json")
  fi
  if [[ -s "$adir/applications.json" ]]; then
    while IFS= read -r uuid; do
      [[ -n "$uuid" ]] || continue
      info "Coolify: start application $uuid"
      _coolify_start_resource app "$uuid" || return 1
    done < <(json_top_uuids "$adir/applications.json")
  fi
}
