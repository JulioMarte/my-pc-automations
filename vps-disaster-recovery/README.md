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

`candidate/part-*` contains the immutable compressed v1.3.0 base payload. `tools/materialize-candidate.sh` applies the small deterministic v1.3.1 regression fix discovered by CI (`VERSION` collided with `/etc/os-release`), then verifies the SHA-256 of the final artifact before any test runs. This keeps the exact tested candidate reproducible and auditable.

Expected v1.3.1 SHA-256:

`9e2ee8924e403e0ab4424beb6e0267d8c36673e66a902f8353ac3933838c19c9`

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
