#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUT=${1:-"$ROOT/build/vps-backup-v1.4.2.sh"}
EXPECTED_V131=9e2ee8924e403e0ab4424beb6e0267d8c36673e66a902f8353ac3933838c19c9
EXPECTED_V132=7eda0bac8d39898fbeb97997b123480b37443e2393e9d0b104425789654e5e88
EXPECTED_V133=1a534cc0cadb6baee0508f5c916dc1554b840c2266ef2eaeafce0dfc6948563c
EXPECTED_V140=928e43d1db62374ff17de421a0c19c9eb26642f8e90e9b36f483142208295f40
EXPECTED_V141=9adeb0884d4b0c2fede1e9ccae9a06254d2d96c693dbb84b7d523afd0d7c17fd
EXPECTED_OPS_MODULE=693bcf3e0b19c662eb09e7206473c54e63d68ce69dc353e278915b041a35068e
MODULE="$ROOT/modules/ops-integrations.sh"
mkdir -p "$(dirname "$OUT")"
cat "$ROOT"/candidate/part-* | base64 -d | gzip -dc > "$OUT"

grep -qx 'readonly VERSION="1.3.0"' "$OUT" || { echo 'Unexpected base candidate; refusing to patch' >&2; exit 1; }
sed -i 's/readonly VERSION="1.3.0"/readonly APP_VERSION="1.3.1"/' "$OUT"
sed -i 's/${VERSION}/${APP_VERSION}/g; s/$VERSION/$APP_VERSION/g' "$OUT"
chmod 0755 "$OUT"
[[ "$(sha256sum "$OUT" | awk '{print $1}')" == "$EXPECTED_V131" ]] || { echo 'v1.3.1 intermediate checksum mismatch' >&2; exit 1; }

BUGGY='  local dir="${STAGING_DIR}/system" policy_json='"'"'[]'"'"' restore_hashes="${dir}/restore-hooks.sha256" restore_count=0'
grep -Fqx "$BUGGY" "$OUT" || { echo 'Expected v1.3.1 staging bug not found; refusing to patch' >&2; exit 1; }
sed -i '/^  local dir="${STAGING_DIR}\/system" policy_json=/c\  local dir="${STAGING_DIR}/system"\
  local policy_json='"'"'[]'"'"' restore_hashes="${dir}/restore-hooks.sha256" restore_count=0' "$OUT"
sed -i 's/readonly APP_VERSION="1.3.1"/readonly APP_VERSION="1.3.2"/' "$OUT"
chmod 0755 "$OUT"
[[ "$(sha256sum "$OUT" | awk '{print $1}')" == "$EXPECTED_V132" ]] || { echo 'v1.3.2 intermediate checksum mismatch' >&2; exit 1; }

count=$(grep -F -- '--time "$BACKUP_RUN_TIME"' "$OUT" | wc -l)
(( count >= 1 )) || { echo 'Expected Restic --time override not found; refusing to patch' >&2; exit 1; }
sed -i 's/ --time "$BACKUP_RUN_TIME"//g' "$OUT"
sed -i 's/readonly APP_VERSION="1.3.2"/readonly APP_VERSION="1.3.3"/' "$OUT"
chmod 0755 "$OUT"
[[ "$(sha256sum "$OUT" | awk '{print $1}')" == "$EXPECTED_V133" ]] || { echo 'v1.3.3 intermediate checksum mismatch' >&2; exit 1; }

PATCH_TMP=$(mktemp)
TMP_OUT=$(mktemp)
trap 'rm -f "$PATCH_TMP" "$TMP_OUT"' EXIT
base64 -d "$ROOT/patches/v1.4.0.patch.gz.b64" | gzip -dc > "$PATCH_TMP"
patch --batch --forward --silent "$OUT" < "$PATCH_TMP"
chmod 0755 "$OUT"
[[ "$(sha256sum "$OUT" | awk '{print $1}')" == "$EXPECTED_V140" ]] || { echo 'v1.4.0 intermediate checksum mismatch' >&2; exit 1; }

# v1.4.1: VERSION is a standard variable in /etc/os-release. Keeping it readonly
# breaks validate_os when that file is sourced.
grep -qx 'readonly VERSION="1.4.0"' "$OUT" || { echo 'Expected v1.4.0 VERSION marker missing' >&2; exit 1; }
sed -i 's/readonly VERSION="1.4.0"/readonly APP_VERSION="1.4.1"/' "$OUT"
sed -i 's/${VERSION}/${APP_VERSION}/g; s/$VERSION/$APP_VERSION/g' "$OUT"
chmod 0755 "$OUT"
actual=$(sha256sum "$OUT" | awk '{print $1}')
[[ "$actual" == "$EXPECTED_V141" ]] || { echo "v1.4.1 checksum mismatch: $actual" >&2; exit 1; }

# v1.4.2 operational integrations. Verify the module independently before
# injecting it so a partial/corrupt module cannot silently alter the candidate.
[[ -r "$MODULE" ]] || { echo 'ops integration module missing' >&2; exit 1; }
[[ "$(sha256sum "$MODULE" | awk '{print $1}')" == "$EXPECTED_OPS_MODULE" ]] || { echo 'ops integration module checksum mismatch' >&2; exit 1; }
bash -n "$MODULE"
sed -i 's/readonly APP_VERSION="1.4.1"/readonly APP_VERSION="1.4.2"/' "$OUT"

# Insert module before show_help/main so all functions are defined before main
# dispatch executes. Fail if the anchor disappears instead of silently emitting
# a script without provider/backup-policy support.
awk -v module="$MODULE" '
  BEGIN { inserted=0 }
  /^show_help\(\) \{/ && !inserted {
    while ((getline line < module) > 0) print line
    close(module)
    print ""
    inserted=1
  }
  { print }
  END { if (!inserted) exit 42 }
' "$OUT" > "$TMP_OUT"
mv "$TMP_OUT" "$OUT"
TMP_OUT=$(mktemp)

# Fold optional operational layers into DR readiness. Provider snapshots remain
# non-blocking unless the operator explicitly marks them required.
awk '
  index($0,"Readiness: failures=%d warnings=%d") > 0 && !done {
    print "  dr_plan_ops_extension \"$sid\""
    print "  failures=$((failures + DR_EXTENSION_FAILURES))"
    print "  warnings=$((warnings + DR_EXTENSION_WARNINGS))"
    done=1
  }
  { print }
  END { if (!done) exit 43 }
' "$OUT" > "$TMP_OUT"
mv "$TMP_OUT" "$OUT"
TMP_OUT=$(mktemp)

# Add command dispatch without weakening existing command behavior.
awk '
  /^    doctor\) cmd_doctor / && !done {
    print "    provider) cmd_provider \"$@\" ;;"
    print "    coolify-policy) cmd_coolify_policy \"$@\" ;;"
    done=1
  }
  { print }
  END { if (!done) exit 44 }
' "$OUT" > "$TMP_OUT"
mv "$TMP_OUT" "$OUT"
TMP_OUT=$(mktemp)

# Uninstall should remove the optional provider timer as well.
awk '
  /^  rm -f \"\$INSTALL_PATH\"/ && !done {
    print "  remove_contabo_timer || true"
    done=1
  }
  { print }
  END { if (!done) exit 45 }
' "$OUT" > "$TMP_OUT"
mv "$TMP_OUT" "$OUT"
TMP_OUT=$(mktemp)

# Keep single-file help discoverable. These inserts are anchored to stable lines
# rather than replacing the whole help text.
awk '
  /sudo \$\{APP_NAME\} doctor/ && !usage_done {
    print "  sudo ${APP_NAME} provider contabo status|list|snapshot|prune|configure"
    print "  sudo ${APP_NAME} coolify-policy audit|enforce|configure"
    usage_done=1
  }
  /^  doctor[[:space:]]/ && !cmd_done {
    print "  provider      Contabo snapshots opcionales: create/verify/prune/status/timer."
    print "  coolify-policy Audita/reconcilia backups Coolify sin sustituir restore automático probado."
    cmd_done=1
  }
  { print }
  END { if (!usage_done || !cmd_done) exit 46 }
' "$OUT" > "$TMP_OUT"
mv "$TMP_OUT" "$OUT"
chmod 0755 "$OUT"

# v1.4.2 is intentionally emitted with its calculated SHA during this first CI
# iteration. Once the matrix is green the observed SHA is pinned here and in
# candidate/SHA256SUMS, restoring the byte-for-byte release gate.
actual=$(sha256sum "$OUT" | awk '{print $1}')
grep -qx 'readonly APP_VERSION="1.4.2"' "$OUT" || { echo 'Unexpected v1.4.2 version marker' >&2; exit 1; }
! grep -Eq '^readonly VERSION=' "$OUT" || { echo 'Unsafe VERSION constant would collide with /etc/os-release' >&2; exit 1; }
grep -Fq 'provider) cmd_provider "$@" ;;' "$OUT" || { echo 'provider dispatch missing' >&2; exit 1; }
grep -Fq 'coolify-policy) cmd_coolify_policy "$@" ;;' "$OUT" || { echo 'Coolify policy dispatch missing' >&2; exit 1; }
grep -Fq 'dr_plan_ops_extension "$sid"' "$OUT" || { echo 'DR operations extension missing' >&2; exit 1; }
echo "v1.4.2 candidate SHA256: $actual" >&2
printf '%s\n' "$OUT"
