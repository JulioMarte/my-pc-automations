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

`ac3fe5e38cc1961565bfc3fd97534a4dbf1181b789d8db933d22254e79ff827a`

## Instalacion automatica

`install --auto` responde cada pregunta con la opcion recomendada (se muestra como
`[AUTO] pregunta -> respuesta`) y crea el token de API de Coolify por si mismo:

```bash
sudo ./vps-backup-v1.4.3.sh install --auto   --endpoint https://<ACCOUNT_ID>.r2.cloudflarestorage.com --bucket vps-backups --region auto
```

- Solo pide por teclado las claves S3 si no estan ya guardadas (config previa o
  borrador de una instalacion interrumpida). Las claves nunca van como opcion.
- DB Docker postgres/mysql/mariadb -> `builtin`; otros motores (mongo...) -> `ignore`
  con aviso; volumenes -> `restic-live`; perfil `balanced`; modulo Coolify DR activo.
- Token Coolify: `vps-backup-dr` del usuario root, equipo raiz, permisos
  read/write/deploy, creado con `User::createToken` via `artisan tinker`. Reinstalar
  revoca el anterior con ese nombre y crea uno nuevo. En modo interactivo, Enter en
  la pregunta del token hace lo mismo.
- Si se interrumpe, relanzar reutiliza lo ya contestado.
- Repositorio: si la ruta del bucket esta vacia, se inicializa (en auto y por defecto
  en interactivo). Si ya hay un repositorio y la contrasena local no lo abre, nunca se
  inicializa. Credenciales rechazadas, bucket inexistente o red se reportan con la
  causa y el error real de Restic.

## Log y trazas de instalacion

`install` y `reconfigure` guardan toda la salida (sin colores) en
`/var/log/vps-backup/install-<UTC>-<pid>.log` (0600, root); `install-last.log` apunta a la
ultima. Un fallo imprime lineas `[TRACE]` con el codigo de salida, el comando y la pila
de funciones con numero de linea. La contrasena Restic generada se muestra solo en la
terminal, no en el log. Para reportar un fallo:

```bash
sudo cat /var/log/vps-backup/install-last.log
```

## Probar DR de Coolify con el host original vivo

La base de datos de Coolify restaurada apunta su servidor `localhost` al host original.
`disaster-recovery --execute` la reapunta a este host antes de arrancar Coolify
(`modules/coolify-dr-retarget.sh`): IP de Tailscale propia si la original era de
Tailscale (Tailscale debe estar activo en el host nuevo), si no `host.docker.internal`.
`VPS_BACKUP_DR_COOLIFY_LOCALHOST_IP` fuerza la IP (debe ser de este host). Aun asi, en una
prueba con el original en produccion:

- corta el trafico del host nuevo hacia el original (IP publica y de Tailscale) antes de
  `--execute`, y bloquea la salida a internet de los contenedores (`DOCKER-USER`) para que
  las apps restauradas no envien correo ni ejecuten webhooks por duplicado;
- al terminar, desactiva los timers de `vps-backup` en el host nuevo: comparte repositorio
  con el original.

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
