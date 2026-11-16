---
applyTo: "**/*.sh"
---

- Aplicar `vps-disaster-recovery/AGENTS.md` y `local-proxy/AGENTS.md` segun el
  path, ademas del `AGENTS.md` raiz.
- Los `*.sh` van en LF (ver `.gitattributes`); un shebang CRLF rompe en Linux.
- No usar `pkill` con el patron en la linea de comandos: el propio proceso hace
  match y se auto-mata.
- En `vps-disaster-recovery`, `tests/static.sh` es el gate obligatorio antes de
  integrar.
- No reintroducir `restic check --help | grep -q ...`; bajo `pipefail` provoca
  SIGPIPE y falsos negativos (usar `grep -c ... >/dev/null`).
