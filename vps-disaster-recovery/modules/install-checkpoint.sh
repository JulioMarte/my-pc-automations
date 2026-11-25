# shellcheck shell=bash
# Overlay v1.4.3: borrador del instalador para reanudar tras una interrupcion.
#
# El base solo escribia config.conf y credentials al final de
# configure_interactive. Si el instalador se cortaba (Ctrl+C, un die al validar
# el token de Coolify, una caida SSH) se perdian todas las respuestas, incluidas
# las claves S3. Peor: la contrasena Restic generada ya estaba en
# $PASSWORD_FILE pero solo se mostraba al final, y al relanzar se "conservaba"
# sin mostrarse nunca.
#
# Ahora cada seccion guarda un borrador en $CONFIG_DIR (0700, root):
#   install-draft.conf  respuestas no secretas
#   install-draft.cred  secretos (0600, mismo nivel que credentials)
# Al relanzar se ofrece reutilizarlo; los prompts existentes ya preguntan
# "¿Conservar ... existente?". El borrador se borra al guardar la configuracion
# final.

readonly INSTALL_DRAFT_CONF="${CONFIG_DIR}/install-draft.conf"
readonly INSTALL_DRAFT_CRED="${CONFIG_DIR}/install-draft.cred"

_install_draft_write() {
  local file="$1" tmp name
  shift
  tmp=$(atomic_begin "$file")
  : > "$tmp"
  for name in "$@"; do
    [[ -n "${!name:-}" ]] && write_kv "$tmp" "$name" "${!name}"
  done
  atomic_finish "$tmp" "$file" 0600
}

# Guarda el progreso actual. Silencioso e idempotente.
install_checkpoint() {
  local unshown="${RESTIC_PASSWORD_UNSHOWN:-false}"
  is_true "${generated_password:-false}" && unshown="true"
  RESTIC_PASSWORD_UNSHOWN="$unshown"
  _install_draft_write "$INSTALL_DRAFT_CONF" \
    BACKUP_ID STORAGE_PROVIDER S3_ENDPOINT S3_REGION S3_BUCKET S3_PREFIX S3_BUCKET_LOOKUP \
    ALLOW_INSECURE_S3 RESTIC_CACERT BACKUP_MODE ONE_FILE_SYSTEM BACKUP_PROFILE SYSTEM_RPO_HOURS \
    DATABASE_RPO_HOURS VOLUME_RPO_HOURS TARGET_RTO_MINUTES COOLIFY_API_URL \
    RESTIC_PASSWORD_UNSHOWN
  _install_draft_write "$INSTALL_DRAFT_CRED" \
    AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY S3_SESSION_TOKEN AWS_SESSION_TOKEN COOLIFY_API_TOKEN
}

# Carga el borrador de una instalacion interrumpida, si el operador lo acepta.
install_draft_load() {
  [[ -f "$INSTALL_DRAFT_CONF" || -f "$INSTALL_DRAFT_CRED" ]] || return 0
  warn "Se encontró una instalación interrumpida con respuestas guardadas."
  if ! confirm "¿Reutilizar esas respuestas (incluidas las claves guardadas)?" yes; then
    install_draft_clear
    return 0
  fi
  local f
  for f in "$INSTALL_DRAFT_CONF" "$INSTALL_DRAFT_CRED"; do
    [[ -f "$f" ]] || continue
    secure_file_or_die "$f"
    # shellcheck disable=SC1090
    source "$f"
  done
  ok "Respuestas recuperadas; Enter acepta cada valor guardado."
}

install_draft_clear() {
  rm -f "$INSTALL_DRAFT_CONF" "$INSTALL_DRAFT_CRED"
}

# Contrasena Restic que hay que mostrar al final: la recien generada o una
# generada en una corrida interrumpida que nunca llego a mostrarse.
install_restic_password_to_show() {
  local current="$1"
  if [[ -n "$current" ]]; then
    printf '%s' "$current"
  elif is_true "${RESTIC_PASSWORD_UNSHOWN:-false}" && [[ -s "$PASSWORD_FILE" ]]; then
    head -n 1 "$PASSWORD_FILE"
  fi
}
