# AGENTS.md - vps-disaster-recovery

Aplica a `vps-disaster-recovery/**` ademas del `AGENTS.md` raiz. No contradice la
politica del repositorio; solo anade reglas locales mas estrictas.

## Reglas

- **Bash puro, sin `npm` ni dependencias de runtime.** El proyecto se ejecuta
  con las herramientas del sistema (bash, git, restic, Docker cuando aplica).
- **Gate obligatorio**: `tests/static.sh` (o `make static`) debe pasar antes de
  integrar. Verifica el SHA-256 del candidato contra `candidate/RELEASE_SHA256`,
  sintaxis bash, ShellCheck a nivel error, invariantes de helpers y la matriz de
  calendario systemd.
- **Candidato determinista**: no editar `candidate/` a mano. Se reproduce con
  `tools/materialize-candidate.sh` (base v1.4.2 verificada + overlay same-OS
  v1.4.3) y el SHA final se fija en `candidate/RELEASE_SHA256`.
- **Tests destructivos**: `s3-roundtrip.sh`, `postgres-roundtrip.sh`,
  `mariadb-roundtrip.sh`, `docker-policy.sh`, `ops-integrations.sh`,
  `performance.sh` y `recovery-image-qemu.sh` requieren `sudo`, Docker/MinIO y
  escriben en namespaces propios (`/srv/vps-dr-*`, `/etc/vps-backup`,
  `/var/lib/vps-backup`, contenedores/volumenes `ci-*`). **Advertencia: no
  ejecutarlos en un host de backup de produccion.**
- **Fin de linea**: todos los `*.sh` van en LF (ver `.gitattributes`); un shebang
  CRLF rompe en Linux.
- **No usar `pkill`** con el patron en la linea de comandos: el propio proceso
  hace match y se auto-mata.
- **No reintroducir el flake de pipefail**: el probe de capacidades de Restic
  debe consumir toda la salida (`grep -c ... >/dev/null`), nunca
  `restic check --help | grep -q ...`.
- **Instalacion de Restic**: `modules/restic-install.sh` reemplaza
  `install_official_restic`/`ensure_restic_min_version` del base. Crea `$TMP_DIR`
  antes del `mktemp` (install corre antes de `ensure_directories`) e instala la
  ultima version publicada de Restic, con fallback a `RESTIC_BOOTSTRAP_VERSION`
  y verificacion SHA256SUMS. `RESTIC_VERSION=X.Y.Z` fija una version. Su blob
  Git esta fijado en `tools/materialize-candidate.sh`.
- **Borrador del instalador**: `modules/install-checkpoint.sh` +
  `tools/install-checkpoint.awk` guardan las respuestas de `configure_interactive`
  por secciones en `/etc/vps-backup/install-draft.{conf,cred}` (0600) para
  reanudar tras una interrupcion, y muestran la contrasena Restic generada en
  una corrida cortada. Las anclas del awk se validan (una vez cada una) contra el
  v1.4.3 real; si cambia el texto del base, el materializador falla.
- **Prompts dentro de bucles**: un `while read ...; done < <(lista)` redirige
  tambien la stdin de los prompts del cuerpo. `tools/workload-policy-stdin.awk`
  hace que `configure_workload_policy` lea sus listas por los fd 3 y 4. No
  anadir prompts dentro de bucles que leen de stdin.
- **Instalacion automatica**: `modules/auto-install.sh` + `tools/auto-install.awk`
  anaden `install --auto` (defaults recomendados, builtin para DB SQL, ignore con
  aviso para motores sin dump) y crean el token de Coolify con `artisan tinker`.
  Las claves S3 nunca se aceptan como opcion de linea de comandos.
- **Diagnostico e instalacion trazable**: `modules/install-diagnostics.sh` +
  `tools/install-diagnostics.awk` reemplazan `initialize_repository_interactive`
  (clasifica el fallo de `restic cat config` por codigo de salida y texto; nunca
  inicializa ante contrasena erronea o error desconocido en auto) y registran
  `install`/`reconfigure` en `/var/log/vps-backup/install-*.log` con trazas
  `[TRACE]`. Nada secreto debe imprimirse por stdout/stderr durante install: lo
  que deba verlo solo el operador va a `>&"$INSTALL_TTY_FD"`.
- **Cobertura de bind mounts**: `modules/bind-coverage.sh` hace que
  `validate_docker_bind_coverage` ignore sockets, dispositivos y rutas de runtime
  (`/run`, `/var/run`, `/proc`, `/sys`, `/dev`); p. ej. `/var/run/docker.sock` de
  coolify-proxy bloqueaba doctor y cada backup. El resto sigue fail-closed.
- **DR de Coolify en host nuevo**: `modules/coolify-dr-retarget.sh` reapunta el
  servidor `localhost` (id 0) de la base de datos de Coolify restaurada a ESTE host
  (IP de Tailscale propia si la original era de Tailscale; si no
  `host.docker.internal`; puerto de `sshd -T`) y marca como `exited` los estados
  heredados, antes de re-ejecutar el instalador. Sin esto, el Coolify restaurado
  gestionaba por SSH el host ORIGINAL: en una prueba con el original vivo actuaba
  sobre produccion. `start` de un recurso que la API da por running cae a
  `restart`. Probar DR con el original vivo exige ademas cortar el trafico del
  host nuevo hacia el original (IP publica y de Tailscale).
  Las DB builtin de un servicio de Coolify solo existen cuando arranca el servicio:
  `restore_policy_databases` arranca el servicio dueno, espera la DB sana, para el
  resto del stack, restaura y deja que el arranque normal lo levante. Una DB builtin
  fuera de Coolify que no existe en el host (p. ej. stack de Portainer) se salta con
  aviso; su dump queda en el bundle DR.
