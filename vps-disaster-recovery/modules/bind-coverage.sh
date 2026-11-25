# shellcheck shell=bash
# Overlay v1.4.3: cobertura de bind mounts Docker sin falsos positivos de runtime.
#
# validate_docker_bind_coverage exigia que TODO bind mount de un contenedor
# quedara dentro de las fuentes del backup. Con ONE_FILE_SYSTEM=true el socket
# /var/run/docker.sock (montado por coolify-proxy, coolify-sentinel, portainer...)
# vive en /run (tmpfs, otro dispositivo) y contaba como "NO cubierto": doctor
# fallaba y cada backup abortaba al empezar. Un socket, un dispositivo o una ruta
# de runtime (/run, /var/run, /proc, /sys, /dev) no contiene datos respaldables
# y /run ya esta en las exclusiones del propio script, asi que se ignoran.
# Cualquier otro bind mount sigue siendo fail-closed.

docker_bind_is_runtime() {
  local p="$1" real
  [[ -S "$p" || -c "$p" || -b "$p" || -p "$p" ]] && return 0
  real=$(readlink -f -- "$p" 2>/dev/null || printf '%s' "$p")
  case "$real" in
    /run|/run/*|/var/run|/var/run/*|/proc|/proc/*|/sys|/sys/*|/dev|/dev/*) return 0 ;;
  esac
  return 1
}
