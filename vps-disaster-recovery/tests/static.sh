#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SCRIPT=$(bash "$ROOT/tools/materialize-candidate.sh")

echo '== pinned release candidate =='
expected_sha=$(awk 'NF{print $1; exit}' "$ROOT/candidate/RELEASE_SHA256")
actual_sha=$(sha256sum "$SCRIPT" | awk '{print $1}')
[[ "$expected_sha" =~ ^[0-9a-f]{64}$ ]]
[[ "$actual_sha" == "$expected_sha" ]]

echo '== bash syntax =='
bash -n "$SCRIPT"

echo '== shellcheck errors =='
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck -S error -e SC1090,SC1091 "$SCRIPT"
  shellcheck -S error "$ROOT/tools/build-recovery-image.sh"
  shellcheck -S error "$ROOT/tools/package-release.sh"
  shellcheck -S error -s bash -e SC1090,SC1091 "$ROOT/modules/ops-integrations.sh"
  shellcheck -S error -s bash -e SC1090,SC1091 "$ROOT/modules/ops-contabo-safety.sh"
  shellcheck -S error -s bash -e SC1090,SC1091 "$ROOT/modules/same-os-recovery.sh"
  shellcheck -S error -s bash -e SC1090,SC1091 "$ROOT/modules/restic-install.sh"
  shellcheck -S error -s bash -e SC1090,SC1091 "$ROOT/modules/install-checkpoint.sh"
  shellcheck -S error -s bash -e SC1090,SC1091 "$ROOT/modules/auto-install.sh"
  shellcheck -S error -s bash -e SC1090,SC1091 "$ROOT/modules/install-diagnostics.sh"
  shellcheck -S error -s bash -e SC1090,SC1091 "$ROOT/modules/bind-coverage.sh"
  shellcheck -S error -s bash -e SC1090,SC1091 "$ROOT/modules/coolify-dr-retarget.sh"
else
  echo 'shellcheck unavailable; skipping'
fi

echo '== version =='
[[ "$($SCRIPT version)" == 'vps-backup v1.4.3' ]]
grep -Fqx 'readonly APP_VERSION="1.4.3"' "$SCRIPT"
! grep -Eq '^readonly VERSION=' "$SCRIPT"

echo '== helper invariants =='
# shellcheck disable=SC1090
source "$SCRIPT"
validate_os
validate_backup_id 'coolify-prod-01'
! validate_backup_id '../bad'
validate_b2_bucket 'vps-backups'
! validate_b2_bucket 'bad..bucket'
validate_hhmm '23:59'
! validate_hhmm '24:00'
version_ge '0.19.1' '0.19.1'
version_ge '0.20.0' '0.19.1'
! version_ge '0.18.9' '0.19.1'

echo '== restic version resolver =='
# Sin red: curl se sustituye por stubs. Ultima version valida -> se usa.
curl() { printf '{"tag_name":"v0.20.5"}
'; }
[[ "$(RESTIC_VERSION='' resolve_restic_version)" == '0.20.5' ]]
# GitHub caido -> fallback a la version fija del candidato.
curl() { return 22; }
[[ "$(RESTIC_VERSION='' resolve_restic_version 2>/dev/null)" == "$RESTIC_BOOTSTRAP_VERSION" ]]
# Etiqueta basura o por debajo del minimo -> fallback.
curl() { printf '{"tag_name":"latest; rm -rf /"}
'; }
[[ "$(RESTIC_VERSION='' resolve_restic_version 2>/dev/null)" == "$RESTIC_BOOTSTRAP_VERSION" ]]
curl() { printf '{"tag_name":"v0.9.0"}
'; }
[[ "$(RESTIC_VERSION='' resolve_restic_version 2>/dev/null)" == "$RESTIC_BOOTSTRAP_VERSION" ]]
# Version fijada por el operador.
[[ "$(RESTIC_VERSION='v0.19.1' resolve_restic_version)" == '0.19.1' ]]
! (RESTIC_VERSION='0.19' resolve_restic_version >/dev/null 2>&1)
unset -f curl

echo '== install draft (resume) =='
declare -F install_checkpoint install_draft_load install_draft_clear install_restic_password_to_show >/dev/null
[[ "$(install_restic_password_to_show 'recien-generada')" == 'recien-generada' ]]
[[ -z "$(RESTIC_PASSWORD_UNSHOWN=false install_restic_password_to_show '')" ]]

echo '== auto install =='
install_parse_flags --auto --endpoint https://acct.r2.cloudflarestorage.com --bucket b1 --region auto
[[ "$VPS_BACKUP_AUTO" == true && "$AUTO_FLAG_BUCKET" == b1 ]]
! install_parse_flags --bogus 2>/dev/null
! install_parse_flags --provider gcs 2>/dev/null
STORAGE_PROVIDER=backblaze; install_apply_flags
[[ "$STORAGE_PROVIDER" == s3 && "$S3_ENDPOINT" == https://acct.r2.cloudflarestorage.com && "$S3_REGION" == auto ]]
[[ "$(prompt_default 'Modo' '1' 2>/dev/null)" == 1 ]]
! (prompt_default 'Endpoint' '' >/dev/null 2>&1)
confirm 'x' yes 2>/dev/null
! confirm 'x' no 2>/dev/null
[[ -z "$(prompt_secret 'Contraseña de cifrado Restic (Enter = generar una fuerte)' 2>/dev/null </dev/null)" ]]
! (prompt_secret 'S3 Access Key ID / B2 Application Key ID' >/dev/null 2>&1 </dev/null)
[[ "$(auto_sql_db_default 2)" == 1 && "$(auto_nonsql_db_default mongo 2>/dev/null)" == 2 ]]
VPS_BACKUP_AUTO=false
[[ "$(auto_sql_db_default 2)" == 2 && "$(auto_nonsql_db_default mongo)" == 1 ]]
# Token de Coolify: se extrae del ruido de tinker; sin linea TOKEN= falla.
docker() {
  case "$1" in
    inspect) return 0 ;;
    exec) case "$*" in
            *API_ENABLED*) printf 'API_ENABLED=1\n' ;;
            *createToken*) printf 'PHP Warning: algo\nTOKEN=7|AbC123xyz_-9\n' ;;
          esac ;;
  esac
}
[[ "$(coolify_provision_api_token 2>/dev/null)" == '7|AbC123xyz_-9' ]]
docker() { case "$1" in inspect) return 0 ;; exec) case "$*" in *API_ENABLED*) printf 'API_ENABLED=1\n' ;; *) printf 'TOKEN_ERR=no-root-user\n' ;; esac ;; esac; }
! (coolify_provision_api_token >/dev/null 2>&1)
unset -f docker

echo '== repo diagnostics =='
[[ "$(repo_probe_classify 0 '')" == ok ]]
[[ "$(repo_probe_classify 10 'Fatal: repository does not exist: unable to open config file: Stat: The specified key does not exist.')" == missing ]]
[[ "$(repo_probe_classify 12 'Fatal: wrong password or no key found')" == wrong-password ]]
[[ "$(repo_probe_classify 1 'Fatal: wrong password or no key found')" == wrong-password ]]
[[ "$(repo_probe_classify 1 'Stat: Access Denied. (AccessDenied)')" == auth ]]
[[ "$(repo_probe_classify 1 'The request signature we calculated does not match (SignatureDoesNotMatch)')" == auth ]]
[[ "$(repo_probe_classify 10 'The specified bucket does not exist (NoSuchBucket)')" == no-bucket ]]
[[ "$(repo_probe_classify 1 'dial tcp: lookup x.example: no such host')" == network ]]
[[ "$(repo_probe_classify 1 'algo raro')" == unknown ]]
# Auto: ruta vacia -> init; contrasena erronea -> nunca init.
load_config() { :; }
run_logged() { "$@"; }
log_line() { :; }
VPS_BACKUP_AUTO=true
restic_cmd() { case "$1" in cat) echo 'Fatal: repository does not exist' >&2; return 10 ;; init) echo INIT_CALLED; return 0 ;; check) return 0 ;; esac; }
initialize_repository_interactive 2>/dev/null | grep -q INIT_CALLED
restic_cmd() { case "$1" in cat) echo 'Fatal: wrong password or no key found' >&2; return 12 ;; init) echo INIT_CALLED; return 0 ;; esac; }
out=$( (initialize_repository_interactive) 2>/dev/null || true)
! grep -q INIT_CALLED <<<"$out"
! (initialize_repository_interactive >/dev/null 2>&1)
restic_cmd() { case "$1" in cat) echo 'algo raro' >&2; return 1 ;; init) echo INIT_CALLED; return 0 ;; esac; }
out=$( (initialize_repository_interactive) 2>/dev/null || true)
! grep -q INIT_CALLED <<<"$out"
VPS_BACKUP_AUTO=false
unset -f load_config run_logged log_line restic_cmd

echo '== docker bind coverage (runtime) =='
bt=$(mktemp -d); python3 -c "import socket,sys; socket.socket(socket.AF_UNIX).bind(sys.argv[1])" "$bt/d.sock" 2>/dev/null || true
if [[ -S "$bt/d.sock" ]]; then docker_bind_is_runtime "$bt/d.sock"; fi
docker_bind_is_runtime /dev/null
docker_bind_is_runtime /run
! docker_bind_is_runtime /etc
! docker_bind_is_runtime "$bt"
# Solo el socket queda fuera; un bind de datos sin cubrir sigue fallando.
detect_docker() { return 0; }
docker_bind_mount_paths() { printf '%s
' /dev/null "$bt"; }
path_is_covered_by_backup_sources() { return 1; }
! validate_docker_bind_coverage 2>/dev/null
docker_bind_mount_paths() { printf '%s
' /dev/null /run; }
validate_docker_bind_coverage
unset -f detect_docker docker_bind_mount_paths path_is_covered_by_backup_sources
rm -rf "$bt"

echo '== coolify dr retarget =='
rt=$(mktemp -d)
printf '100.112.184.84\t2222\n' > "$rt/server"
docker() {
  local sql="" a prev="" vip="" vport=""
  for a in "$@"; do
    [[ "$prev" == -c ]] && sql="$a"
    [[ "$prev" == -v && "$a" == ip=* ]] && vip="${a#ip=}"
    [[ "$prev" == -v && "$a" == port=* ]] && vport="${a#port=}"
    prev="$a"
  done
  [[ -n "$sql" ]] || sql=$(cat)
  printf '%s\n' "$sql" >> "$rt/sql.log"
  case "$sql" in
    'SELECT ip, port FROM servers WHERE id = 0') cat "$rt/server" ;;
    UPDATE\ servers*) printf '%s\t%s\n' "$vip" "$vport" > "$rt/server" ;;
    SELECT\ table_name*) printf '%s\n' applications standalone_postgresqls ;;
  esac
  return 0
}
sshd() { printf 'port 2222\n'; }
tailscale() { printf '100.112.250.64\n'; }
ip() { printf '2: eth0    inet 144.126.139.118/20 brd x\n3: tailscale0    inet 100.112.250.64/32 scope global\n'; }
# Original en Tailscale -> IP de Tailscale de este host y estados reseteados.
coolify_retarget_localhost_server 2>/dev/null
[[ "$(cat "$rt/server")" == $'100.112.250.64\t2222' ]]
grep -Fq "UPDATE \"applications\" SET status = 'exited'" "$rt/sql.log"
grep -Fq "UPDATE \"standalone_postgresqls\" SET status = 'exited'" "$rt/sql.log"
# Una IP forzada que no es de este host no se aplica.
printf '100.112.184.84\t2222\n' > "$rt/server"; : > "$rt/sql.log"
! VPS_BACKUP_DR_COOLIFY_LOCALHOST_IP=100.112.184.84 coolify_retarget_localhost_server 2>/dev/null
! grep -q '^UPDATE' "$rt/sql.log"
# Original fuera de Tailscale -> host.docker.internal.
printf '10.20.30.40\t22\n' > "$rt/server"
coolify_retarget_localhost_server 2>/dev/null
[[ "$(cat "$rt/server")" == $'host.docker.internal\t2222' ]]
# start rechazado por "already running" cae a restart; otro error falla.
coolify_cli() {
  printf '%s %s %s\n' "$1" "$2" "$3" >> "$rt/cli.log"
  case "$2" in
    start) [[ "$3" == ok ]] && return 0; printf 'API error 400: Database is already running.\n' >&2; [[ "$3" == boom ]] && printf 'other\n' >&2; return 1 ;;
    restart) [[ "$3" == boom ]] && return 1; return 0 ;;
  esac
}
_coolify_start_resource database ok
_coolify_start_resource database l1 2>/dev/null
grep -Fqx 'database restart l1' "$rt/cli.log"
! _coolify_start_resource database boom 2>/dev/null
# Un servicio sin su red externa: se crea antes de arrancarlo.
docker() { [[ "$1 $2" == 'network inspect' ]] && return 1; printf '%s %s %s %s
' "$1" "$2" "$3" "$4" >> "$rt/net.log"; }
_coolify_start_resource service ok
grep -Fqx 'network create --attachable ok' "$rt/net.log"
unset -f docker sshd tailscale ip coolify_cli
rm -rf "$rt"
# DB builtin de un servicio de Coolify: se arranca el servicio, se para el resto
# del stack y se restaura; una DB fuera de Coolify inexistente se salta.
rr=$(mktemp -d); st="$rr/var/lib/vps-backup/staging"
mkdir -p "$st/system" "$st/coolify"
printf '[{"uuid":"gb7p1bz3e57dhqfzc3o0nard","name":"firefly"}]\n' > "$st/coolify/services.json"
printf '[]\n' > "$st/coolify/applications.json"
printf 'docker-db\tmysql-gb7p1bz3e57dhqfzc3o0nard\tmariadb\tbuiltin\t6\tmariadb:11\ndocker-db\tpostgres-sql-postgres-1\tpostgres\tbuiltin\t6\tpostgres:16\ndocker-db\tmongodb-x\tmongo\thook\t6\tmongo:7\n' > "$st/system/workloads.tsv"
for n in mysql-gb7p1bz3e57dhqfzc3o0nard postgres-sql-postgres-1; do
  d="$st/workloads/docker-db/$(safe_name "$n")"; mkdir -p "$d"; echo x > "$d/a"; (cd "$d" && sha256sum a > SHA256SUMS)
done
[[ "$(_coolify_owner_of mysql-gb7p1bz3e57dhqfzc3o0nard "$st/coolify")" == 'service gb7p1bz3e57dhqfzc3o0nard' ]]
! _coolify_owner_of postgres-sql-postgres-1 "$st/coolify"
docker() {
  case "$1" in
    inspect) [[ "${*: -1}" == mysql-gb7p1bz3e57dhqfzc3o0nard && -e "$rr/started" ]] || return 1
             [[ "$2" == -f ]] && printf 'running/healthy\n'; return 0 ;;
    ps) printf '%s\n' mysql-gb7p1bz3e57dhqfzc3o0nard firefly-gb7p1bz3e57dhqfzc3o0nard ;;
    stop) printf 'stop %s\n' "$2" >> "$rr/log" ;;
  esac
}
_coolify_start_resource() { printf 'start %s %s\n' "$1" "$2" >> "$rr/log"; touch "$rr/started"; }
restore_builtin_mysql_container() { printf 'restore %s\n' "$1" >> "$rr/log"; }
restore_builtin_postgres_container() { printf 'restore %s\n' "$1" >> "$rr/log"; }
restore_policy_databases "$rr" 2>/dev/null
grep -Fqx 'start service gb7p1bz3e57dhqfzc3o0nard' "$rr/log"
grep -Fqx 'stop firefly-gb7p1bz3e57dhqfzc3o0nard' "$rr/log"
! grep -Fqx 'stop mysql-gb7p1bz3e57dhqfzc3o0nard' "$rr/log"
grep -Fqx 'restore mysql-gb7p1bz3e57dhqfzc3o0nard' "$rr/log"
! grep -Fq 'postgres-sql-postgres-1' "$rr/log"
unset -f docker _coolify_start_resource restore_builtin_mysql_container restore_builtin_postgres_container
rm -rf "$rr"
# Volumen restic-live: el que monta una DB builtin (bind a su _data) no se toca;
# el de un contenedor en marcha se copia con el contenedor parado.
rv=$(mktemp -d); mkdir -p "$rv/rr/var/lib/vps-backup/staging/system" "$rv/vols/volumes/n8nvol/_data" "$rv/vols/volumes/vecvol/_data" "$rv/dst/n8nvol" "$rv/dst/vecvol"
printf 'docker-db\tpostgres-n8n\tpostgres\tbuiltin\t6\tpostgres:16\ndocker-volume\tn8nvol\tvolume\trestic-live\t12\tnone\ndocker-volume\tvecvol\tvolume\trestic-live\t12\tvec\n' > "$rv/rr/var/lib/vps-backup/staging/system/workloads.tsv"
docker() {
  case "$1 $2" in
    'volume inspect') [[ "$3" == -f ]] && printf '%s\n' "$rv/dst/$5"; return 0 ;;
    'ps -aq') printf '%s\n' c1 c2 ;;
    'inspect -f')
      case "$3" in
        *State.Running*) [[ "$4" == vec ]] && printf 'true\n' || printf 'false\n' ;;
        *) [[ "$4" == c1 ]] && printf '/postgres-n8n||%s\n' "$rv/dst/n8nvol"
           [[ "$4" == c2 ]] && printf '/vec|vecvol|%s\n' "$rv/dst/vecvol" ;;
      esac ;;
    'stop '*|'start '*) printf '%s %s\n' "$1" "$2" >> "$rv/log" ;;
  esac
  return 0
}
rsync() { printf 'rsync %s\n' "${*: -1}" >> "$rv/log"; }
restore_policy_volumes "$rv/rr" "$rv/vols" 2>/dev/null
! grep -Fq "rsync $rv/dst/n8nvol/" "$rv/log"
grep -Fqx "rsync $rv/dst/vecvol/" "$rv/log"
[[ "$(cat "$rv/log")" == "stop vec"$'\n'"rsync $rv/dst/vecvol/"$'\n'"start vec" ]]
unset -f docker rsync
rm -rf "$rv"
# Estado de origen: solo se arrancan y se exigen los recursos en marcha en origen;
# las DB se esperan (arranque asincrono) y una DB fuera de Coolify ausente es aviso.
vr=$(mktemp -d); vc="$vr/staging/coolify"; mkdir -p "$vc" "$vr/staging/system"
A=aaaaaaaaaaaaaaaaaaaaaaaa; B=bbbbbbbbbbbbbbbbbbbbbbbb; C=cccccccccccccccccccccccc
printf '[{"name":"localhost","uuid":"srv"}]\n' > "$vc/servers.json"
printf '[{"uuid":"%s"},{"uuid":"%s"}]\n' "$A" "$B" > "$vc/services.json"
printf '[{"uuid":"%s"}]\n' "$C" > "$vc/applications.json"
printf '[{"uuid":"%s","status":"running:healthy"},{"uuid":"%s","status":"exited"},{"uuid":"%s","status":"running:healthy"}]\n' "$A" "$B" "$C" > "$vc/resources.json"
printf 'docker-db\tmysql-%s\tmariadb\tbuiltin\t6\tx\ndocker-db\tpostgres-%s\tpostgres\tbuiltin\t6\tx\ndocker-db\tpostgres-sql-postgres-1\tpostgres\tbuiltin\t6\tx\n' "$A" "$B" > "$vr/staging/system/workloads.tsv"
_coolify_expected_running "$vc" "$A"
! _coolify_expected_running "$vc" "$B"
_coolify_expected_running "$vc" dddddddddddddddddddddddd
VPS_BACKUP_DR_START_ALL=true _coolify_expected_running "$vc" "$B"
_coolify_start_resource() { printf 'start %s %s\n' "$1" "$2" >> "$vr/start.log"; }
coolify_start_apps_services_from_inventory "$vc" >/dev/null
[[ "$(cat "$vr/start.log")" == "start service $A"$'\n'"start app $C" ]]
unset -f _coolify_start_resource
[[ "$(_container_resource_uuid "$C-20261123T170952" "$vc")" == "$C" ]]
[[ "$(_container_resource_uuid "mysql-$A" "$vc")" == "$A" ]]
! _container_resource_uuid coolify-db "$vc"
# La DB de A pasa por "starting" antes de quedar healthy: se espera, no falla.
docker() {
  case "$1" in
    info) return 0 ;;
    inspect)
      [[ "${*: -1}" == "mysql-$A" ]] || return 1
      if [[ "$2" == -f ]]; then
        if [[ -e "$vr/seen" ]]; then printf 'running/healthy\n'; else touch "$vr/seen"; printf 'running/starting\n'; fi
      fi
      return 0 ;;
    ps) printf 'x-%s\n' "$B" ;;
  esac
}
coolify_wait_deployments_idle() { return 0; }
coolify_cli() { printf '[{"uuid":"%s","name":"A","status":"running:healthy"},{"uuid":"%s","name":"B","status":"exited"},{"uuid":"%s","name":"C","status":"%s"}]\n' "$A" "$B" "$C" "$(cat "$vr/cstate")"; }
printf 'running:unknown\n' > "$vr/cstate"
MODULE_COOLIFY=false COOLIFY_CLI_ENABLED=true validate_recovered_runtime "$vc/servers.json" >/dev/null 2>"$vr/err"
[[ -e "$vr/seen" ]]
grep -Fq 'postgres-sql-postgres-1' "$vr/err"
! grep -Fq "x-$B" "$vr/err"
# Un recurso en marcha en origen que no queda sano hace fallar y se nombra.
printf 'exited:unhealthy\n' > "$vr/cstate"
! MODULE_COOLIFY=false COOLIFY_CLI_ENABLED=true VPS_BACKUP_DR_READY_TIMEOUT=0 validate_recovered_runtime "$vc/servers.json" >/dev/null 2>"$vr/err"
grep -Fq "C ($C): exited:unhealthy" "$vr/err"
! grep -Fq "B ($B)" "$vr/err"
unset -f docker coolify_wait_deployments_idle coolify_cli
rm -rf "$vr"
# Rutas del host montadas por Coolify: se restauran desde el snapshot de sistema las
# que Coolify no regenera; volumenes Docker, /dev y el plano de control se excluyen,
# el contenedor que usa la ruta se para durante la copia y el directorio vacio que
# Docker crea en un bind de fichero se sustituye por el fichero.
bs=$(mktemp -d -p /var/tmp); H="$bs/host"
mkdir -p "$H/vw" "$H/key.pem" "$H/old"; echo nuevo > "$H/vw/rsa_key.pem"
_coolify_db_psql() {
  cat >/dev/null
  printf '%s\n' "$H/vw/" "$H/key.pem" "$H/missing" /dev/urandom /var/lib/docker/volumes/x/_data \
    /data/coolify/proxy relativo "$H/vw" /data/../etc
}
[[ "$(coolify_bind_sources)" == "$H/key.pem"$'\n'"$H/missing"$'\n'"$H/vw" ]]
restic_cmd() {
  local t="" prev="" a
  for a in "$@"; do [[ "$prev" == --target ]] && t="$a"; prev="$a"; done
  printf '%s ' "$@" > "$bs/restic.args"
  mkdir -p "$t$H/vw"; echo datos > "$t$H/vw/db.sqlite3"; echo clave > "$t$H/key.pem"
}
docker() {
  case "$1" in
    ps) printf 'c1\n' ;;
    inspect) if [[ "$3" == *State.Running* ]]; then printf 'true\n'; else printf '/vaultwarden|%s\n' "$H/vw"; fi ;;
    stop|start) printf '%s %s\n' "$1" "$2" >> "$bs/docker.log" ;;
  esac
  return 0
}
rsync() {
  local src="${*: -2:1}" dst="${*: -1}"
  printf 'rsync %s\n' "$dst" >> "$bs/docker.log"
  if [[ "$src" == */ ]]; then
    [[ " $(printf '%s ' "$@")" == *" --delete "* ]] && find "$dst" -mindepth 1 -delete
    cp -a "$src." "$dst"
  else
    cp -a "$src" "$dst"
  fi
}
MODULE_COOLIFY=true BACKUP_ID=vmi1 coolify_restore_bind_sources snap1 "$bs/dr" >/dev/null 2>"$bs/err"
grep -Fq "restore snap1 --host vmi1 --tag system --target $bs/dr/binds" "$bs/restic.args"
grep -Fq -- "--include $H/vw" "$bs/restic.args"
[[ "$(cat "$H/vw/db.sqlite3")" == datos && ! -e "$H/vw/rsa_key.pem" ]]
[[ -f "$H/key.pem" && "$(cat "$H/key.pem")" == clave ]]
[[ "$(cat "$bs/docker.log")" == "rsync $H/key.pem"$'\n'"stop vaultwarden"$'\n'"rsync $H/vw/"$'\n'"start vaultwarden" ]]
grep -Fq "$H/missing no está en el snapshot" "$bs/err"
# Un directorio con contenido en la ruta de un fichero no se sustituye: falla.
rm -f "$H/key.pem"; mkdir -p "$H/key.pem"; echo x > "$H/key.pem/otro"; : > "$bs/docker.log"
! MODULE_COOLIFY=true BACKUP_ID=vmi1 coolify_restore_bind_sources snap1 "$bs/dr" >/dev/null 2>&1
[[ -f "$H/key.pem/otro" ]]
# Sin MODULE_COOLIFY no hace nada.
rm -f "$bs/restic.args"
MODULE_COOLIFY=false coolify_restore_bind_sources snap1 "$bs/dr"
[[ ! -e "$bs/restic.args" ]]
unset -f _coolify_db_psql restic_cmd docker rsync
rm -rf "$bs"
# DB recien creada por el DR: se vacian sus DB antes de pg_restore (la app pudo
# migrar el esquema con una imagen mas nueva); "postgres" recrea el esquema public.
pr=$(mktemp -d); printf 'n8n\npostgres\ntemplate1\nra"ro\n' > "$pr/database-list.txt"
docker_env_value() { [[ "$2" == POSTGRES_USER ]] && printf 'n8nadmin\n'; [[ "$2" == POSTGRES_PASSWORD ]] && printf 's3cr\n'; return 0; }
docker() { printf '%s|' "$@" >> "$pr/log"; printf '\n' >> "$pr/log"; }
_pg_reset_databases pg1 "$pr" >/dev/null
grep -Fq 'exec|-e|PGPASSWORD=s3cr|pg1|psql|-U|n8nadmin|' "$pr/log"
grep -Fq -- '-c|DROP DATABASE IF EXISTS "n8n" WITH (FORCE);|' "$pr/log"
grep -Fq -- '-c|DROP DATABASE IF EXISTS "ra""ro" WITH (FORCE);|' "$pr/log"
grep -Fq -- '-c|DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;|' "$pr/log"
! grep -Fq 'template1' "$pr/log"
[[ "$(wc -l < "$pr/log")" -eq 3 ]]
unset -f docker_env_value docker
rm -rf "$pr"
# Bind que es enlace simbolico (live/ -> archive/ de Let's Encrypt): se restaura el
# destino y se copia su contenido en la ruta montada.
bl=$(mktemp -d -p /var/tmp); L="$bl/host"; mkdir -p "$L/le/live/d/privkey.pem"
_coolify_db_psql() { cat >/dev/null; printf '%s\n' "$L/le/live/d/privkey.pem"; }
restic_cmd() {
  local t="" prev="" a inc=""
  for a in "$@"; do [[ "$prev" == --target ]] && t="$a"; [[ "$prev" == --include ]] && inc="$a"; prev="$a"; done
  printf '%s\n' "$inc" >> "$bl/includes"
  if [[ "$inc" == */archive/* ]]; then
    mkdir -p "$t$L/le/archive/d"; echo clave-real > "$t$L/le/archive/d/privkey3.pem"
  else
    mkdir -p "$t$L/le/live/d"; ln -sfn ../../archive/d/privkey3.pem "$t$L/le/live/d/privkey.pem"
  fi
}
docker() { [[ "$1" == ps ]] && return 0; return 0; }
rsync() { cp -a "${*: -2:1}" "${*: -1}"; }
MODULE_COOLIFY=true BACKUP_ID=vmi1 coolify_restore_bind_sources snap1 "$bl/dr" >/dev/null 2>"$bl/err"
grep -Fqx "$L/le/archive/d/privkey3.pem" "$bl/includes"
[[ -f "$L/le/live/d/privkey.pem" && ! -L "$L/le/live/d/privkey.pem" ]]
[[ "$(cat "$L/le/live/d/privkey.pem")" == clave-real ]]
! grep -Fq 'no está en el snapshot' "$bl/err"
unset -f _coolify_db_psql restic_cmd docker rsync
rm -rf "$bl"

echo '== backup profiles =='
apply_backup_profile economy
[[ "$BACKUP_PROFILE/$BACKUP_INTERVAL_HOURS/$DATABASE_RPO_HOURS" == 'economy/12/12' ]]
apply_backup_profile balanced
[[ "$BACKUP_PROFILE/$BACKUP_INTERVAL_HOURS/$DATABASE_RPO_HOURS" == 'balanced/6/6' ]]
apply_backup_profile critical
[[ "$BACKUP_PROFILE/$BACKUP_INTERVAL_HOURS/$DATABASE_RPO_HOURS" == 'critical/2/2' ]]
! apply_backup_profile nonsense

echo '== systemd calendar matrix =='
if command -v systemd-analyze >/dev/null 2>&1; then
  for start in $(seq -w 0 23); do
    for interval in 1 2 3 4 6 8 12 24; do
      hours=$(calendar_hours_for_interval "$start" "$interval")
      systemd-analyze calendar "*-*-* ${hours}:17:00" >/dev/null
    done
  done
fi

echo '== set -u restore regressions =='
grep -Fq 'local restore_root="$1" policy=""' "$SCRIPT"
grep -Fq 'local restore_root="$1" volumes_root="$2" policy=""' "$SCRIPT"
! grep -Fq 'policy="${restore_root}/' "$SCRIPT"
! grep -Fq 'restore_hashes="${dir}/restore-hooks.sha256"' "$SCRIPT"

echo '== Restic timestamp regression =='
! grep -Fq -- '--time "$BACKUP_RUN_TIME"' "$SCRIPT"

echo '== restic capability probe robustness =='
# `restic check --help | grep -q ...` under pipefail flakes via SIGPIPE; the
# patched candidate must consume the whole help output (grep -c).
! grep -Fq -- "| grep -q -- '--read-data" "$SCRIPT"
grep -Fq -- "grep -c -- '--read-data-subset' >/dev/null" "$SCRIPT"
grep -Fq -- "grep -c -- '--read-data' >/dev/null" "$SCRIPT"

echo '== recovery safety =='
grep -Fq -- '--require-same-os' "$SCRIPT"
grep -Fq 'schema:3' "$SCRIPT"
grep -Fq 'backup_profile:$profile' "$SCRIPT"
grep -Fq 'apt-mark showmanual' "$SCRIPT"
grep -Fq 'Recovery bloquea S3 sin TLS' "$SCRIPT"
grep -Fq 'recover_same_os_portable "$sid"' "$SCRIPT"
grep -Fq 'same_os_recovery_verify_os' "$SCRIPT"
grep -Fq -- "--exclude='/netplan/***'" "$SCRIPT"
grep -Fq -- "--exclude='/ssh/ssh_host_*'" "$SCRIPT"
grep -Fq '/var/lib/docker|/var/lib/docker/*' "$SCRIPT"
! grep -Fq 'Recovery automático genérico de rootfs todavía no es seguro' "$SCRIPT"

echo '== operational integrations =='
grep -Fq 'provider) cmd_provider "$@" ;;' "$SCRIPT"
grep -Fq 'coolify-policy) cmd_coolify_policy "$@" ;;' "$SCRIPT"
grep -Fq 'dr_plan_ops_extension "$sid"' "$SCRIPT"
grep -Fq 'CONTABO_REQUIRE_RECENT_RESTIC="true"' "$SCRIPT"
grep -Fq 'CONTABO_SNAPSHOT_KEEP="1"' "$SCRIPT"
grep -Fq 'CONTABO_SNAPSHOT_SLOT_LIMIT="2"' "$SCRIPT"
grep -Fq 'CONTABO_SNAPSHOT_VERIFY_TIMEOUT_SECONDS="300"' "$SCRIPT"
grep -Fq 'Rotación segura requiere KEEP < SLOT_LIMIT' "$SCRIPT"
grep -Fq '/snapshots?size=100' "$SCRIPT"
grep -Fq 'contabo_snapshot_wait_visible "$sid"' "$SCRIPT"
grep -Fq 'no rotaré con inventario paginado incompleto' "$SCRIPT"
grep -Fq 'COOLIFY_DB_BACKUP_AUTHORITY="vps-backup"' "$SCRIPT"
grep -Fq 'COOLIFY_DB_NATIVE_SUPPLEMENTAL="false"' "$SCRIPT"
grep -Fq 'coolify-native no puede declarar AUTO_DR_READY' "$SCRIPT"

echo '== release bundle identity =='
release_tmp=$(mktemp -d)
bash "$ROOT/tools/package-release.sh" "$release_tmp" >/dev/null
[[ -x "$release_tmp/vps-backup-v1.4.3.sh" ]]
(
  cd "$release_tmp"
  sha256sum -c SHA256SUMS >/dev/null
)
grep -Fqx 'version=1.4.3' "$release_tmp/RELEASE-MANIFEST.txt"
grep -Fqx "sha256=$actual_sha" "$release_tmp/RELEASE-MANIFEST.txt"
[[ -s "$release_tmp/PRODUCTION-DRILL.md" ]]
[[ -s "$release_tmp/recovery-cloud-init.example.yaml" ]]
rm -rf "$release_tmp"

echo 'STATIC PASS'
