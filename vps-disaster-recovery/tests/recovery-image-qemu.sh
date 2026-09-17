#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck disable=SC1091
source "$ROOT/tests/lib.sh"

[[ $EUID -eq 0 ]] || { echo 'run as root' >&2; exit 1; }
for c in openssl socat qemu-system-x86_64 qemu-img cloud-localds virt-cat virt-ls; do
  command -v "$c" >/dev/null 2>&1 || { echo "missing test dependency: $c" >&2; exit 1; }
done

T=$(mktemp -d /var/tmp/vps-dr-qemu.XXXXXX)
SOCAT_PID=''
cleanup() {
  set +e
  [[ -n "$SOCAT_PID" ]] && kill "$SOCAT_PID" >/dev/null 2>&1
  stop_minio
  cleanup_candidate_state
  rm -rf /srv/vps-dr-qemu-source "$T"
  rm -f /usr/local/share/ca-certificates/vps-dr-ci.crt
  update-ca-certificates >/dev/null 2>&1 || true
}
# Root-owned artifacts would break actions/upload-artifact with EACCES when the
# run fails early, so normalize results/ permissions on every exit path.
fix_results_perms() {
  local f
  mkdir -p "$ROOT/results"
  chmod 0755 "$ROOT/results" || true
  for f in "$ROOT/results"/*.log "$ROOT/results"/*.json; do
    [[ -e "$f" ]] || continue
    chmod 0644 "$f" || true
  done
}
trap cleanup EXIT
trap 'rc=$?; write_failure_context /tmp/vps-dr-failure-context.txt; fix_results_perms; [[ -f "$T/qemu-console.log" ]] && tail -n 250 "$T/qemu-console.log" >&2 || true; exit $rc' ERR

install_candidate_dependencies
start_minio

# Add a small TLS terminator in front of MinIO. recovery-bootstrap deliberately
# rejects plain HTTP, so this exercises the production TLS-only path rather than
# weakening it for CI.
TLS="$T/tls"
mkdir -p "$TLS"
openssl req -x509 -newkey rsa:2048 -sha256 -days 2 -nodes \
  -keyout "$TLS/ca.key" -out "$TLS/ca.crt" -subj '/CN=VPS DR CI CA' >/dev/null 2>&1
openssl req -newkey rsa:2048 -nodes -keyout "$TLS/server.key" -out "$TLS/server.csr" \
  -subj '/CN=127.0.0.1' >/dev/null 2>&1
cat >"$TLS/server.ext" <<'EOF_EXT'
subjectAltName=IP:127.0.0.1,IP:10.0.2.2
extendedKeyUsage=serverAuth
EOF_EXT
openssl x509 -req -in "$TLS/server.csr" -CA "$TLS/ca.crt" -CAkey "$TLS/ca.key" \
  -CAcreateserial -out "$TLS/server.crt" -days 2 -sha256 -extfile "$TLS/server.ext" >/dev/null 2>&1
cat "$TLS/server.key" "$TLS/server.crt" >"$TLS/server.pem"
chmod 0600 "$TLS/server.pem" "$TLS/ca.key"

socat OPENSSL-LISTEN:9443,reuseaddr,fork,cert="$TLS/server.pem",verify=0 TCP:127.0.0.1:9000 \
  >"$T/socat.log" 2>&1 &
SOCAT_PID=$!
for _ in $(seq 1 30); do
  curl -fsS --cacert "$TLS/ca.crt" https://127.0.0.1:9443/minio/health/live >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS --cacert "$TLS/ca.crt" https://127.0.0.1:9443/minio/health/live >/dev/null
install -m 0644 "$TLS/ca.crt" /usr/local/share/ca-certificates/vps-dr-ci.crt
update-ca-certificates >/dev/null

# Create a real Restic recovery point on the same OS family the guest will use.
MINIO_ENDPOINT=https://127.0.0.1:9443
cleanup_candidate_state
install -d -m 0755 /srv/vps-dr-qemu-source
printf '%s\n' 'recovered-from-s3-v1.4.3' > /srv/vps-dr-qemu-source/marker.txt
SOURCE_SHA=$(sha256sum /srv/vps-dr-qemu-source/marker.txt | awk '{print $1}')
write_ci_config ci-qemu ci-qemu /srv/vps-dr-qemu-source false
init_repo
"$SCRIPT" backup
SID=$(cat /var/lib/vps-backup/state/last_backup_snapshot_id)
[[ -n "$SID" ]]
"$SCRIPT" dr-plan --snapshot "$SID"

IMAGE="$T/vps-recovery.qcow2"
VPS_BACKUP_SCRIPT="$SCRIPT" OUTPUT="$IMAGE" DISK_SIZE=16G bash "$ROOT/tools/build-recovery-image.sh"
qemu-img check "$IMAGE" >/dev/null

# The reusable image itself must not contain CI recovery credentials or a
# pre-existing vps-backup configuration. Secrets are provided only in NoCloud
# user-data for this disposable boot.
! virt-ls -a "$IMAGE" /etc/vps-backup >/dev/null 2>&1
! virt-cat -a "$IMAGE" /usr/local/sbin/vps-backup | grep -Fq "$MINIO_PASSWORD"
! virt-cat -a "$IMAGE" /usr/local/sbin/vps-backup | grep -Fq 'ci-restic-password-please-change'
virt-cat -a "$IMAGE" /etc/recovery-image.txt | grep -Fq "vps_backup_sha256=$(sha256sum "$SCRIPT" | awk '{print $1}')"

USER_DATA="$T/user-data"
META_DATA="$T/meta-data"
CA_INDENTED=$(sed 's/^/      /' "$TLS/ca.crt")
cat >"$USER_DATA" <<EOF_USER
#cloud-config
write_files:
  - path: /usr/local/share/ca-certificates/vps-dr-ci.crt
    owner: root:root
    permissions: '0644'
    content: |
$CA_INDENTED
runcmd:
  - [ sh, -c, 'update-ca-certificates >/dev/null 2>&1' ]
  - [ sh, -c, 'rm -rf /srv/vps-dr-qemu-source' ]
  - [ bash, -lc, 'set +e; printf "RECOVER-ci-qemu\\n" | env VPS_RECOVERY_S3_ACCESS_KEY="$MINIO_USER" VPS_RECOVERY_S3_SECRET_KEY="$MINIO_PASSWORD" VPS_RECOVERY_RESTIC_PASSWORD="ci-restic-password-please-change" /usr/local/sbin/vps-backup recovery-bootstrap --non-interactive --require-same-os --execute --snapshot "$SID" --provider s3 --endpoint https://10.0.2.2:9443 --region us-east-1 --bucket "$TEST_BUCKET" --prefix ci-qemu --backup-id ci-qemu --bucket-lookup path > /var/tmp/recovery-bootstrap.log 2>&1; rc=\$?; printf "%s\\n" "\$rc" > /var/tmp/recovery-bootstrap.rc; sync; exit 0' ]
  - [ bash, -lc, 'test -f /srv/vps-dr-qemu-source/marker.txt && sha256sum /srv/vps-dr-qemu-source/marker.txt > /var/tmp/recovered-marker.sha256' ]
  - [ bash, -lc, '/usr/local/sbin/vps-backup version > /var/tmp/vps-backup-version.txt' ]
  - [ bash, -lc, 'test -s /etc/machine-id' ]
  - [ bash, -lc, 'ls /etc/ssh/ssh_host_*_key >/dev/null 2>&1' ]
  - [ bash, -lc, 'printf PASS > /var/tmp/vps-dr-qemu-pass' ]
power_state:
  mode: poweroff
  message: VPS DR CI complete
  timeout: 60
  condition: true
EOF_USER
cat >"$META_DATA" <<'EOF_META'
instance-id: vps-dr-ci-001
local-hostname: vps-dr-recovery-ci
EOF_META
SEED="$T/seed.img"
cloud-localds "$SEED" "$USER_DATA" "$META_DATA"

# TCG is slower than KVM but available on standard hosted runners and gives us
# an actual kernel/systemd/cloud-init boot rather than merely inspecting files.
set +e
timeout --signal=TERM --kill-after=30s 900 \
  qemu-system-x86_64 \
    -machine accel=tcg \
    -cpu max -smp 2 -m 2048 \
    -nographic -no-reboot \
    -drive "file=$IMAGE,format=qcow2,if=virtio" \
    -drive "file=$SEED,format=raw,if=virtio,readonly=on" \
    -nic user,model=virtio-net-pci \
    >"$T/qemu-console.log" 2>&1
QEMU_RC=$?
set -e
[[ $QEMU_RC -eq 0 ]] || { echo "QEMU exited rc=$QEMU_RC" >&2; tail -n 250 "$T/qemu-console.log" >&2; exit 1; }

# Always extract guest-side diagnostics before validating success markers. This
# makes a failed recovery actionable instead of losing the only useful log when
# cloud-init continues to poweroff after an runcmd failure.
mkdir -p "$ROOT/results"
virt-cat -a "$IMAGE" /var/tmp/recovery-bootstrap.log > "$ROOT/results/recovery-bootstrap-qemu.log" 2>/dev/null || true
virt-cat -a "$IMAGE" /var/log/cloud-init-output.log > "$ROOT/results/cloud-init-output-qemu.log" 2>/dev/null || true
virt-cat -a "$IMAGE" /var/log/cloud-init.log > "$ROOT/results/cloud-init-qemu.log" 2>/dev/null || true
cp "$T/qemu-console.log" "$ROOT/results/qemu-console.log"
RECOVERY_RC=$(virt-cat -a "$IMAGE" /var/tmp/recovery-bootstrap.rc 2>/dev/null | tr -d '\r\n' || true)
if [[ "$RECOVERY_RC" != 0 ]]; then
  echo "guest recovery-bootstrap failed rc=${RECOVERY_RC:-missing}" >&2
  [[ -s "$ROOT/results/recovery-bootstrap-qemu.log" ]] && tail -n 250 "$ROOT/results/recovery-bootstrap-qemu.log" >&2 || true
  exit 1
fi

[[ "$(virt-cat -a "$IMAGE" /var/tmp/vps-dr-qemu-pass)" == PASS ]]
[[ "$(virt-cat -a "$IMAGE" /var/tmp/vps-backup-version.txt | tr -d '\r\n')" == 'vps-backup v1.4.3' ]]
RECOVERED_SHA=$(virt-cat -a "$IMAGE" /var/tmp/recovered-marker.sha256 | awk '{print $1}')
[[ "$RECOVERED_SHA" == "$SOURCE_SHA" ]]
[[ -n "$(virt-cat -a "$IMAGE" /etc/machine-id | tr -d '\r\n')" ]]
virt-ls -a "$IMAGE" /etc/ssh | grep -Eq '^ssh_host_.*_key$'

cat > "$ROOT/results/recovery-image-qemu.json" <<EOF_JSON
{"snapshot":"$SID","candidate_sha256":"$(sha256sum "$SCRIPT" | awk '{print $1}')","source_sha256":"$SOURCE_SHA","restored_sha256":"$RECOVERED_SHA","qemu":"PASS","cloud_init":"PASS","same_os_recovery":"PASS"}
EOF_JSON
fix_results_perms
if [[ -n "${SUDO_UID:-}" && -n "${SUDO_GID:-}" ]]; then
  chown -R "$SUDO_UID:$SUDO_GID" "$ROOT/results" || true
fi

echo "QEMU SAME-OS RECOVERY PASS snapshot=${SID:0:12}"
