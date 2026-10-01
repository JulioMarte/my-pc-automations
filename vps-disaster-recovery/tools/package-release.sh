#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DIST=${1:-"$ROOT/dist"}
VERSION="1.4.3"
SCRIPT_NAME="vps-backup-v${VERSION}.sh"
SCRIPT_PATH="$DIST/$SCRIPT_NAME"
CHECKSUM_SOURCE="$ROOT/candidate/RELEASE_SHA256"

umask 022
mkdir -p "$DIST"
rm -f "$SCRIPT_PATH" "$DIST/SHA256SUMS" "$DIST/PRODUCTION-DRILL.md" \
  "$DIST/recovery-cloud-init.example.yaml" "$DIST/RELEASE-MANIFEST.txt"

bash "$ROOT/tools/materialize-candidate.sh" "$SCRIPT_PATH" >/dev/null

expected=$(awk 'NF{print $1; exit}' "$CHECKSUM_SOURCE")
actual=$(sha256sum "$SCRIPT_PATH" | awk '{print $1}')
[[ "$expected" =~ ^[0-9a-f]{64}$ ]] || { echo "release checksum inválido" >&2; exit 1; }
[[ "$actual" == "$expected" ]] || {
  echo "release checksum mismatch: expected=$expected actual=$actual" >&2
  exit 1
}

chmod 0755 "$SCRIPT_PATH"
cp "$CHECKSUM_SOURCE" "$DIST/SHA256SUMS"
cp "$ROOT/docs/production-drill.md" "$DIST/PRODUCTION-DRILL.md"
cp "$ROOT/examples/recovery-cloud-init.example.yaml" "$DIST/recovery-cloud-init.example.yaml"

cat > "$DIST/RELEASE-MANIFEST.txt" <<EOF
product=vps-backup
version=$VERSION
sha256=$actual
supported_os=Ubuntu_22.04,Ubuntu_24.04,Debian_12,Debian_13
recovery_paths=same-os-portable,coolify,qcow2-bootstrap
authoritative_backup=Restic_S3
EOF

(
  cd "$DIST"
  sha256sum -c SHA256SUMS
)

printf '%s\n' "$DIST"
