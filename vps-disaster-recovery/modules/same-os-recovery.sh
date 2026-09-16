# shellcheck shell=bash
# v1.4.3 same-OS portable recovery overlay.
# This module is injected after the v1.4.2 candidate has been reproduced and
# content-verified. It intentionally does NOT perform a raw restore to '/'.

same_os_recovery_read_os_value() {
  local file="$1" key="$2"
  awk -F= -v key="$key" '
    $1 == key {
      v=substr($0,index($0,"=")+1)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", v)
      if (v ~ /^".*"$/ || v ~ /^'"'"'.*'"'"'$/) v=substr(v,2,length(v)-2)
      print v
      exit
    }
  ' "$file"
}

same_os_recovery_verify_os() {
  local sid="$1" tmp source_id source_ver current_id current_ver arch manifest_arch=""
  tmp=$(mktemp "${TMP_DIR}/same-os-release.XXXXXX")
  if ! restic_cmd dump "$sid" /var/lib/vps-backup/staging/system/os-release > "$tmp"; then
    rm -f "$tmp"
    err "Same-OS recovery: el snapshot no contiene system/os-release verificable."
    return 1
  fi
  source_id=$(same_os_recovery_read_os_value "$tmp" ID)
  source_ver=$(same_os_recovery_read_os_value "$tmp" VERSION_ID)
  rm -f "$tmp"

  current_id=$(same_os_recovery_read_os_value /etc/os-release ID)
  current_ver=$(same_os_recovery_read_os_value /etc/os-release VERSION_ID)
  arch=$(uname -m)
  [[ -n "$source_id" && -n "$source_ver" ]] || { err "Same-OS recovery: metadata del OS fuente incompleta."; return 1; }
  [[ "$source_id" == "$current_id" && "$source_ver" == "$current_ver" ]] || {
    err "Same-OS recovery bloqueado: fuente=${source_id} ${source_ver}, destino=${current_id} ${current_ver}."
    return 1
  }

  # The captured system manifest includes uname -a. Use it as a second guard
  # where available, but do not parse provider/kernel versions as identity.
  tmp=$(mktemp "${TMP_DIR}/same-os-manifest.XXXXXX")
  if restic_cmd dump "$sid" /var/lib/vps-backup/staging/system/manifest.txt > "$tmp" 2>/dev/null; then
    case "$arch" in
      x86_64|amd64) manifest_arch='x86_64|amd64' ;;
      aarch64|arm64) manifest_arch='aarch64|arm64' ;;
      *) manifest_arch='' ;;
    esac
    if [[ -n "$manifest_arch" ]] && ! grep -Eq "kernel=.*(${manifest_arch})([[:space:]]|$)" "$tmp"; then
      rm -f "$tmp"
      err "Same-OS recovery bloqueado: arquitectura del snapshot no coincide con ${arch}."
      return 1
    fi
  fi
  rm -f "$tmp"
  ok "Same-OS portable rebuild verificado: ${current_id} ${current_ver} ${arch}."
}

same_os_recovery_path_is_denied() {
  local p="${1%/}"
  case "$p" in
    ''|/|/boot|/boot/*|/dev|/dev/*|/proc|/proc/*|/sys|/sys/*|/run|/run/*|/tmp|/tmp/*|/var/tmp|/var/tmp/*|/var/cache|/var/cache/*|/var/lib/docker|/var/lib/docker/*|/var/lib/containerd|/var/lib/containerd/*|/var/lib/postgresql|/var/lib/postgresql/*|/var/lib/mysql|/var/lib/mysql/*|/var/lib/mariadb|/var/lib/mariadb/*|/var/lib/tailscale|/var/lib/tailscale/*|/var/lib/cloud|/var/lib/cloud/*|/var/lib/vps-backup|/var/lib/vps-backup/*)
      return 0 ;;
  esac
  return 1
}

same_os_recovery_collect_includes() {
  local sid="$1" out="$2" p tmp
  : > "$out"
  printf '%s\n' /etc /home /root /opt /srv /usr/local /var/www /var/spool/cron >> "$out"

  # Preserve operator-configured paths too. '/' itself is intentionally ignored;
  # this recovery mode is an overlay of portable data, not a bare-metal rootfs clone.
  tmp=$(mktemp "${TMP_DIR}/same-os-paths.XXXXXX")
  if restic_cmd dump "$sid" /etc/vps-backup/paths.txt > "$tmp" 2>/dev/null; then
    while IFS= read -r p; do
      p="${p%%#*}"
      p=$(printf '%s' "$p" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
      [[ "$p" == /* ]] || continue
      same_os_recovery_path_is_denied "$p" && continue
      printf '%s\n' "${p%/}" >> "$out"
    done < "$tmp"
  fi
  rm -f "$tmp"
  sort -u -o "$out" "$out"
}

same_os_recovery_preserve_target_identity() {
  local preserve="$1" f
  install -d -m 0700 "$preserve/etc/ssh" "$preserve/root-ssh"
  for f in /etc/fstab /etc/hostname /etc/hosts /etc/resolv.conf /etc/machine-id /var/lib/dbus/machine-id; do
    [[ -e "$f" || -L "$f" ]] || continue
    install -d -m 0700 "$preserve$(dirname "$f")"
    cp -a -- "$f" "$preserve$f" 2>/dev/null || true
  done
  cp -a /etc/netplan "$preserve/etc/" 2>/dev/null || true
  cp -a /etc/network "$preserve/etc/" 2>/dev/null || true
  cp -a /etc/systemd/network "$preserve/etc/systemd/" 2>/dev/null || true
  cp -a /etc/NetworkManager/system-connections "$preserve/etc/NetworkManager/" 2>/dev/null || true
  cp -a /etc/ssh/ssh_host_* "$preserve/etc/ssh/" 2>/dev/null || true
  cp -a /root/.ssh/authorized_keys "$preserve/root-ssh/authorized_keys" 2>/dev/null || true
}

same_os_recovery_rsync_etc() {
  local src="$1"
  [[ -d "$src/etc" ]] || return 0
  rsync -aHAX --numeric-ids \
    --exclude='/fstab' \
    --exclude='/crypttab' \
    --exclude='/hostname' \
    --exclude='/hosts' \
    --exclude='/resolv.conf' \
    --exclude='/machine-id' \
    --exclude='/netplan/***' \
    --exclude='/network/interfaces' \
    --exclude='/network/interfaces.d/***' \
    --exclude='/systemd/network/***' \
    --exclude='/NetworkManager/system-connections/***' \
    --exclude='/cloud/***' \
    --exclude='/ssh/ssh_host_*' \
    --exclude='/default/grub' \
    --exclude='/grub.d/***' \
    --exclude='/initramfs-tools/***' \
    --exclude='/kernel/***' \
    --exclude='/modules' \
    --exclude='/modules-load.d/***' \
    --exclude='/udev/rules.d/70-persistent-net.rules' \
    --exclude='/passwd' --exclude='/passwd-' \
    --exclude='/group' --exclude='/group-' \
    --exclude='/shadow' --exclude='/shadow-' \
    --exclude='/gshadow' --exclude='/gshadow-' \
    --exclude='/subuid' --exclude='/subgid' \
    "$src/etc/" /etc/
}

same_os_recovery_rsync_path() {
  local stage="$1" p="$2" src
  p="${p%/}"
  [[ -n "$p" && "$p" != /etc ]] || return 0
  same_os_recovery_path_is_denied "$p" && { warn "Same-OS recovery: omitido path no portable: $p"; return 0; }
  src="${stage}${p}"
  [[ -e "$src" || -L "$src" ]] || return 0

  # Preserve the new provider's access key material. Old authorized_keys can be
  # inspected from staging if needed, but should not silently lock out the new VPS.
  if [[ "$p" == /root ]]; then
    install -d -m 0700 /root
    rsync -aHAX --numeric-ids --exclude='/.ssh/authorized_keys' "$src/" /root/
    return 0
  fi
  if [[ "$p" == /home ]]; then
    install -d -m 0755 /home
    rsync -aHAX --numeric-ids --exclude='*/.ssh/authorized_keys' "$src/" /home/
    return 0
  fi

  install -d -m 0755 "$p" 2>/dev/null || true
  if [[ -d "$src" ]]; then
    rsync -aHAX --numeric-ids "$src/" "$p/"
  else
    install -d -m 0755 "$(dirname "$p")"
    rsync -aHAX --numeric-ids "$src" "$p"
  fi
}

recover_same_os_portable() {
  local sid="$1" stage preserve includes p state rc=0
  require_root
  ensure_directories
  same_os_recovery_verify_os "$sid" || return 1

  # A generic portable rebuild must not be layered on top of an already-running
  # application host. The Coolify path has its own explicit replacement flow.
  if command -v docker >/dev/null 2>&1 && docker ps -q 2>/dev/null | grep -q .; then
    err "Same-OS recovery bloqueado: hay contenedores Docker ejecutándose en el destino."
    return 1
  fi

  stage="${DR_DIR}/same-os-${sid:0:12}"
  preserve="${DR_DIR}/preserve-target-$(date +%Y%m%d-%H%M%S)"
  includes="${DR_DIR}/same-os-${sid:0:12}.paths"
  state="${DR_DIR}/same-os-${sid:0:12}.state"
  install -d -m 0700 "$DR_DIR" "$stage" "$preserve"
  printf 'stage=preflight\nsnapshot=%s\n' "$sid" > "$state"
  chmod 0600 "$state"
  same_os_recovery_preserve_target_identity "$preserve"
  same_os_recovery_collect_includes "$sid" "$includes"

  local restore_args=() count=0
  while IFS= read -r p; do
    [[ -n "$p" ]] || continue
    restore_args+=(--include "$p")
    count=$((count+1))
  done < "$includes"
  # Internal DR evidence is needed for later database/volume/hook validation.
  restore_args+=(--include /var/lib/vps-backup/staging/system --include /var/lib/vps-backup/staging/postgres --include /var/lib/vps-backup/staging/mysql --include /var/lib/vps-backup/staging/workloads --include /var/lib/vps-backup/staging/workload-evidence --include /etc/vps-backup/hooks/restore.d)
  (( count > 0 )) || { err "Same-OS recovery: no hay paths portables que restaurar."; return 1; }

  info "Same-OS recovery: restaurando snapshot exacto a staging ($count path(s) portables)..."
  rm -rf --one-file-system "$stage"/* 2>/dev/null || true
  if ! restic_cmd restore "$sid" --host "$BACKUP_ID" --tag system --target "$stage" "${restore_args[@]}"; then
    err "Same-OS recovery: falló restore a staging. El sistema destino no fue sobreescrito."
    return 1
  fi
  printf 'stage=staged\nsnapshot=%s\n' "$sid" > "$state"

  info "Same-OS recovery: aplicando overlay portable sin --delete..."
  same_os_recovery_rsync_etc "$stage" || rc=$?
  if (( rc == 0 )); then
    while IFS= read -r p; do
      [[ -n "$p" && "$p" != /etc ]] || continue
      same_os_recovery_rsync_path "$stage" "$p" || { rc=$?; break; }
    done < "$includes"
  fi
  if (( rc != 0 )); then
    err "Same-OS recovery: falló el overlay portable (rc=$rc). Archivos originales de identidad/red preservados en $preserve"
    return "$rc"
  fi

  systemctl daemon-reload 2>/dev/null || true
  printf 'stage=portable-overlay-complete\nsnapshot=%s\npreserved=%s\n' "$sid" "$preserve" > "$state"
  chmod 0600 "$state"
  ok "Same-OS portable recovery completado desde snapshot ${sid:0:12}."
  warn "No se restauraron boot/network/provider identity, Docker overlay ni data directories físicas de DB. Valida servicios y ejecuta restores lógicos/hooks correspondientes antes de tráfico."
  return 0
}
