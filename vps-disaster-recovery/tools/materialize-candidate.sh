#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUT=${1:-"$ROOT/build/vps-backup-v1.4.3.sh"}
EXPECTED_V142=5e94be6c3790bccb28dc071665b7c8c17921624eb6d3cc5f5d656ba03b8aa232
EXPECTED_SAME_OS_MODULE_GIT_BLOB=d6c42366d3b9ca22de7e981e8394eb880e37835d
MODULE="$ROOT/modules/same-os-recovery.sh"
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
chmod 0755 "$OUT"

# Release invariants for the new recovery path. Final SHA is pinned only after
# the complete destructive/QEMU matrix passes these exact bytes.
grep -qx 'readonly APP_VERSION="1.4.3"' "$OUT" || { echo 'v1.4.3 version marker missing' >&2; exit 1; }
! grep -Fq 'Recovery automático genérico de rootfs todavía no es seguro' "$OUT" || { echo 'old generic recovery blocker still present' >&2; exit 1; }
grep -Fq 'recover_same_os_portable "$sid"' "$OUT" || { echo 'same-OS recovery dispatch missing' >&2; exit 1; }
grep -Fq 'Same-OS portable recovery completado' "$OUT" || { echo 'same-OS recovery implementation missing' >&2; exit 1; }
actual=$(sha256sum "$OUT" | awk '{print $1}')
echo "v1.4.3 candidate SHA256: $actual" >&2
printf '%s\n' "$OUT"
