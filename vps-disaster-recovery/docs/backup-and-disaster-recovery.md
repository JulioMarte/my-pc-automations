# VPS Backup + Disaster Recovery v1.4.1

This project deliberately separates **data backup** from **recovery acceleration**.

- Restic + S3 is the authoritative, encrypted, provider-independent backup.
- Logical/native database dumps protect transactional state.
- Docker persistent storage is classified explicitly; database volumes are not treated as portable live-file backups.
- A QCOW2 recovery image is optional. It is a clean bootable recovery appliance, not a live clone of the old VPS.
- Provider snapshots can be an additional fast-path, but they are never the only recovery copy.

## Backup policy profiles

`vps-backup install` / `reconfigure` offers four profiles. `vps-backup recommend` prints the policy guidance again later.

| Profile | Full backup interval | DB RPO target | System / volume RPO | Target RTO | Retention |
|---|---:|---:|---:|---:|---|
| economy | 12 h | 12 h | 26 h | 180 min | 7 daily / 4 weekly / 6 monthly / 1 yearly |
| balanced | 6 h | 6 h | 12 h | 90 min | 14 / 8 / 12 / 2 |
| critical | 2 h | 2 h | 6 h | 60 min | 30 / 12 / 12 / 3 |
| custom | operator-defined | operator-defined | operator-defined | operator-defined | operator-defined |

These are defaults, not universal SLAs. A database that cannot lose two hours of data should use engine-native continuous/near-continuous protection (for example PostgreSQL WAL/PITR or MySQL/MariaDB binlog-based recovery) in addition to this system. Increasing whole-VPS Restic frequency blindly is not a substitute for database PITR.

### Cost guidance

For a personal VPS, lab, cache-heavy workload, or data that can be recreated, `economy` is usually sufficient.

For ordinary production Coolify workloads, `balanced` is the default recommendation. Restic deduplication keeps unchanged system data inexpensive while still giving multiple restore points per day.

Use `critical` when bookings, customer transactions, or operational records make a 6–12 hour loss unacceptable. Expect more database-dump churn, I/O, object operations, and storage growth.

## Recovery path A — clean VPS, same base OS

This is the cheapest and most provider-independent path.

1. Provision a clean Debian/Ubuntu VPS with the **same distro ID, VERSION_ID and architecture** as the protected server.
2. Copy the v1.4.1 script to the new VPS.
3. Run:

```bash
sudo ./vps-backup-v1.4.1.sh recovery-bootstrap --require-same-os
```

The command installs prerequisites, asks for S3/Restic recovery credentials, opens the existing repository, selects the latest system snapshot and validates the DR manifest. It does **not** execute destructive recovery without `--execute`.

After the plan passes:

```bash
sudo vps-backup recovery-bootstrap --require-same-os --execute --snapshot SNAPSHOT_ID
```

`rebuild-from-s3` is an alias that always adds the same-OS requirement.

The recovery engine deliberately does not overwrite provider networking, `/etc/fstab` UUIDs, machine-id, SSH host keys, cloud-init provider state, boot loader or provider agents.

## Recovery path B — QCOW2 recovery image + S3 data

Use this when the VPS provider supports custom disk images and you want a faster, predictable bootstrap.

Build the image on a Linux workstation/VM with `qemu-img` and libguestfs:

```bash
sudo ./tools/build-recovery-image.sh \
  --output ./vps-recovery-ubuntu-24.04-amd64.qcow2
```

The builder:

1. downloads an official cloud image over HTTPS;
2. verifies it against the publisher SHA256SUMS;
3. converts it to QCOW2;
4. embeds the exact tested `vps-backup` candidate;
5. preserves cloud-init and installs qemu-guest-agent;
6. removes machine-id and SSH host keys so the new VM regenerates identity;
7. runs `qemu-img check`;
8. writes a SHA256 sidecar.

The image contains **no recovery credentials**.

### Upload image to S3

With AWS CLI credentials configured for the target S3-compatible provider:

```bash
sudo ./tools/build-recovery-image.sh \
  --output ./vps-recovery-ubuntu-24.04-amd64.qcow2 \
  --upload s3://MY_BUCKET/recovery/vps-recovery-ubuntu-24.04-amd64.qcow2 \
  --endpoint https://s3.REGION.backblazeb2.com \
  --region REGION \
  --presign
```

The temporary signed URL can be supplied to a VPS provider that imports an image from a URL. Rotate/revoke the image-upload key after use when practical.

For Contabo, current documentation states that custom images for VPS/VDS support **QCOW2 and ISO**, must be **x86-64**, and need VirtIO disk/network support. The custom-image add-on may be required. Contabo's API can also create a custom image from a download URL.

References:
- https://help.contabo.com/en/support/solutions/articles/103000274171-can-i-use-custom-images-on-my-server-
- https://help.contabo.com/en/support/solutions/articles/103000274217-how-do-i-install-a-custom-image-on-my-server-
- https://api.contabo.com/

## Optional one-time cloud-init recovery

`examples/recovery-cloud-init.example.yaml` can execute recovery automatically on first boot. It contains placeholders for S3 and Restic credentials.

Provider user-data can remain visible in a provider control plane. For high-value credentials, the safer default is to boot the image, SSH to it, run `recovery-bootstrap` interactively, and rotate the dedicated recovery S3 key afterward.

## What “successful disaster recovery” means

The script may report core recovery success only after:

- the selected Restic system snapshot and remote DR manifest validate;
- declared database backups meet freshness policy;
- Coolify control-plane DB / APP_KEY artifacts validate when Coolify is protected;
- declared persistent storage is restored or explicitly ignored;
- restore-hook hashes verify before privileged execution;
- restored databases complete without error;
- applications/services are started only after state is restored;
- runtime/container health checks pass.

DNS cutover is intentionally separate. A green restore is not proof of business-level application correctness; HTTP/API/login/transaction tests should be performed before traffic is moved.

## Recovery credentials that must exist outside the dead VPS

At minimum keep these in a password manager or offline recovery kit:

- BACKUP_ID
- S3 endpoint / region / bucket / prefix
- S3 recovery key ID + secret
- Restic repository password

For Coolify, the historical APP_KEY is captured inside the encrypted Restic repository, but keeping a separately secured copy is still sensible.

## What this system does not claim

It is not a bit-for-bit bare-metal imaging product. It does not make a live `dd` copy of the root disk, and it does not use `/var/lib/docker/overlay2` as the primary portable backup. Those approaches are fragile across providers, disk sizes and runtime state.

Provider snapshots remain useful as an additional recovery accelerator. The off-site S3/Restic copy remains the authoritative provider-independent recovery path.
