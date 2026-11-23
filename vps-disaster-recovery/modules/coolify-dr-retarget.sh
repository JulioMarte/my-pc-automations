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
# Ademas "start" de un recurso que la API da por running cae a "restart", y la red
# externa de un servicio se crea antes de arrancarlo si falta.

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
  # Los servicios usan una red externa con su uuid; en el host nuevo puede faltar
  # ("network <uuid> declared as external, but could not be found").
  if [[ "$kind" == service ]] && ! docker network inspect "$uuid" >/dev/null 2>&1; then
    docker network create --attachable "$uuid" >/dev/null 2>&1       || warn "No pude crear la red Docker $uuid del servicio; Coolify lo intentará."
  fi
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

# --- estado de origen de los recursos -----------------------------------------
# resources.json del inventario guarda el estado de cada recurso en el host de
# origen al hacer el backup. El DR reproduce ese estado: arranca y exige sanos
# solo los recursos que estaban en marcha; los parados en origen (p. ej. stacks
# apagados a proposito) se dejan parados. VPS_BACKUP_DR_START_ALL=true arranca y
# exige todos, como el base.

# Estado de un recurso en origen ("running:healthy", "exited", ...); vacio si no consta.
_coolify_source_status() {
  local adir="$1" uuid="$2"
  [[ -s "$adir/resources.json" ]] || return 0
  jq -r --arg u "$uuid" 'if type=="array" then .[] elif (.data? | type)=="array" then .data[] else empty end
    | select((.uuid? // "") == $u) | (.status? // "") | tostring' "$adir/resources.json" 2>/dev/null | head -1
}

# 0 si el recurso estaba en marcha en origen, o si no hay dato (conservador).
_coolify_expected_running() {
  local adir="$1" uuid="$2" st
  is_true "${VPS_BACKUP_DR_START_ALL:-false}" && return 0
  st=$(_coolify_source_status "$adir" "$uuid")
  [[ -z "$st" || "$st" == running* ]]
}

coolify_start_apps_services_from_inventory() {
  local adir="$1" uuid kind label file
  for kind in service app; do
    case "$kind" in
      service) file="$adir/services.json"; label=service ;;
      app) file="$adir/applications.json"; label=application ;;
    esac
    [[ -s "$file" ]] || continue
    while IFS= read -r uuid; do
      [[ -n "$uuid" ]] || continue
      if ! _coolify_expected_running "$adir" "$uuid"; then
        info "Coolify: $label $uuid estaba parado en origen ($(_coolify_source_status "$adir" "$uuid")); no lo arranco."
        continue
      fi
      info "Coolify: start $label $uuid"
      _coolify_start_resource "$kind" "$uuid" || return 1
    done < <(json_top_uuids "$file")
  done
}

# --- bases de datos builtin dentro de servicios/apps de Coolify ------------------
# Las DB builtin de un servicio de Coolify (p. ej. mysql-<uuid> de Firefly) solo
# existen cuando su servicio arranca, y el base las restauraba antes de arrancar
# servicios ("Container ... no apareció"). Ahora: se arranca el servicio dueño, se
# espera a que la DB este sana, se para el resto del stack mientras se restaura y
# el paso normal de arranque lo levanta despues. Una DB que no gestiona Coolify y
# no existe en este host (p. ej. un stack de Portainer) se salta con aviso: su
# dump queda en el bundle DR para restaurarla a mano.

# Imprime "service <uuid>" o "app <uuid>" si el contenedor es de un recurso del inventario.
_coolify_owner_of() {
  local name="$1" adir="$2" u
  u="${name##*-}"
  [[ "$u" =~ ^[a-z0-9]{24}$ ]] || return 1
  if [[ -s "$adir/services.json" ]] && json_top_uuids "$adir/services.json" | grep -Fxc -- "$u" >/dev/null; then
    printf 'service %s' "$u"; return 0
  fi
  if [[ -s "$adir/applications.json" ]] && json_top_uuids "$adir/applications.json" | grep -Fxc -- "$u" >/dev/null; then
    printf 'app %s' "$u"; return 0
  fi
  return 1
}

# Espera a que el contenedor este running y, si tiene healthcheck, healthy.
_wait_container_ready() {
  local c="$1" timeout="${2:-300}" elapsed=0 st
  while (( elapsed < timeout )); do
    st=$(docker inspect -f '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$c" 2>/dev/null || true)
    case "$st" in running/healthy|running/none) return 0 ;; esac
    sleep 5; elapsed=$((elapsed + 5))
  done
  err "El contenedor $c no quedó listo en ${timeout}s (estado: ${st:-inexistente})."
  return 1
}

# Un contenedor DB creado por el DR al arrancar su servicio ya tiene el esquema que
# la app creo al arrancar, y si la imagen es mas nueva que la del origen incluye
# tablas con FK que el dump no conoce: pg_restore --clean falla ("cannot drop
# constraint ... other objects depend on it"). Como esos datos solo son los recien
# creados, se vacian las DB del dump antes de restaurar: las normales se borran (el
# base las vuelve a crear) y en "postgres" se recrea el esquema public.
_pg_reset_databases() {
  local c="$1" dir="$2" user pass db ident
  local -a dexec=(docker exec)
  user=$(docker_env_value "$c" POSTGRES_USER); user="${user:-postgres}"
  pass=$(docker_env_value "$c" POSTGRES_PASSWORD)
  [[ -n "$pass" ]] && dexec+=(-e "PGPASSWORD=$pass")
  while IFS= read -r db; do
    [[ -n "$db" ]] || continue
    case "$db" in template0|template1) continue ;; esac
    ident="\"${db//\"/\"\"}\""
    if [[ "$db" == postgres ]]; then
      "${dexec[@]}" "$c" psql -U "$user" -X -q -v ON_ERROR_STOP=1 -d postgres \
        -c 'DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;' >/dev/null || return 1
    else
      "${dexec[@]}" "$c" psql -U "$user" -X -q -v ON_ERROR_STOP=1 -d postgres \
        -c "DROP DATABASE IF EXISTS ${ident} WITH (FORCE);" >/dev/null || return 1
    fi
    info "Vaciada la DB $c/$db (creada por el DR; se restaura del dump)"
  done < "$dir/database-list.txt"
}

restore_policy_databases() {
  local restore_root="$1" policy="" kind name engine strategy max_age extra dir adir owner rkind ruuid sib fresh
  local -a skipped=()
  policy="${restore_root}/var/lib/vps-backup/staging/system/workloads.tsv"
  [[ -r "$policy" ]] || return 0
  adir="${restore_root}/var/lib/vps-backup/staging/coolify"
  while IFS=$'\t' read -r -u 3 kind name engine strategy max_age extra; do
    [[ "$kind" == "docker-db" && "$strategy" == "builtin" ]] || continue
    dir="${restore_root}/var/lib/vps-backup/staging/workloads/docker-db/$(safe_name "$name")"
    [[ -d "$dir" ]] || { err "Falta staging de DB $name"; return 1; }
    (cd "$dir" && sha256sum -c SHA256SUMS) >/dev/null || { err "Checksum dump $name falló"; return 1; }
    fresh=false
    if ! docker inspect "$name" >/dev/null 2>&1; then
      if owner=$(_coolify_owner_of "$name" "$adir"); then
        fresh=true
        IFS=" " read -r rkind ruuid <<<"$owner"
        info "Coolify: arranco $rkind $ruuid para crear $name antes de restaurar sus datos"
        _coolify_start_resource "$rkind" "$ruuid" || return 1
        _wait_container_ready "$name" 600 || return 1
        while IFS= read -r sib; do
          [[ -n "$sib" && "$sib" != "$name" ]] || continue
          docker stop "$sib" >/dev/null 2>&1 || true
        done < <(docker ps --filter "label=com.docker.compose.project=${ruuid}" --format '{{.Names}}')
      else
        warn "$name no lo gestiona Coolify y no existe en este host; NO se restaura. Dump: $dir"
        skipped+=("$name")
        continue
      fi
    else
      _wait_container_ready "$name" 300 || return 1
    fi
    if [[ "$fresh" == true && "$engine" == postgres ]]; then
      _pg_reset_databases "$name" "$dir" || return 1
    fi
    case "$engine" in
      postgres) restore_builtin_postgres_container "$name" "$dir" || return $? ;;
      mysql|mariadb) restore_builtin_mysql_container "$name" "$dir" || return $? ;;
      *) err "Restore builtin no soporta engine=$engine ($name)"; return 1 ;;
    esac
  done 3< "$policy"
  if (( ${#skipped[@]} > 0 )); then
    warn "DB builtin sin restaurar (fuera de Coolify; recrearlas y restaurarlas a mano): ${skipped[*]}"
  fi
  return 0
}

# --- volumenes restic-live con contenedores en marcha -----------------------------
# El base restaura las DB builtin por dump y DESPUES hace rsync --delete de cada
# volumen restic-live, aunque haya un contenedor usandolo. En el DR de vps-02 eso
# sobrescribio el directorio de datos de Postgres de n8n (montado por bind desde
# /var/lib/docker/volumes/n8n_n8n_postgres_data/_data, por eso su politica era
# restic-live) con el Postgres en marcha: catalogo corrupto ("unexpected data
# beyond EOF"). Ahora:
# - un volumen que monta una DB builtin (como volumen o por bind a su _data) no se
#   sobrescribe: el dump ya restaurado es la fuente de verdad;
# - el resto de contenedores que usan el volumen se paran durante el rsync y se
#   vuelven a arrancar despues.

# Contenedores (nombres) que montan el volumen, como named volume o por bind a su _data.
_volume_users() {
  local vol="$1" mp id
  mp=$(docker volume inspect -f '{{.Mountpoint}}' "$vol" 2>/dev/null || true)
  [[ -n "$mp" ]] || mp="$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || printf '/var/lib/docker')/volumes/${vol}/_data"
  for id in $(docker ps -aq 2>/dev/null); do
    docker inspect -f '{{.Name}}{{range .Mounts}}|{{.Name}}|{{.Source}}{{end}}' "$id" 2>/dev/null
  done | awk -F'|' -v v="$vol" -v mp="$mp" '{
    n = substr($1, 2)
    for (i = 2; i <= NF; i++) if ($i == v || ($i != "" && (index($i, mp) == 1 || index(mp, $i "/") == 1))) { print n; break }
  }' | sort -u
}

restore_policy_volumes() {
  local restore_root="$1" volumes_root="$2" policy="" kind vol engine strategy max_age extra src dst users builtin hit u
  local -a stopped
  policy="${restore_root}/var/lib/vps-backup/staging/system/workloads.tsv"
  [[ -r "$policy" ]] || return 0
  [[ -n "$volumes_root" && -d "$volumes_root" ]] || return 0
  builtin=$(awk -F '\t' '$1 == "docker-db" && $4 == "builtin" {print $2}' "$policy")
  while IFS=$'\t' read -r -u 3 kind vol engine strategy max_age extra; do
    [[ "$kind" == "docker-volume" && ( "$strategy" == "restic-live" || "$strategy" == "restic-quiesced" ) ]] || continue
    users=$(_volume_users "$vol")
    hit=""
    if [[ -n "$users" && -n "$builtin" ]]; then
      hit=$(grep -Fx -f <(printf '%s\n' "$builtin") <<<"$users" || true)
    fi
    if [[ -n "$hit" ]]; then
      info "Volume $vol son los datos de la DB builtin ${hit//$'\n'/, } (ya restaurada por dump); no se sobrescribe."
      continue
    fi
    docker volume inspect "$vol" >/dev/null 2>&1 || docker volume create "$vol" >/dev/null || return 1
    dst=$(docker volume inspect -f '{{.Mountpoint}}' "$vol" 2>/dev/null || true)
    src=$(find "$volumes_root" -type d -path "*/volumes/${vol}/_data" -print -quit 2>/dev/null || true)
    [[ -d "$src" && -d "$dst" ]] || { err "No pude mapear volume $vol src=$src dst=$dst"; return 1; }
    stopped=()
    for u in $users; do
      if [[ "$(docker inspect -f '{{.State.Running}}' "$u" 2>/dev/null || true)" == true ]]; then
        docker stop "$u" >/dev/null || { err "No pude parar $u para restaurar $vol"; return 1; }
        stopped+=("$u")
      fi
    done
    if (( ${#stopped[@]} > 0 )); then
      info "Restaurando named volume $vol (parados durante la copia: $(printf '%s ' "${stopped[@]}"))"
    else
      info "Restaurando named volume $vol"
    fi
    rsync -aHAX --numeric-ids --delete "$src/" "$dst/" || return 1
    for u in "${stopped[@]}"; do
      docker start "$u" >/dev/null || warn "No pude volver a arrancar $u tras restaurar $vol"
    done
  done 3< "$policy"
}

# --- validacion final del runtime restaurado ---------------------------------------
# El base comprobaba los contenedores DB justo despues de pedir los arranques
# (Coolify los hace asincronos: falsos "no running"), exigia sanos todos los
# recursos aunque estuvieran parados en origen y contaba como fallo una DB fuera de
# Coolify que restore_policy_databases ya habia saltado con aviso. Ahora:
# 1. primero control plane y cola de deployments vacia;
# 2. cada DB de la politica (la del bundle restaurado) se espera hasta VPS_BACKUP_DR_READY_TIMEOUT segundos
#    (600 por defecto); las de recursos parados en origen no se exigen y las de
#    fuera de Coolify ausentes quedan como aviso para restaurarlas a mano;
# 3. los recursos de Coolify que estaban en marcha en origen deben quedar running
#    (healthy o sin healthcheck) dentro del mismo plazo; se listan los que no;
# 4. contenedores unhealthy solo cuentan si son de un recurso esperado o no son
#    de ningun recurso conocido.

# uuid del recurso de Coolify al que pertenece un contenedor (sufijo o prefijo de 24).
_container_resource_uuid() {
  local name="$1" adir="$2" u
  [[ -s "$adir/resources.json" ]] || return 1
  for u in "${name##*-}" "${name%%-*}"; do
    [[ "$u" =~ ^[a-z0-9]{24}$ ]] || continue
    if jq -r 'if type=="array" then .[] elif (.data? | type)=="array" then .data[] else empty end | .uuid? // empty' "$adir/resources.json" 2>/dev/null | grep -Fxc -- "$u" >/dev/null; then
      printf '%s' "$u"; return 0
    fi
  done
  return 1
}

coolify_validate_expected_resources() {
  local servers_file="$1" adir="$2" timeout="$3" uuid json pending elapsed=0 ruuid rname rst
  uuid=$(coolify_localhost_uuid_from_inventory "$servers_file" || true)
  [[ -n "$uuid" ]] || { err "No pude resolver localhost UUID para health validation."; return 1; }
  while :; do
    pending=""
    json=$(coolify_cli --format json server get "$uuid" --resources 2>/dev/null || true)
    if [[ -n "$json" ]] && printf '%s' "$json" | jq -e . >/dev/null 2>&1; then
      while IFS=$'\t' read -r ruuid rname rst; do
        [[ -n "$ruuid" ]] || continue
        _coolify_expected_running "$adir" "$ruuid" || continue
        case "$rst" in
          running|running:healthy|running:unknown|running:none) ;;
          *) pending+="  ${rname} (${ruuid}): ${rst:-sin estado}"$'\n' ;;
        esac
      done < <(printf '%s' "$json" | jq -r 'if type=="array" then .[] elif (.data? | type)=="array" then .data[] else empty end
        | [(.uuid? // ""), (.name? // ""), ((.status? // "") | tostring)] | @tsv' 2>/dev/null)
    else
      pending="  no pude consultar los recursos del localhost restaurado"$'\n'
    fi
    if [[ -z "$pending" ]]; then
      ok "Coolify: los recursos que estaban en marcha en origen están running."
      return 0
    fi
    (( elapsed >= timeout )) && break
    sleep "${VPS_BACKUP_DR_POLL_SECONDS:-15}"
    elapsed=$((elapsed + ${VPS_BACKUP_DR_POLL_SECONDS:-15}))
  done
  err "Recursos en marcha en origen que no quedaron sanos en ${timeout}s:"
  printf '%s' "$pending" >&2
  return 1
}

validate_recovered_runtime() {
  local servers_file="${1:-}" adir="" failures=0 timeout="${VPS_BACKUP_DR_READY_TIMEOUT:-600}"
  local kind name engine strategy max_age extra owner rkind ruuid c
  local policy="$WORKLOAD_POLICY_FILE"
  local -a manual=()
  [[ -n "$servers_file" ]] && adir=$(dirname -- "$servers_file")
  # La politica del bundle restaurado describe el origen; la del host es respaldo.
  [[ -n "$adir" && -r "$adir/../system/workloads.tsv" ]] && policy="$adir/../system/workloads.tsv"
  docker info >/dev/null 2>&1 || { err "Docker no operativo"; return 1; }
  if is_true "${MODULE_COOLIFY:-false}"; then
    coolify_control_plane_health || failures=$((failures + 1))
  fi
  if is_true "${COOLIFY_CLI_ENABLED:-false}"; then
    coolify_wait_deployments_idle || failures=$((failures + 1))
  fi
  if [[ -r "$policy" ]]; then
    while IFS=$'\t' read -r kind name engine strategy max_age extra <&3; do
      [[ "$kind" == "docker-db" && "$strategy" != "ignore" ]] || continue
      owner=$(_coolify_owner_of "$name" "$adir" 2>/dev/null || true)
      if [[ -z "$owner" ]] && ! docker inspect "$name" >/dev/null 2>&1; then
        manual+=("$name"); continue
      fi
      if [[ -n "$owner" ]]; then
        IFS=" " read -r rkind ruuid <<<"$owner"
        if ! _coolify_expected_running "$adir" "$ruuid"; then
          info "DB $name: su $rkind $ruuid estaba parado en origen; no se exige."
          continue
        fi
      fi
      _wait_container_ready "$name" "$timeout" || failures=$((failures + 1))
    done 3< "$policy"
  fi
  if is_true "${COOLIFY_CLI_ENABLED:-false}" && [[ -n "$servers_file" ]]; then
    coolify_validate_expected_resources "$servers_file" "$adir" "$timeout" || failures=$((failures + 1))
  fi
  while IFS= read -r c; do
    [[ -n "$c" ]] || continue
    ruuid=$(_container_resource_uuid "$c" "$adir" || true)
    if [[ -n "$ruuid" ]] && ! _coolify_expected_running "$adir" "$ruuid"; then continue; fi
    err "Contenedor unhealthy tras DR: $c"
    failures=$((failures + 1))
  done < <(docker ps --filter health=unhealthy --format '{{.Names}}' 2>/dev/null || true)
  if (( ${#manual[@]} > 0 )); then
    warn "DB fuera de Coolify sin restaurar (no cuentan como fallo; recrearlas y restaurarlas a mano): ${manual[*]}"
  fi
  (( failures == 0 ))
}

# --- rutas del host montadas por Coolify (binds) -----------------------------------
# El base solo restaura del snapshot de sistema el bundle DR; las rutas del host que
# montan los recursos de Coolify (p. ej. /data/compose/5/vw-data de Vaultwarden o
# /home/<usuario>/Docker-data/portainer) quedaban vacias y los servicios arrancaban
# con datos nuevos. Tras restaurar la base de datos de Coolify y antes de arrancar
# nada, se restauran desde el mismo snapshot las rutas que Coolify montara y no puede
# regenerar: directorios y ficheros sin contenido guardado en su base de datos
# (local_file_volumes) y host_path de local_persistent_volumes. Los ficheros con
# contenido los escribe Coolify; los volumenes Docker los restaura
# restore_policy_volumes; las rutas del plano de control de Coolify no se tocan.
# Se restauran a un staging y se copian con rsync --delete, con los contenedores que
# las usen parados durante la copia.

# Rutas candidatas, una por linea, sin duplicados.
coolify_bind_sources() {
  local sql
  sql="SELECT fs_path FROM local_file_volumes WHERE is_directory OR content IS NULL OR content = ''
UNION SELECT host_path FROM local_persistent_volumes WHERE host_path IS NOT NULL AND host_path <> '';"
  printf '%s\n' "$sql" | _coolify_db_psql | awk 'NF' | while IFS= read -r p; do
    case "$p" in
      /*) ;;
      *) continue ;;
    esac
    case "$p" in
      /|/dev|/dev/*|/proc|/proc/*|/sys|/sys/*|/run|/run/*|/var/run|/var/run/*|/tmp|/tmp/*) continue ;;
      /var/lib/docker|/var/lib/docker/*) continue ;;
      /data/coolify|/data/coolify/source|/data/coolify/source/*|/data/coolify/ssh|/data/coolify/ssh/*|/data/coolify/proxy|/data/coolify/proxy/*) continue ;;
      *..*) continue ;;
    esac
    printf '%s\n' "${p%/}"
  done | sort -u
}

# Contenedores que montan una ruta del host (la ruta o algo por debajo).
_bind_users() {
  local path="$1" c
  for c in $(docker ps -aq 2>/dev/null); do
    docker inspect -f '{{.Name}}{{range .Mounts}}|{{.Source}}{{end}}' "$c" 2>/dev/null
  done | awk -F'|' -v p="$path" '{n=$1; sub(/^\//, "", n); for (i = 2; i <= NF; i++) if ($i == p || index($i, p "/") == 1) { print n; break } }'
}

coolify_restore_bind_sources() {
  local sid="$1" target="$2" stage p src running c link rc=0
  local -a paths=() includes=() stopped=()
  is_true "${MODULE_COOLIFY:-false}" || return 0
  mapfile -t paths < <(coolify_bind_sources)
  (( ${#paths[@]} > 0 )) || { info "Coolify: no hay rutas del host montadas que restaurar."; return 0; }
  stage="${target}/binds"
  mkdir -p "$stage"
  for p in "${paths[@]}"; do includes+=(--include "$p"); done
  info "Coolify: restaurando ${#paths[@]} rutas del host montadas por recursos desde el snapshot $sid"
  restic_cmd restore "$sid" --host "$BACKUP_ID" --tag system --target "$stage" "${includes[@]}" >/dev/null || {
    err "No pude restaurar las rutas del host montadas por Coolify."; return 1; }
  # Un bind que es enlace simbolico (p. ej. live/<dominio>/privkey.pem de Let's
  # Encrypt -> ../../archive/...) necesita tambien su destino; Docker monta el destino.
  includes=()
  for p in "${paths[@]}"; do
    [[ -L "${stage}${p}" ]] || continue
    link=$(readlink -- "${stage}${p}")
    [[ "$link" == /* ]] || link="$(dirname -- "$p")/$link"
    link=$(realpath -m -- "$link")
    includes+=(--include "$link")
  done
  if (( ${#includes[@]} > 0 )); then
    restic_cmd restore "$sid" --host "$BACKUP_ID" --tag system --target "$stage" "${includes[@]}" >/dev/null || {
      err "No pude restaurar los destinos de los enlaces montados por Coolify."; return 1; }
  fi
  for p in "${paths[@]}"; do
    src="${stage}${p}"
    if [[ -L "$src" ]]; then
      link=$(readlink -- "$src")
      [[ "$link" == /* ]] || link="$(dirname -- "$p")/$link"
      src="${stage}$(realpath -m -- "$link")"
    fi
    if [[ ! -e "$src" ]]; then
      warn "Ruta montada $p no está en el snapshot; queda como la cree Coolify."
      continue
    fi
    stopped=()
    for c in $(_bind_users "$p"); do
      running=$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null || true)
      [[ "$running" == true ]] || continue
      docker stop "$c" >/dev/null 2>&1 && stopped+=("$c")
    done
    if [[ -d "$src" ]]; then
      [[ -e "$p" && ! -d "$p" ]] && rm -f -- "$p"
      mkdir -p -- "$p"
      rsync -aHAX --numeric-ids --delete "$src/" "$p/" || { err "Falló la copia de $p"; rc=1; }
    elif [[ -d "$p" ]] && ! rmdir -- "$p" 2>/dev/null; then
      # Docker crea un directorio vacio en la ruta de un bind de fichero que falta;
      # uno con contenido no se sustituye.
      err "$p es un directorio con contenido; no lo sustituyo por el fichero del snapshot."
      rc=1
    else
      mkdir -p -- "$(dirname -- "$p")"
      rsync -aHAX --numeric-ids "$src" "$p" || { err "Falló la copia de $p"; rc=1; }
    fi
    info "Ruta montada $p restaurada${stopped[*]:+ (parados durante la copia: ${stopped[*]})}"
    for c in "${stopped[@]}"; do docker start "$c" >/dev/null 2>&1 || warn "No pude rearrancar $c"; done
  done
  return "$rc"
}
