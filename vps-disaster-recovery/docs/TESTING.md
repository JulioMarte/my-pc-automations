# Test strategy

The suite follows a recovery-first hierarchy:

1. **Static correctness** — parsing, version and validation helpers, calendar generation.
2. **Protocol integration** — real Restic talking to a real S3-compatible object store (MinIO).
3. **Data integrity** — restored files are compared by SHA-256, not merely by command exit status.
4. **Application consistency** — PostgreSQL is populated, logically dumped by the candidate, destroyed, recreated, restored, and compared by a deterministic database checksum.
5. **Repository integrity** — `restic check` reads repository data.
6. **DR artifact test** — `dr-plan` and `dr-test` execute against the exact produced snapshot.
7. **Performance/regression** — first backup, incremental backup, restore time and repository growth are recorded as artifacts.

## What should become the next test tier

A full Coolify recovery is intentionally separated from PR CI because it changes the whole runner and is significantly slower. A manual/scheduled workflow should install Coolify on a disposable Ubuntu runner or dedicated ephemeral VM, deploy a small fixture stack (app + PostgreSQL + persistent volume), back it up, destroy state, run `disaster-recovery --execute`, and validate HTTP/database checksums.

For production acceptance, additionally perform a periodic restore into a completely separate VPS. CI can detect many regressions, but it cannot model provider networking, DNS, firewall, disk layout, or every third-party application.
