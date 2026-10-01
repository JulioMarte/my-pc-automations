# Test strategy

The suite follows a recovery-first hierarchy:

1. **Static correctness** — parsing, version and validation helpers, calendar generation.
2. **Protocol integration** — real Restic talking to a real S3-compatible object store (MinIO).
3. **Data integrity** — restored files are compared by SHA-256, not merely by command exit status.
4. **Application consistency** — PostgreSQL 16 and MariaDB 11.4 are populated, dumped by the candidate, destroyed, recreated, restored, and compared by deterministic database checksums.
5. **Repository integrity** — `restic check` reads repository data.
6. **DR artifact test** — `dr-plan` and `dr-test` execute against the exact produced snapshot.
7. **Fresh-host recovery** — a QCOW2 image boots under QEMU with cloud-init and performs a same-OS restore from TLS S3, then validates restored content by SHA-256.
8. **Performance/regression** — first backup, incremental backup, restore time and repository growth are recorded as artifacts.
9. **Release identity** — `tools/package-release.sh` rematerializes the exact candidate and verifies `candidate/RELEASE_SHA256` before producing a testable bundle.

## Gate de release

La release de software se considera apta para un drill real cuando todos los
jobs de `VPS Disaster Recovery CI` son verdes y el job agregado
`Release candidate bundle` publica el candidato exacto.

El drill real se ejecuta siguiendo `docs/production-drill.md`.

## What should become the next test tier

A full Coolify recovery is intentionally separated from PR CI because it changes the whole runner and is significantly slower. A manual/scheduled workflow should install Coolify on a disposable Ubuntu runner or dedicated ephemeral VM, deploy a small fixture stack (app + PostgreSQL + persistent volume), back it up, destroy state, run `disaster-recovery --execute`, and validate HTTP/database checksums.

For production acceptance, additionally perform a periodic restore into a completely separate VPS. CI can detect many regressions, but it cannot model provider networking, DNS, firewall, disk layout, or every third-party application.
