# shellcheck shell=bash
# Overlay v1.4.3: log de instalacion, trazas de fallo y diagnostico del repositorio.
#
# 1. Log de instalacion: `install` y `reconfigure` copian toda la salida
#    (sin colores) a /var/log/vps-backup/install-<UTC>.log (0600, root) y
#    apuntan /var/log/vps-backup/install-last.log a la ultima corrida. Los
#    secretos no llegan al log: los prompts secretos no hacen eco y la
#    contrasena Restic generada se imprime solo en la terminal original.
# 2. Trazas: un fallo inesperado (set -e) o un die imprimen "[TRACE]" con el
#    codigo de salida, el comando (texto sin expandir, no valores) y la pila de
#    funciones con numeros de linea, mas la ruta del log.
# 3. Repositorio: el base probaba `restic cat config` descartando el error y
#    preguntaba "¿Inicializar un repositorio NUEVO?" con default No, asi que
#    `install --auto` abortaba en un bucket vacio sin decir por que. Ahora se
#    clasifica el fallo (codigo de salida de Restic >= 0.17 y texto del error),
#    se muestra el error real y:
#      missing         ruta vacia -> se inicializa (default Si; auto: Si)
#      wrong-password  existe un repo y la contrasena local no lo abre -> nunca init
#      auth/no-bucket/network -> se aborta con la causa concreta
#      unknown         interactivo: pregunta con default No; auto: aborta
#    `restic init` ademas se niega a escribir sobre un repositorio existente.

readonly INSTALL_LOG_DIR="/var/log/vps-backup"
INSTALL_LOG=""
INSTALL_TTY_FD=1
_INSTALL_TRACE_PIDS=()

# Pila de llamadas "f1:linea <- f2:linea ..." omitiendo los marcos propios.
_install_trace_stack() {
  local i skip="${1:-2}" out=""
  for ((i = skip; i < ${#FUNCNAME[@]}; i++)); do
    out+=" <- ${FUNCNAME[i]}:${BASH_LINENO[i - 1]}"
  done
  printf '%s' "${out# <- }"
}

_install_trace_err() {
  local rc="$1" cmd="$2"
  printf '[TRACE] fallo rc=%s en: %s | pila: %s\n' "$rc" "$cmd" "$(_install_trace_stack 2)" >&2
  if (( BASH_SUBSHELL == 0 )) && [[ -n "$INSTALL_LOG" ]]; then
    printf '[TRACE] log completo: %s\n' "$INSTALL_LOG" >&2
    _install_trace_close
  fi
}

# Empieza a registrar la corrida. Idempotente. Solo como root.
install_trace_begin() {
  [[ -z "$INSTALL_LOG" ]] || return 0
  [[ ${EUID:-$(id -u)} -eq 0 ]] || return 0
  install -d -m 0700 -o root -g root "$INSTALL_LOG_DIR" || return 0
  INSTALL_LOG="${INSTALL_LOG_DIR}/install-$(date -u +%Y%m%dT%H%M%SZ)-$$.log"
  ( umask 077; : > "$INSTALL_LOG" ) || { INSTALL_LOG=""; return 0; }
  ln -sfn "$(basename "$INSTALL_LOG")" "${INSTALL_LOG_DIR}/install-last.log"
  {
    printf '# %s v%s  comando:' "$APP_NAME" "$APP_VERSION"; printf ' %s' "$@"; printf '\n'
    printf '# fecha UTC: %s  host: %s\n' "$(date -u +%FT%TZ)" "$(hostname 2>/dev/null || true)"
    printf '# script: %s  sha256: %s\n' "$0" "$(sha256sum "$0" 2>/dev/null | awk '{print $1}')"
    printf '# os: %s  kernel: %s  bash: %s\n' "$(. /etc/os-release 2>/dev/null; printf '%s' "${PRETTY_NAME:-?}")" "$(uname -r)" "$BASH_VERSION"
    printf '# restic: %s\n' "$(restic version 2>/dev/null | head -1 || printf 'no instalado')"
  } >> "$INSTALL_LOG"
  exec 5>&1 6>&2
  # Un solo pipe para stdout y stderr: conserva el orden de mensajes y prompts.
  # tee hereda la salida original (no reabre /dev/fd/5: con stdout a un archivo
  # eso sobrescribiria desde el inicio); la copia al log va por su propia rama.
  exec > >(tee >(sed -u 's/\x1b\[[0-9;]*m//g' >> "$INSTALL_LOG")) 2>&1
  _INSTALL_TRACE_PIDS+=("$!")
  INSTALL_TTY_FD=5
  trap '_install_trace_err $? "$BASH_COMMAND"' ERR
  info "Log de esta instalación: $INSTALL_LOG"
}

# Restaura la salida original y espera a que el log termine de escribirse.
_install_trace_close() {
  [[ -n "$INSTALL_LOG" && "$INSTALL_TTY_FD" == 5 ]] || return 0
  trap - ERR
  exec 1>&5 2>&6
  INSTALL_TTY_FD=1
  wait "${_INSTALL_TRACE_PIDS[@]}" 2>/dev/null || true
}

install_trace_end() {
  [[ -n "$INSTALL_LOG" ]] || return 0
  info "Log de esta instalación: $INSTALL_LOG"
  _install_trace_close
}

# Igual que el die del base, mas la traza y la ruta del log.
die() {
  err "$*"
  if [[ -n "$INSTALL_LOG" ]]; then
    printf '[TRACE] die en: %s\n' "$(_install_trace_stack 2)" >&2
    if (( BASH_SUBSHELL == 0 )); then
      printf '[TRACE] log completo: %s\n' "$INSTALL_LOG" >&2
      _install_trace_close
    fi
  fi
  exit 1
}

# --- diagnostico del repositorio ----------------------------------------------

REPO_PROBE_RC=0
REPO_PROBE_OUT=""

repo_probe() {
  local rc=0 out
  out=$(restic_cmd cat config 2>&1 >/dev/null) || rc=$?
  REPO_PROBE_RC=$rc
  REPO_PROBE_OUT=$out
}

# Imprime: ok | missing | wrong-password | locked | no-bucket | auth | network | unknown
repo_probe_classify() {
  local rc="$1" out="$2"
  case "$rc" in
    0) printf 'ok'; return 0 ;;
    12) printf 'wrong-password'; return 0 ;;
    11) printf 'locked'; return 0 ;;
  esac
  if grep -qiE 'wrong password|no key found' <<<"$out"; then printf 'wrong-password'
  elif grep -qiE 'NoSuchBucket|bucket does not exist|specified bucket does not exist' <<<"$out"; then printf 'no-bucket'
  elif grep -qiE 'AccessDenied|InvalidAccessKeyId|SignatureDoesNotMatch|Unauthorized|Forbidden|InvalidToken|\b40[13]\b' <<<"$out"; then printf 'auth'
  elif grep -qiE 'no such host|connection refused|i/o timeout|timeout|network is unreachable|x509|certificate|tls:' <<<"$out"; then printf 'network'
  elif [[ "$rc" == 10 ]] || grep -qiE 'repository does not exist|config file does not exist|Is there a repository|NoSuchKey|key does not exist' <<<"$out"; then printf 'missing'
  else printf 'unknown'
  fi
}

_repo_show_error() {
  [[ -n "$REPO_PROBE_OUT" ]] || return 0
  printf 'Error de Restic (rc=%s):\n' "$REPO_PROBE_RC" >&2
  printf '%s\n' "$REPO_PROBE_OUT" | tail -n 15 | sed 's/^/    /' >&2
}

initialize_repository_interactive() {
  local kind
  load_config
  info "Probando repositorio: $RESTIC_REPOSITORY"
  repo_probe
  kind=$(repo_probe_classify "$REPO_PROBE_RC" "$REPO_PROBE_OUT")
  log_line INFO "repo probe rc=$REPO_PROBE_RC clase=$kind"
  case "$kind" in
    ok)
      ok "Repositorio Restic existente y accesible."
      return 0 ;;
    locked)
      warn "El repositorio existe pero tiene un lock activo; se considera accesible."
      _repo_show_error
      return 0 ;;
    missing)
      info "La ruta está vacía: aún no hay repositorio Restic (normal en la primera instalación)."
      printf 'Repositorio objetivo: %s\n' "$RESTIC_REPOSITORY"
      confirm "¿Inicializar un repositorio NUEVO exactamente en esa ruta?" yes \
        || die "No se inicializó el repositorio. Ejecuta de nuevo: sudo $APP_NAME install"
      run_logged restic_cmd init || die "restic init falló (ver el error de arriba)."
      ok "Repositorio Restic inicializado."
      run_logged restic_cmd check || die "restic check falló justo después de init."
      return 0 ;;
  esac
  _repo_show_error
  case "$kind" in
    wrong-password)
      die "Ya existe un repositorio en esa ruta y la contraseña de $PASSWORD_FILE no lo abre. NO se inicializa (se perderían los datos). Restaura la contraseña original en $PASSWORD_FILE o usa otro prefijo (--prefix) y repite: sudo $APP_NAME install" ;;
    auth)
      die "El storage rechazó las credenciales. Revisa Access Key ID / Secret y que la key tenga lectura y escritura de objetos sobre el bucket '$S3_BUCKET' (R2: permiso 'Object Read & Write'). Para cambiarlas: sudo $APP_NAME reconfigure" ;;
    no-bucket)
      die "El bucket '$S3_BUCKET' no existe en $S3_ENDPOINT. Créalo (R2: cf r2 buckets create --name $S3_BUCKET) y repite: sudo $APP_NAME install" ;;
    network)
      die "No pude conectar con $S3_ENDPOINT (DNS, red o TLS). Revisa el endpoint y la conectividad del VPS." ;;
  esac
  warn "No pude clasificar el fallo; puede ser endpoint, credenciales, prefijo o password incorrectos."
  warn "Con una B2 key restringida a bucket vía S3, verifica también 'Allow List All Bucket Names' (listAllBucketNames)."
  printf 'Repositorio objetivo: %s\n' "$RESTIC_REPOSITORY"
  if auto_mode; then
    die "Modo automático: no inicializo un repositorio ante un error desconocido."
  fi
  confirm "¿Inicializar un repositorio NUEVO exactamente en esa ruta?" no \
    || die "No se inicializó el repositorio. Corrige la configuración y ejecuta: sudo $APP_NAME reconfigure"
  run_logged restic_cmd init || die "restic init falló (ver el error de arriba)."
  ok "Repositorio Restic inicializado."
  run_logged restic_cmd check || die "restic check falló justo después de init."
}
