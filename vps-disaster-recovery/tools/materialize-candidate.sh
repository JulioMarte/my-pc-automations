#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUT=${1:-"$ROOT/build/vps-backup-v1.4.1.sh"}
EXPECTED_V131=9e2ee8924e403e0ab4424beb6e0267d8c36673e66a902f8353ac3933838c19c9
EXPECTED_V132=7eda0bac8d39898fbeb97997b123480b37443e2393e9d0b104425789654e5e88
EXPECTED_V133=1a534cc0cadb6baee0508f5c916dc1554b840c2266ef2eaeafce0dfc6948563c
EXPECTED_V141=9adeb0884d4b0c2fede1e9ccae9a06254d2d96c693dbb84b7d523afd0d7c17fd
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
trap 'rm -f "$PATCH_TMP"' EXIT
base64 -d "$ROOT/patches/v1.4.1.patch.gz.b64" | gzip -dc > "$PATCH_TMP"
patch --batch --forward --silent "$OUT" < "$PATCH_TMP"
chmod 0755 "$OUT"
actual=$(sha256sum "$OUT" | awk '{print $1}')
[[ "$actual" == "$EXPECTED_V141" ]] || { echo "v1.4.1 checksum mismatch: $actual" >&2; exit 1; }
grep -qx 'readonly APP_VERSION="1.4.1"' "$OUT" || { echo 'Unexpected v1.4.1 version marker' >&2; exit 1; }
! grep -Eq '^readonly VERSION=' "$OUT" || { echo 'Unsafe VERSION constant would collide with /etc/os-release' >&2; exit 1; }
echo "v1.4.1 candidate SHA256: $actual" >&2
printf '%s\n' "$OUT"
