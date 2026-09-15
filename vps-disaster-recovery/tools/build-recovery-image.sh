#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VPS_BACKUP_SCRIPT=${VPS_BACKUP_SCRIPT:-"$(bash "$ROOT/tools/materialize-candidate.sh")"}
BASE_IMAGE_URL=${BASE_IMAGE_URL:-https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img}
BASE_SUMS_URL=${BASE_SUMS_URL:-https://cloud-images.ubuntu.com/noble/current/SHA256SUMS}
OUTPUT=${OUTPUT:-"$ROOT/build/vps-recovery-ubuntu-24.04-amd64.qcow2"}
DISK_SIZE=${DISK_SIZE:-20G}
S3_URI=${S3_URI:-}
S3_ENDPOINT=${S3_ENDPOINT:-}
S3_REGION=${S3_REGION:-us-east-1}
AWS_PROFILE=${AWS_PROFILE:-}
PRESIGN_SECONDS=${PRESIGN_SECONDS:-604800}
DO_UPLOAD=false
DO_PRESIGN=false
WORKDIR=""

usage() {
  cat <<'HELP'
Build a provider-importable, secret-free QCOW2 disaster-recovery image.

Usage:
  sudo ./tools/build-recovery-image.sh [options]

Options:
  --base-url URL           Cloud QCOW2 source (default Ubuntu 24.04 Noble current)
  --sums-url URL           Official SHA256SUMS URL for the base image
  --output FILE.qcow2      Output path
  --disk-size SIZE         Virtual disk size (default 20G, sparse)
  --upload S3_URI          Upload final image, e.g. s3://bucket/recovery/vps-recovery.qcow2
  --endpoint URL           S3-compatible endpoint for aws CLI
  --region REGION          S3 region
  --presign                Print a temporary HTTPS download URL after upload
  --presign-seconds SEC    Presign lifetime (default 604800 / 7 days)

Requirements: curl, sha256sum, qemu-img, virt-customize, python3.
For --upload/--presign: aws CLI.

Security model:
  - The image contains the pinned vps-backup recovery engine only.
  - The official Ubuntu cloud image already supplies cloud-init; recovery-bootstrap
    installs runtime dependencies after boot. Image customization is intentionally
    offline so the builder does not depend on libguestfs network access.
  - It NEVER embeds S3 keys, Restic passwords, Coolify APP_KEY, SSH private keys or API tokens.
  - Supply recovery secrets after boot or through one-time cloud-init/user-data.
HELP
}

die(){ printf '[ERR] %s\n' "$*" >&2; exit 1; }
info(){ printf '[INFO] %s\n' "$*" >&2; }
need(){ command -v "$1" >/dev/null 2>&1 || die "Missing dependency: $1"; }
cleanup(){ [[ -n "$WORKDIR" && -d "$WORKDIR" ]] && rm -rf "$WORKDIR"; }
trap cleanup EXIT

while (($#)); do
  case "$1" in
    --base-url) [[ $# -ge 2 ]] || die '--base-url needs value'; BASE_IMAGE_URL=$2; shift 2 ;;
    --sums-url) [[ $# -ge 2 ]] || die '--sums-url needs value'; BASE_SUMS_URL=$2; shift 2 ;;
    --output) [[ $# -ge 2 ]] || die '--output needs value'; OUTPUT=$2; shift 2 ;;
    --disk-size) [[ $# -ge 2 ]] || die '--disk-size needs value'; DISK_SIZE=$2; shift 2 ;;
    --upload) [[ $# -ge 2 ]] || die '--upload needs s3:// URI'; S3_URI=$2; DO_UPLOAD=true; shift 2 ;;
    --endpoint) [[ $# -ge 2 ]] || die '--endpoint needs URL'; S3_ENDPOINT=$2; shift 2 ;;
    --region) [[ $# -ge 2 ]] || die '--region needs value'; S3_REGION=$2; shift 2 ;;
    --presign) DO_PRESIGN=true; shift ;;
    --presign-seconds) [[ $# -ge 2 ]] || die '--presign-seconds needs value'; PRESIGN_SECONDS=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ $OUTPUT == *.qcow2 ]] || die 'Output must end in .qcow2.'
[[ -x $VPS_BACKUP_SCRIPT ]] || die "vps-backup candidate not executable: $VPS_BACKUP_SCRIPT"
[[ $BASE_IMAGE_URL == https://* && $BASE_SUMS_URL == https://* ]] || die 'Base image and checksum URLs must use HTTPS.'
[[ $PRESIGN_SECONDS =~ ^[1-9][0-9]*$ ]] || die 'Invalid presign seconds.'
need curl; need sha256sum; need qemu-img; need virt-customize; need python3
if $DO_UPLOAD || $DO_PRESIGN; then need aws; fi
if $DO_PRESIGN && ! $DO_UPLOAD && [[ -z $S3_URI ]]; then die '--presign requires --upload S3_URI or S3_URI env'; fi

WORKDIR=$(mktemp -d /var/tmp/vps-recovery-image.XXXXXX)
base="$WORKDIR/base.img"
sums="$WORKDIR/SHA256SUMS"
name=${BASE_IMAGE_URL##*/}

info "Downloading base image: $BASE_IMAGE_URL"
curl --fail --location --proto '=https' --tlsv1.2 --retry 5 --retry-all-errors --output "$base" "$BASE_IMAGE_URL"
curl --fail --location --proto '=https' --tlsv1.2 --retry 5 --retry-all-errors --output "$sums" "$BASE_SUMS_URL"
expected=$(awk -v n="$name" '$2==n || $2=="*"n {print $1; exit}' "$sums")
[[ $expected =~ ^[0-9a-fA-F]{64}$ ]] || die "Could not find SHA256 for $name in $BASE_SUMS_URL"
actual=$(sha256sum "$base" | awk '{print $1}')
[[ ${actual,,} == ${expected,,} ]] || die 'Base image SHA256 mismatch'
info "Base SHA256 verified: $actual"

mkdir -p "$(dirname "$OUTPUT")"
qemu-img convert -p -f qcow2 -O qcow2 -o compat=1.1,lazy_refcounts=on "$base" "$OUTPUT"
qemu-img resize "$OUTPUT" "$DISK_SIZE"

marker="$WORKDIR/recovery-image.txt"
cat > "$marker" <<MARKER
vps-recovery-image=1
built_at=$(date --iso-8601=seconds)
base_url=$BASE_IMAGE_URL
base_sha256=$actual
vps_backup_sha256=$(sha256sum "$VPS_BACKUP_SCRIPT" | awk '{print $1}')
customization=offline
MARKER

# Deliberately do not use --install or --network here. The trusted Ubuntu cloud
# image already contains cloud-init. recovery-bootstrap installs ca-certificates,
# curl, jq, rsync and Restic after the VM gets its provider network. Keeping image
# construction offline makes it deterministic and avoids libguestfs/passt network
# failures on CI/build hosts.
virt-customize -a "$OUTPUT" \
  --copy-in "$VPS_BACKUP_SCRIPT:/usr/local/sbin" \
  --copy-in "$marker:/etc" \
  --run-command "mv /usr/local/sbin/$(basename "$VPS_BACKUP_SCRIPT") /usr/local/sbin/vps-backup" \
  --chmod '0755:/usr/local/sbin/vps-backup' \
  --run-command 'test -x /usr/bin/cloud-init' \
  --run-command 'cloud-init clean --logs --seed || true' \
  --run-command 'rm -f /etc/ssh/ssh_host_* || true' \
  --run-command 'truncate -s 0 /etc/machine-id || true' \
  --run-command 'rm -f /var/lib/dbus/machine-id || true'

qemu-img check "$OUTPUT" >/dev/null
format=$(qemu-img info --output=json "$OUTPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["format"])')
[[ $format == qcow2 ]] || die 'Output is not QCOW2'
chmod 0600 "$OUTPUT"
sha=$(sha256sum "$OUTPUT" | awk '{print $1}')
printf '%s  %s\n' "$sha" "$(basename "$OUTPUT")" > "${OUTPUT}.sha256"
chmod 0644 "${OUTPUT}.sha256"
info "Recovery image ready: $OUTPUT"
info "SHA256: $sha"

if $DO_UPLOAD; then
  [[ $S3_URI == s3://*/*.qcow2 ]] || die '--upload must point to an s3://.../*.qcow2 object'
  aws_args=(--region "$S3_REGION")
  [[ -n $S3_ENDPOINT ]] && aws_args+=(--endpoint-url "$S3_ENDPOINT")
  [[ -n $AWS_PROFILE ]] && aws_args+=(--profile "$AWS_PROFILE")
  info "Uploading QCOW2 to $S3_URI"
  aws "${aws_args[@]}" s3 cp "$OUTPUT" "$S3_URI" --only-show-errors
  aws "${aws_args[@]}" s3 cp "${OUTPUT}.sha256" "${S3_URI}.sha256" --only-show-errors
fi

if $DO_PRESIGN; then
  aws_args=(--region "$S3_REGION")
  [[ -n $S3_ENDPOINT ]] && aws_args+=(--endpoint-url "$S3_ENDPOINT")
  [[ -n $AWS_PROFILE ]] && aws_args+=(--profile "$AWS_PROFILE")
  printf '\nTemporary image URL (%ss):\n' "$PRESIGN_SECONDS"
  aws "${aws_args[@]}" s3 presign "$S3_URI" --expires-in "$PRESIGN_SECONDS"
fi
