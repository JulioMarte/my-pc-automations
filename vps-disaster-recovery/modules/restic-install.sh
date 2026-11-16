# shellcheck shell=bash
# Overlay v1.4.3: instalacion de Restic oficial.
#
# Reemplaza install_official_restic del candidato base por dos motivos:
# 1. El base hacia `mktemp -d "$TMP_DIR/..."` antes de que ensure_directories
#    creara $TMP_DIR, asi que `install` fallaba en un host limpio sin Restic
#    (observado en Ubuntu 22.04: "mktemp: failed to create directory").
# 2. Se instala la ultima version publicada de Restic, no una fija. Si GitHub no
#    responde o la etiqueta no es valida, se usa RESTIC_BOOTSTRAP_VERSION. Se
#    puede fijar una version con RESTIC_VERSION=X.Y.Z. El binario se sigue
#    verificando contra SHA256SUMS oficial y contra MIN_RESTIC_VERSION.
#    ensure_restic_min_version actualiza un Restic ya instalado si es mas viejo
#    que la ultima version (solo corre en install/bootstrap, nunca en un backup).

# Imprime la version de Restic a instalar (X.Y.Z), sin prefijo "v".
resolve_restic_version() {
  local pinned="${RESTIC_VERSION:-}" latest=""
  if [[ -n "$pinned" ]]; then
    pinned="${pinned#v}"
    [[ "$pinned" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "RESTIC_VERSION invalida: $pinned (formato X.Y.Z)."
    printf '%s\n' "$pinned"
    return 0
  fi
  latest=$(curl -fsSL --retry 2 --connect-timeout 10 --max-time 30 \
      -H 'Accept: application/vnd.github+json' \
      https://api.github.com/repos/restic/restic/releases/latest 2>/dev/null \
    | jq -r '.tag_name // empty' 2>/dev/null || true)
  latest="${latest#v}"
  if [[ "$latest" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] && version_ge "$latest" "$MIN_RESTIC_VERSION"; then
    printf '%s\n' "$latest"
  else
    warn "No pude resolver la ultima version de Restic; uso v${RESTIC_BOOTSTRAP_VERSION}." >&2
    printf '%s\n' "$RESTIC_BOOTSTRAP_VERSION"
  fi
}

install_official_restic() {
  local version="${1:-}" machine arch filename base tmp expected actual
  [[ -n "$version" ]] || version=$(resolve_restic_version) || die "No pude determinar la version de Restic."
  machine=$(uname -m)
  case "$machine" in
    x86_64|amd64) arch="amd64" ;;
    aarch64|arm64) arch="arm64" ;;
    armv7l|armv7*) arch="arm" ;;
    *) die "Arquitectura no soportada para bootstrap Restic oficial: $machine" ;;
  esac
  filename="restic_${version}_linux_${arch}.bz2"
  base="https://github.com/restic/restic/releases/download/v${version}"
  # install_packages corre antes que ensure_directories: crear aqui el directorio temporal.
  install -d -m 0700 -o root -g root "$TMP_DIR"
  tmp=$(mktemp -d "${TMP_DIR}/restic-install.XXXXXX")
  # shellcheck disable=SC2064
  trap "rm -rf '$tmp'" RETURN
  info "Instalando Restic oficial v${version} (${arch}) con verificación SHA-256..."
  curl -fL --retry 3 --connect-timeout 20 -o "${tmp}/${filename}" "${base}/${filename}" || die "No pude descargar $filename"
  curl -fL --retry 3 --connect-timeout 20 -o "${tmp}/SHA256SUMS" "${base}/SHA256SUMS" || die "No pude descargar SHA256SUMS de Restic."
  expected=$(awk -v f="$filename" '$2==f || $2=="*"f {print $1; exit}' "${tmp}/SHA256SUMS")
  [[ "$expected" =~ ^[0-9a-fA-F]{64}$ ]] || die "No pude obtener checksum oficial para $filename."
  actual=$(sha256sum "${tmp}/${filename}" | awk '{print $1}')
  [[ "$actual" == "$expected" ]] || die "Checksum Restic NO coincide. Se aborta instalación."
  bunzip2 -c "${tmp}/${filename}" > "${tmp}/restic"
  install -m 0755 -o root -g root "${tmp}/restic" /usr/local/bin/restic
  hash -r
  validate_restic_version || die "Restic instalado no cumple mínimo ${MIN_RESTIC_VERSION}."
  ok "Restic instalado: $(restic version | head -1)"
  trap - RETURN
  rm -rf "$tmp"
}

ensure_restic_min_version() {
  local have="" target=""
  have=$(restic_current_version || true)
  target=$(resolve_restic_version) || die "No pude determinar la version de Restic."
  if [[ -n "$have" ]] && version_ge "$have" "$target"; then
    ok "Restic al dia: $have (ultima/objetivo $target, minimo $MIN_RESTIC_VERSION)"
    return 0
  fi
  if [[ -n "$have" ]] && version_ge "$have" "$MIN_RESTIC_VERSION"; then
    info "Restic $have instalado; actualizando a v${target}."
  elif [[ -n "$have" ]]; then
    warn "Restic $have es demasiado antiguo; mínimo requerido: $MIN_RESTIC_VERSION."
  fi
  install_official_restic "$target"
}
