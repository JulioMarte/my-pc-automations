# VPS Disaster Recovery Lab

CI laboratory for `vps-backup` on Debian/Ubuntu. This folder is intentionally isolated from the other automations in this repository.

## What the CI proves

The blocking CI uses real binaries and real protocols where practical:

- Bash parsing and ShellCheck error-level analysis.
- Systemd calendar generation across every supported backup interval/start-hour combination.
- Debian 12/13 compatibility smoke tests in clean containers.
- Ubuntu 22.04/24.04 end-to-end Restic backup -> S3-compatible MinIO -> restore -> checksum verification.
- Real `restic check --read-data-subset=1/1` and staged DR validation.
- PostgreSQL 16 logical backup and restore using the candidate's own Docker DB implementation.
- MariaDB 11.4 destruction/recovery using the candidate's own Docker DB implementation.
- A QCOW2 recovery image built, booted under QEMU with cloud-init, and driven through a same-OS portable recovery from a TLS S3 snapshot, validating the restored data by SHA-256.
- A repeatable mixed-data benchmark measuring first backup, incremental backup, restore, repository growth, and dedup effectiveness.

MinIO is used only as the CI S3 endpoint. It exercises Restic's S3-compatible path without putting production Backblaze credentials in GitHub Actions. Backblaze-specific credentials should remain outside CI unless a dedicated disposable bucket/key is created later.

## Candidate snapshot

`candidate/part-*` contains the immutable compressed v1.3.0 base payload. The toolchain derives the tested artifact in two verified stages:

1. `tools/materialize-v142.sh` reproduces the proven **v1.4.2** candidate deterministically (v1.3.1 regression fix where `VERSION` collided with `/etc/os-release`, plus the versioned patches) and verifies its SHA-256.
2. `tools/materialize-candidate.sh` reproduces that exact v1.4.2 base **byte-for-byte**, then applies the **v1.4.3** same-OS portable recovery overlay (content-addressed by Git blob), and `tests/static.sh` verifies the final artifact SHA-256 against `candidate/RELEASE_SHA256`.

This keeps the exact tested candidate reproducible and auditable.

Pinned v1.4.3 SHA-256:

`d3718839413ca99f48d887fa574ba13d980fecee6fa3477c6a9b3aaa5d2a9b57`

## Local commands

```bash
bash ./tools/materialize-candidate.sh
sudo bash ./tests/static.sh
sudo bash ./tests/s3-roundtrip.sh
sudo bash ./tests/postgres-roundtrip.sh
sudo SIZE_MIB=256 SMALL_FILES=10000 bash ./tests/performance.sh
```

These integration tests are destructive **only inside their CI fixture namespaces** (`/srv/vps-dr-*`, `/etc/vps-backup`, `/var/lib/vps-backup`, Docker containers/volumes prefixed `ci-`). Do not run them on a production backup host.

## Interpretation

A green workflow means the backup engine works under the tested operating systems and fixtures. It does **not** yet prove that a specific production Coolify instance is recoverable. The next tier is a scheduled/manual disposable-host Coolify drill: fresh Coolify installation, control-plane restore, application/database/storage recovery, health checks, then destroy the test host.
