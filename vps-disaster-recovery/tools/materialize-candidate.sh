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
(
  cd "$(dirname "$OUT")"
  printf '%s  %s\n' "$(awk '{print $1}' "$ROOT/candidate/SHA256SUMS")" "$(basename "$OUT")" | sha256sum -c - >&2
)
printf '%s\n' "$OUT"
