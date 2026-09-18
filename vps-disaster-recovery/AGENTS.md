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
