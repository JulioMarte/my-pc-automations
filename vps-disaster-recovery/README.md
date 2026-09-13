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
- A repeatable mixed-data benchmark measuring first backup, incremental backup, restore, repository growth, and dedup effectiveness.

MinIO is used only as the CI S3 endpoint. It exercises Restic's S3-compatible path without putting production Backblaze credentials in GitHub Actions. Backblaze-specific credentials should remain outside CI unless a dedicated disposable bucket/key is created later.

## Candidate snapshot

`candidate/part-*` is a gzip+base64 representation of the exact `vps-backup-v1.3.sh` candidate being evaluated. `tools/materialize-candidate.sh` reconstructs it and verifies the pinned SHA-256 before any test runs. This keeps the candidate immutable during a CI experiment.

Expected SHA-256:

`119a5ee2910c360b58b241a2f286152c68cf02a3398b7cb6ad8b3cf5517d28ac`

## Local commands

```bash
./tools/materialize-candidate.sh
sudo ./tests/static.sh
sudo ./tests/s3-roundtrip.sh
sudo ./tests/postgres-roundtrip.sh
sudo SIZE_MIB=256 SMALL_FILES=10000 ./tests/performance.sh
```

These integration tests are destructive **only inside their CI fixture namespaces** (`/srv/vps-dr-*`, `/etc/vps-backup`, `/var/lib/vps-backup`, Docker containers/volumes prefixed `ci-`). Do not run them on a production backup host.

## Interpretation

A green workflow means the backup engine works under the tested operating systems and fixtures. It does **not** yet prove that a specific production Coolify instance is recoverable. The next tier is a scheduled/manual disposable-host Coolify drill: fresh Coolify installation, control-plane restore, application/database/storage recovery, health checks, then destroy the test host.
