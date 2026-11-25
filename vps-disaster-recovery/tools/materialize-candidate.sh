#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUT=${1:-"$ROOT/build/vps-backup-v1.4.3.sh"}
EXPECTED_V142=5e94be6c3790bccb28dc071665b7c8c17921624eb6d3cc5f5d656ba03b8aa232
EXPECTED_SAME_OS_MODULE_GIT_BLOB=d6c42366d3b9ca22de7e981e8394eb880e37835d
MODULE="$ROOT/modules/same-os-recovery.sh"
RESTIC_MODULE="$ROOT/modules/restic-install.sh"
EXPECTED_RESTIC_MODULE_GIT_BLOB=763d181f9c6e26023e805a1374a1ac3e4f69431d
CHECKPOINT_MODULE="$ROOT/modules/install-checkpoint.sh"
AUTO_MODULE="$ROOT/modules/auto-install.sh"
EXPECTED_AUTO_MODULE_GIT_BLOB=edc1dd2552e0a0cd0f0b01bf1b64efcdf7c4b7c5
EXPECTED_CHECKPOINT_MODULE_GIT_BLOB=0dec1eef272b32d465ac4abe1ddf9f153631772e
DIAG_MODULE="$ROOT/modules/install-diagnostics.sh"
BIND_MODULE="$ROOT/modules/bind-coverage.sh"
RETARGET_MODULE="$ROOT/modules/coolify-dr-retarget.sh"
EXPECTED_RETARGET_MODULE_GIT_BLOB=30e658b9c8a77bc2dd9fe1abf7e81931bf4eb165
EXPECTED_BIND_MODULE_GIT_BLOB=cac621dcaf1025e8871bc39700f0f81b97c1b443
EXPECTED_DIAG_MODULE_GIT_BLOB=f994f4d3e56740c8708ef80d759c5434d415614d
TMP_OUT=$(mktemp)
trap 'rm -f "$TMP_OUT"' EXIT

# Reproduce the already-proven v1.4.2 candidate byte-for-byte first. Keeping
# this as a separate stage means every v1.4.3 regression is attributable to the
# same-OS recovery delta rather than silently changing the proven base.
bash "$ROOT/tools/materialize-v142.sh" "$OUT" >/dev/null
actual=$(sha256sum "$OUT" | awk '{print $1}')
[[ "$actual" == "$EXPECTED_V142" ]] || { echo "v1.4.2 base checksum mismatch: $actual" >&2; exit 1; }

[[ -r "$MODULE" ]] || { echo 'same-OS recovery module missing' >&2; exit 1; }
command -v git >/dev/null 2>&1 || { echo 'git required to verify same-OS module identity' >&2; exit 1; }
[[ "$(git -C "$ROOT" hash-object "$MODULE")" == "$EXPECTED_SAME_OS_MODULE_GIT_BLOB" ]] || { echo 'same-OS recovery module blob mismatch' >&2; exit 1; }
bash -n "$MODULE"

# Bump only after the exact v1.4.2 base has been verified.
grep -qx 'readonly APP_VERSION="1.4.2"' "$OUT" || { echo 'v1.4.2 version marker missing' >&2; exit 1; }
sed -i 's/readonly APP_VERSION="1.4.2"/readonly APP_VERSION="1.4.3"/' "$OUT"

# Inject portable-rebuild helpers before show_help/main. They are definitions
# only; no recovery behavior changes until recovery-bootstrap reaches execute.
awk -v module="$MODULE" '
  BEGIN { inserted=0 }
  /^show_help\(\) \{/ && !inserted {
    while ((getline line < module) > 0) print line
    close(module)
    print ""
    inserted=1
  }
  { print }
  END { if (!inserted) exit 51 }
' "$OUT" > "$TMP_OUT"
mv "$TMP_OUT" "$OUT"
TMP_OUT=$(mktemp)

# Replace the former unconditional generic-recovery refusal. Coolify keeps its
# existing tested DR path; non-Coolify snapshots now use the conservative
# same-OS portable overlay, which independently re-verifies OS metadata.
awk '
  index($0,"Recovery automático genérico de rootfs todavía no es seguro") > 0 && !done {
    print "  if ! is_true \"$MODULE_COOLIFY\"; then"
    print "    recover_same_os_portable \"$sid\""
    print "    return $?"
    print "  fi"
    done=1
    next
  }
  { print }
  END { if (!done) exit 52 }
' "$OUT" > "$TMP_OUT"
mv "$TMP_OUT" "$OUT"

# The base candidate probes Restic capabilities with `restic check --help |
# grep -q ...`. Under `set -o pipefail`, `grep -q` closes the pipe on the first
# match, restic receives SIGPIPE and the pipeline is reported as failed, so the
# probe intermittently claims the flag is missing (observed as a flaky DR/S3
# failure). Read the whole help output instead: `grep -c` consumes all input and
# its exit status is equivalent for an `if` condition.
awk -v q="'" '
  index($0, "restic check --help 2>&1 | grep -q --") > 0 {
    gsub("grep -q -- " q "--read-data-subset" q, "grep -c -- " q "--read-data-subset" q " >/dev/null")
    gsub("grep -q -- " q "--read-data" q, "grep -c -- " q "--read-data" q " >/dev/null")
    count++
  }
  { print }
  END { if (count < 1) exit 53 }
' "$OUT" > "$TMP_OUT"
mv "$TMP_OUT" "$OUT"
# Overlay de instalacion de Restic (modules/restic-install.sh): el base creaba
# el temporal en $TMP_DIR antes de que ensure_directories lo creara (install
# fallaba en un host limpio sin Restic) y fijaba una version de Restic. Se
# eliminan las dos funciones del base y se inyecta el modulo, verificado por blob.
[[ -r "$RESTIC_MODULE" ]] || { echo 'restic install module missing' >&2; exit 1; }
[[ "$(git -C "$ROOT" hash-object "$RESTIC_MODULE")" == "$EXPECTED_RESTIC_MODULE_GIT_BLOB" ]] || { echo 'restic install module blob mismatch' >&2; exit 1; }
bash -n "$RESTIC_MODULE"
awk -v module="$RESTIC_MODULE" '
  /^(install_official_restic|ensure_restic_min_version)\(\) \{/ { skip=1; removed++; next }
  skip { if ($0 == "}") skip=0; next }
  /^show_help\(\) \{/ && !inserted {
    while ((getline line < module) > 0) print line
    close(module)
    print ""
    inserted=1
  }
  { print }
  END { if (removed != 2 || !inserted) exit 54 }
' "$OUT" > "$TMP_OUT"
mv "$TMP_OUT" "$OUT"
TMP_OUT=$(mktemp)
# Overlay de borrador del instalador (modules/install-checkpoint.sh): guarda
# las respuestas por secciones para reanudar tras una interrupcion y muestra la
# contrasena Restic generada aunque la corrida anterior se cortara.
[[ -r "$CHECKPOINT_MODULE" ]] || { echo 'install checkpoint module missing' >&2; exit 1; }
[[ "$(git -C "$ROOT" hash-object "$CHECKPOINT_MODULE")" == "$EXPECTED_CHECKPOINT_MODULE_GIT_BLOB" ]] || { echo 'install checkpoint module blob mismatch' >&2; exit 1; }
bash -n "$CHECKPOINT_MODULE"
awk -f "$ROOT/tools/install-checkpoint.awk" "$OUT" > "$TMP_OUT"
mv "$TMP_OUT" "$OUT"
TMP_OUT=$(mktemp)
awk -v module="$CHECKPOINT_MODULE" '
  /^show_help\(\) \{/ && !inserted {
    while ((getline line < module) > 0) print line
    close(module)
    print ""
    inserted=1
  }
  { print }
  END { if (!inserted) exit 56 }
' "$OUT" > "$TMP_OUT"
mv "$TMP_OUT" "$OUT"
TMP_OUT=$(mktemp)
# Prompts de politica Docker: los bucles leian la lista por stdin y los
# prompts consumian esa lista en vez del teclado (tools/workload-policy-stdin.awk).
awk -f "$ROOT/tools/workload-policy-stdin.awk" "$OUT" > "$TMP_OUT"
mv "$TMP_OUT" "$OUT"
TMP_OUT=$(mktemp)
# Instalacion automatica y token de Coolify automatico (modules/auto-install.sh).
# Debe ir despues del overlay del borrador: engancha la linea install_draft_load.
[[ -r "$AUTO_MODULE" ]] || { echo 'auto install module missing' >&2; exit 1; }
[[ "$(git -C "$ROOT" hash-object "$AUTO_MODULE")" == "$EXPECTED_AUTO_MODULE_GIT_BLOB" ]] || { echo 'auto install module blob mismatch' >&2; exit 1; }
bash -n "$AUTO_MODULE"
awk -f "$ROOT/tools/auto-install.awk" "$OUT" > "$TMP_OUT"
mv "$TMP_OUT" "$OUT"
TMP_OUT=$(mktemp)
awk -v module="$AUTO_MODULE" '
  /^show_help\(\) \{/ && !inserted {
    while ((getline line < module) > 0) print line
    close(module)
    print ""
    inserted=1
  }
  { print }
  END { if (!inserted) exit 59 }
' "$OUT" > "$TMP_OUT"
mv "$TMP_OUT" "$OUT"
TMP_OUT=$(mktemp)
# Log de instalacion, trazas de fallo y diagnostico del repositorio
# (modules/install-diagnostics.sh). Va despues de auto-install: reescribe su linea de main.
[[ -r "$DIAG_MODULE" ]] || { echo 'install diagnostics module missing' >&2; exit 1; }
[[ "$(git -C "$ROOT" hash-object "$DIAG_MODULE")" == "$EXPECTED_DIAG_MODULE_GIT_BLOB" ]] || { echo 'install diagnostics module blob mismatch' >&2; exit 1; }
bash -n "$DIAG_MODULE"
awk -f "$ROOT/tools/install-diagnostics.awk" "$OUT" > "$TMP_OUT"
mv "$TMP_OUT" "$OUT"
TMP_OUT=$(mktemp)
awk -v module="$DIAG_MODULE" '
  /^show_help\(\) \{/ && !inserted {
    while ((getline line < module) > 0) print line
    close(module)
    print ""
    inserted=1
  }
  { print }
  END { if (!inserted) exit 61 }
' "$OUT" > "$TMP_OUT"
mv "$TMP_OUT" "$OUT"
TMP_OUT=$(mktemp)
# Cobertura de bind mounts (modules/bind-coverage.sh): sockets, dispositivos y
# rutas de runtime (/run, /var/run, ...) no cuentan como bind mount sin cubrir.
[[ -r "$BIND_MODULE" ]] || { echo 'bind coverage module missing' >&2; exit 1; }
[[ "$(git -C "$ROOT" hash-object "$BIND_MODULE")" == "$EXPECTED_BIND_MODULE_GIT_BLOB" ]] || { echo 'bind coverage module blob mismatch' >&2; exit 1; }
bash -n "$BIND_MODULE"
awk '
  $0 == "validate_docker_bind_coverage() {" { inside=1 }
  { print }
  inside && $0 == "    [[ -n \"$p\" && -e \"$p\" ]] || continue" { print "    docker_bind_is_runtime \"$p\" && continue"; hooked++ }
  inside && $0 == "}" { inside=0 }
  END { if (hooked != 1) exit 62 }
' "$OUT" > "$TMP_OUT"
mv "$TMP_OUT" "$OUT"
TMP_OUT=$(mktemp)
awk -v module="$BIND_MODULE" '
  /^show_help\(\) \{/ && !inserted {
    while ((getline line < module) > 0) print line
    close(module)
    print ""
    inserted=1
  }
  { print }
  END { if (!inserted) exit 63 }
' "$OUT" > "$TMP_OUT"
mv "$TMP_OUT" "$OUT"
TMP_OUT=$(mktemp)
# DR de Coolify en host nuevo (modules/coolify-dr-retarget.sh): el servidor
# localhost restaurado deja de apuntar al host original antes de arrancar Coolify.
[[ -r "$RETARGET_MODULE" ]] || { echo 'coolify retarget module missing' >&2; exit 1; }
[[ "$(git -C "$ROOT" hash-object "$RETARGET_MODULE")" == "$EXPECTED_RETARGET_MODULE_GIT_BLOB" ]] || { echo 'coolify retarget module blob mismatch' >&2; exit 1; }
bash -n "$RETARGET_MODULE"
awk '
  $0 == "cmd_disaster_recovery() {" { inside=1 }
  inside && $0 == "  info \"Reejecutando instalador Coolify para arrancar y aplicar migraciones...\"" {
    print "  coolify_retarget_localhost_server || die \"No pude reapuntar el servidor localhost de Coolify a este host; no arranco Coolify.\""
    print "  coolify_restore_bind_sources \"$sid\" \"$target\" || die \"No pude restaurar las rutas del host que montan los recursos de Coolify.\""
    print "  coolify_pin_images_from_inventory \"$target\""
    hooked++
  }
  { print }
  inside && $0 == "}" { inside=0 }
  END { if (hooked != 1) exit 64 }
' "$OUT" > "$TMP_OUT"
mv "$TMP_OUT" "$OUT"
TMP_OUT=$(mktemp)
awk -v module="$RETARGET_MODULE" '
  /^show_help\(\) \{/ && !inserted {
    while ((getline line < module) > 0) print line
    close(module)
    print ""
    inserted=1
  }
  { print }
  END { if (!inserted) exit 65 }
' "$OUT" > "$TMP_OUT"
mv "$TMP_OUT" "$OUT"
TMP_OUT=$(mktemp)
chmod 0755 "$OUT"

# Release invariants for the new recovery path. Final SHA is pinned only after
# the complete destructive/QEMU matrix passes these exact bytes.
grep -qx 'readonly APP_VERSION="1.4.3"' "$OUT" || { echo 'v1.4.3 version marker missing' >&2; exit 1; }
! grep -Fq 'Recovery automático genérico de rootfs todavía no es seguro' "$OUT" || { echo 'old generic recovery blocker still present' >&2; exit 1; }
grep -Fq 'recover_same_os_portable "$sid"' "$OUT" || { echo 'same-OS recovery dispatch missing' >&2; exit 1; }
grep -Fq 'Same-OS portable recovery completado' "$OUT" || { echo 'same-OS recovery implementation missing' >&2; exit 1; }
! grep -Fq "grep -q -- '--read-data" "$OUT" || { echo 'restic probe still uses grep -q (pipefail SIGPIPE flake)' >&2; exit 1; }
grep -Fq "grep -c -- '--read-data-subset' >/dev/null" "$OUT" || { echo 'restic probe patch missing (subset)' >&2; exit 1; }
grep -Fq "grep -c -- '--read-data' >/dev/null" "$OUT" || { echo 'restic probe patch missing (read-data)' >&2; exit 1; }
grep -Fq 'install -d -m 0700 -o root -g root "$TMP_DIR"' "$OUT" || { echo 'restic install tmpdir fix missing' >&2; exit 1; }
grep -Fq 'releases/latest' "$OUT" || { echo 'restic latest-version resolver missing' >&2; exit 1; }
[[ "$(grep -c '^install_official_restic() {' "$OUT")" == 1 ]] || { echo 'install_official_restic defined more than once' >&2; exit 1; }
[[ "$(grep -c '^ensure_restic_min_version() {' "$OUT")" == 1 ]] || { echo 'ensure_restic_min_version defined more than once' >&2; exit 1; }
[[ "$(grep -c '^  install_checkpoint$' "$OUT")" == 5 ]] || { echo 'install checkpoints missing' >&2; exit 1; }
grep -qx '  install_draft_load' "$OUT" || { echo 'install draft load missing' >&2; exit 1; }
grep -qx '  install_draft_clear' "$OUT" || { echo 'install draft clear missing' >&2; exit 1; }
grep -Fqx '  done 3< <(docker_db_containers)' "$OUT" || { echo 'workload policy DB loop still reads list from stdin' >&2; exit 1; }
grep -Fqx '  done 4< <(docker volume ls -q 2>/dev/null)' "$OUT" || { echo 'workload policy volume loop still reads list from stdin' >&2; exit 1; }
grep -Fq 'install_parse_flags "$@" || exit 2; install_trace_begin' "$OUT" || { echo 'install flags hook missing' >&2; exit 1; }
grep -Fq 'coolify_provision_api_token || true' "$OUT" || { echo 'coolify token auto-provision hook missing' >&2; exit 1; }
[[ "$(grep -c '^initialize_repository_interactive() {' "$OUT")" == 1 ]] || { echo 'initialize_repository_interactive defined more than once' >&2; exit 1; }
grep -Fq 'install_trace_begin install "$@"; cmd_install; install_trace_end' "$OUT" || { echo 'install trace hook missing' >&2; exit 1; }
grep -Fqx '    docker_bind_is_runtime "$p" && continue' "$OUT" || { echo 'bind coverage runtime skip missing' >&2; exit 1; }
grep -Fq '"$restic_password" "$C_RESET" >&"$INSTALL_TTY_FD"' "$OUT" || { echo 'restic password may leak into install log' >&2; exit 1; }
grep -Fqx '  coolify_retarget_localhost_server || die "No pude reapuntar el servidor localhost de Coolify a este host; no arranco Coolify."' "$OUT" || { echo 'coolify localhost retarget hook missing' >&2; exit 1; }
grep -Fqx '  coolify_restore_bind_sources "$sid" "$target" || die "No pude restaurar las rutas del host que montan los recursos de Coolify."' "$OUT" || { echo 'coolify bind sources restore hook missing' >&2; exit 1; }
grep -Fqx '  coolify_pin_images_from_inventory "$target"' "$OUT" || { echo 'coolify image pin hook missing' >&2; exit 1; }
[[ "$(grep -c '^coolify_start_databases_from_inventory() {' "$OUT")" == 2 ]] || { echo 'coolify start override missing' >&2; exit 1; }
[[ "$(grep -c '^restore_policy_databases() {' "$OUT")" == 2 ]] || { echo 'builtin DB owner-service override missing' >&2; exit 1; }
[[ "$(grep -c '^_coolify_start_until_ready() {' "$OUT")" == 1 ]] || { echo 'DR start retry helper missing' >&2; exit 1; }
[[ "$(grep -c '^restore_policy_volumes() {' "$OUT")" == 2 ]] || { echo 'live-safe volume restore override missing' >&2; exit 1; }
[[ "$(grep -c '^validate_recovered_runtime() {' "$OUT")" == 2 ]] || { echo 'source-state runtime validation override missing' >&2; exit 1; }
[[ "$(grep -c '^coolify_start_apps_services_from_inventory() {' "$OUT")" == 2 ]] || { echo 'source-state start override missing' >&2; exit 1; }
actual=$(sha256sum "$OUT" | awk '{print $1}')
echo "v1.4.3 candidate SHA256: $actual" >&2
printf '%s\n' "$OUT"
