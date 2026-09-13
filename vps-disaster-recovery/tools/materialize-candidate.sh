#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUT=${1:-"$ROOT/build/vps-backup-v1.3.sh"}
mkdir -p "$(dirname "$OUT")"
cat "$ROOT"/candidate/part-* | base64 -d | gzip -dc > "$OUT"
chmod 0755 "$OUT"
(
  cd "$(dirname "$OUT")"
  printf '%s  %s\n' "$(awk '{print $1}' "$ROOT/candidate/SHA256SUMS")" "$(basename "$OUT")" | sha256sum -c -
)
printf '%s\n' "$OUT"
