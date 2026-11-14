# shellcheck shell=bash
# Overlay v1.4.3: instalacion automatica y token de Coolify automatico.
#
# `install --auto` responde cada pregunta con la opcion recomendada y la deja
# registrada en pantalla ("[AUTO] pregunta -> respuesta"). Solo pide por teclado
# lo que no puede decidir: las claves S3 si no estan guardadas (config previa o
# borrador de una instalacion interrumpida).
#
# Opciones (solo valores no secretos; las claves nunca van en la linea de comandos):
#   --auto                 responder con lo recomendado
#   --provider s3|backblaze
#   --endpoint URL         endpoint S3 (p. ej. https://<id>.r2.cloudflarestorage.com)
#   --bucket NOMBRE
#   --region REGION        R2: auto
#   --prefix PREFIJO
#   --backup-id NOMBRE
#
# Decisiones del modo automatico que difieren de los defaults interactivos:
# - DB Docker postgres/mysql/mariadb -> builtin (dump logico). El default
#   interactivo "hook" exige un script propio por DB; sin el, cada backup falla.
# - DB Docker de otros motores (mongo, ...) -> ignore, con aviso: no existe dump
#   builtin para ellos y "hook" sin script tambien bloquea los backups.
# - Token de Coolify: se crea automaticamente (ver coolify_provision_api_token).

VPS_BACKUP_AUTO="${VPS_BACKUP_AUTO:-false}"
AUTO_FLAG_PROVIDER=""
AUTO_FLAG_ENDPOINT=""
AUTO_FLAG_BUCKET=""
AUTO_FLAG_REGION=""
AUTO_FLAG_PREFIX=""
AUTO_FLAG_BACKUP_ID=""

auto_mode() { is_true "${VPS_BACKUP_AUTO:-false}"; }

auto_log() { printf '%s[AUTO]%s %s\n' "$C_BLUE" "$C_RESET" "$*" >&2; }

install_parse_flags() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --auto) VPS_BACKUP_AUTO="true" ;;
      --provider)
        case "${2:-}" in s3|backblaze) AUTO_FLAG_PROVIDER="$2" ;; *) err "--provider debe ser s3 o backblaze"; return 2 ;; esac
        shift ;;
      --endpoint) AUTO_FLAG_ENDPOINT="${2:-}"; shift ;;
      --bucket) AUTO_FLAG_BUCKET="${2:-}"; shift ;;
      --region) AUTO_FLAG_REGION="${2:-}"; shift ;;
      --prefix) AUTO_FLAG_PREFIX="${2:-}"; shift ;;
      --backup-id) AUTO_FLAG_BACKUP_ID="${2:-}"; shift ;;
      *) err "Opción desconocida para install: $1"; return 2 ;;
    esac
    shift
  done
  return 0
}

# Aplica las opciones de linea de comandos por encima de config/borrador.
# Se llama al final de install_draft_load, justo antes de las preguntas.
install_apply_flags() {
  [[ -n "$AUTO_FLAG_PROVIDER" ]] && STORAGE_PROVIDER="$AUTO_FLAG_PROVIDER"
  [[ -n "$AUTO_FLAG_ENDPOINT" ]] && S3_ENDPOINT="$AUTO_FLAG_ENDPOINT"
  [[ -n "$AUTO_FLAG_BUCKET" ]] && S3_BUCKET="$AUTO_FLAG_BUCKET"
  [[ -n "$AUTO_FLAG_REGION" ]] && S3_REGION="$AUTO_FLAG_REGION"
  [[ -n "$AUTO_FLAG_PREFIX" ]] && S3_PREFIX="$AUTO_FLAG_PREFIX"
  [[ -n "$AUTO_FLAG_BACKUP_ID" ]] && BACKUP_ID="$AUTO_FLAG_BACKUP_ID"
  # Con un endpoint dado y sin proveedor explicito, un endpoint que no es B2 es S3 generico.
  if [[ -z "$AUTO_FLAG_PROVIDER" && -n "$AUTO_FLAG_ENDPOINT" && "$AUTO_FLAG_ENDPOINT" != *backblazeb2.com* ]]; then
    STORAGE_PROVIDER="s3"
  fi
  return 0
}

# --- prompts: mismas firmas que el base; en modo auto devuelven lo recomendado ---

prompt_default() {
  local prompt="$1" default="$2" value=""
  if auto_mode; then
    if [[ -z "$default" ]]; then
      die "Modo automático: '$prompt' no tiene valor por defecto. Pásalo como opción (--endpoint, --bucket, ...) o ejecuta install sin --auto."
    fi
    auto_log "$prompt -> $default"
    printf '%s' "$default"
    return 0
  fi
  read -r -p "$prompt [$default]: " value || true
  printf '%s' "${value:-$default}"
}

prompt_optional() {
  local prompt="$1" value=""
  if auto_mode; then
    auto_log "$prompt -> (ninguno)"
    return 0
  fi
  read -r -p "$prompt: " value || true
  printf '%s' "$value"
}

prompt_secret() {
  local prompt="$1" value=""
  if auto_mode; then
    case "$prompt" in
      *"Contraseña de cifrado Restic"*) auto_log "Contraseña Restic -> generar una fuerte"; return 0 ;;
      *"session token"*) auto_log "AWS session token -> ninguno"; return 0 ;;
      *"Coolify API token"*) auto_log "Coolify API token -> crear automáticamente"; return 0 ;;
    esac
    # Claves S3 o passwords de DB: no se inventan; se piden si hay terminal.
    [[ -t 0 ]] || die "Modo automático: falta '$prompt' y no hay terminal para pedirlo."
    warn "Modo automático: '$prompt' no está guardado; escríbelo (no se mostrará)."
  fi
  read -r -s -p "$prompt: " value || true
  printf '\n' >&2
  printf '%s' "$value"
}

confirm() {
  local prompt="$1" default="${2:-yes}" answer=""
  if auto_mode; then
    auto_log "$prompt -> $([[ "$default" == "yes" ]] && printf 'Sí' || printf 'No')"
    [[ "$default" == "yes" ]]
    return
  fi
  if [[ "$default" == "yes" ]]; then
    read -r -p "$prompt [S/n]: " answer || true
    answer="${answer:-s}"
  else
    read -r -p "$prompt [s/N]: " answer || true
    answer="${answer:-n}"
  fi
  is_true "$answer"
}

# Default de estrategia para una DB Docker de motor SQL soportado.
auto_sql_db_default() {
  local current="$1"
  if auto_mode; then printf '1'; else printf '%s' "$current"; fi
}

# Default de estrategia para una DB Docker sin dump builtin (mongo, ...).
auto_nonsql_db_default() {
  local name="$1"
  if auto_mode; then
    warn "Modo automático: '$name' no tiene dump builtin; queda en 'ignore' (sus datos NO entran en el backup). Configura un hook y cambia la estrategia con: sudo vps-backup reconfigure"
    printf '2'
  else
    printf '1'
  fi
}

# --- token de API de Coolify -------------------------------------------------

COOLIFY_DR_TOKEN_NAME="vps-backup-dr"

# Ejecuta PHP en el contenedor de Coolify con artisan tinker.
_coolify_tinker() {
  docker exec "${COOLIFY_CONTAINER:-coolify}" php artisan tinker --execute "$1" 2>/dev/null
}

# Crea un token de API del usuario root de Coolify (equipo raiz) con permisos
# read/write/deploy, por el mismo camino que el panel (User::createToken), y lo
# imprime. Revoca antes los tokens anteriores con el mismo nombre: el texto plano
# de un token no se puede recuperar, asi que reinstalar genera uno nuevo.
# Si la API esta desactivada, pide confirmacion (en auto: si) para activarla.
coolify_provision_api_token() {
  local out token enabled
  command_exists docker || { err "Docker no disponible: no puedo crear el token de Coolify."; return 1; }
  docker inspect "${COOLIFY_CONTAINER:-coolify}" >/dev/null 2>&1 || { err "No encuentro el contenedor ${COOLIFY_CONTAINER:-coolify}."; return 1; }
  enabled=$(_coolify_tinker 'echo "API_ENABLED=" . (App\Models\InstanceSettings::get()->is_api_enabled ? "1" : "0");' | awk -F= '/^API_ENABLED=/{print $2; exit}')
  if [[ "$enabled" == "0" ]]; then
    if confirm "La API de Coolify está desactivada y el DR automático la necesita. ¿Activarla?" yes; then
      _coolify_tinker '$s = App\Models\InstanceSettings::get(); $s->is_api_enabled = true; $s->save(); echo "API_ENABLED=1";' | grep -q '^API_ENABLED=1' \
        || { err "No pude activar la API de Coolify."; return 1; }
      info "API de Coolify activada." >&2
    else
      err "Sin API de Coolify no hay redeploy automático."
      return 1
    fi
  fi
  out=$(_coolify_tinker '$u = App\Models\User::find(0); if (! $u) { echo "TOKEN_ERR=no-root-user"; return; } $u->tokens()->where("name", "'"$COOLIFY_DR_TOKEN_NAME"'")->delete(); $t = $u->createToken("'"$COOLIFY_DR_TOKEN_NAME"'", ["read", "write", "deploy"], null, 0); echo "TOKEN=" . $t->plainTextToken;')
  token=$(printf '%s\n' "$out" | awk -F= '/^TOKEN=[0-9]+\|[A-Za-z0-9_-]+$/{print substr($0, 7); exit}')
  if [[ -z "$token" ]]; then
    err "No pude crear el token de Coolify ($(printf '%s\n' "$out" | grep -o 'TOKEN_ERR=[a-z-]*' | head -1))."
    return 1
  fi
  ok "Token de API de Coolify '$COOLIFY_DR_TOKEN_NAME' creado (read/write/deploy, equipo raíz)." >&2
  printf '%s' "$token"
}
