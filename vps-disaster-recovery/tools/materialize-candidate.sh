#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUT=${1:-"$ROOT/build/vps-backup-v1.3.sh"}
mkdir -p "$(dirname "$OUT")"
cat "$ROOT"/candidate/part-* | base64 -d | gzip -dc > "$OUT"

# v1.3.1 regression fix discovered by the first real Ubuntu CI run:
# the application constant VERSION collided with VERSION from /etc/os-release.
grep -qx 'readonly VERSION="1.3.0"' "$OUT" || { echo 'Unexpected base candidate; refusing to patch' >&2; exit 1; }
sed -i 's/readonly VERSION="1.3.0"/readonly APP_VERSION="1.3.1"/' "$OUT"
sed -i 's/\${VERSION}/\${APP_VERSION}/g; s/\$VERSION/\$APP_VERSION/g' "$OUT"
chmod 0755 "$OUT"

# Verify the known v1.3.1 artifact before applying any further migration.
(
  cd "$(dirname "$OUT")"
  printf '%s  %s\n' "$(awk '{print $1}' "$ROOT/candidate/SHA256SUMS")" "$(basename "$OUT")" | sha256sum -c - >&2
)

# v1.3.2 regression fix discovered by real backup execution with `set -u`:
# Bash expands all RHS expressions in a single `local` command before assigning
# them, so `${dir}` was unbound when restore_hashes was initialized.
BUGGY='  local dir="${STAGING_DIR}/system" policy_json='"'"'[]'"'"' restore_hashes="${dir}/restore-hooks.sha256" restore_count=0'
grep -Fqx "$BUGGY" "$OUT" || { echo 'Expected v1.3.1 staging bug not found; refusing to patch' >&2; exit 1; }
sed -i '/^  local dir="${STAGING_DIR}\/system" policy_json=/c\  local dir="${STAGING_DIR}/system"\
  local policy_json='"'"'[]'"'"' restore_hashes="${dir}/restore-hooks.sha256" restore_count=0' "$OUT"
sed -i 's/readonly APP_VERSION="1.3.1"/readonly APP_VERSION="1.3.2"/' "$OUT"
chmod 0755 "$OUT"

echo "v1.3.2 candidate SHA256: $(sha256sum "$OUT" | awk '{print $1}')" >&2
printf '%s\n' "$OUT"
