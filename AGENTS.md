# AGENTS.md

Reglas de trabajo para este repositorio (`my-pc-automations`).

## Flujo de ramas

```
feat/<feature>  --(tests + verificacion OK)-->  dev  --(PR + review)-->  main
```

- **`dev`**: rama de integracion y trabajo diario.
- **`main`**: release candidate. Solo recibe merges desde `dev` mediante PR.
- **Ramas de feature**: cada cambio nace en su propia rama creada desde `dev`
  (`feat/...`, `fix/...`, `chore/...`, `docs/...`).

### Reglas obligatorias

1. **Nunca** commitear ni hacer push directo a `main`.
2. **Antes de editar, crear la rama** (`git checkout -b <tipo>/<nombre>` desde `dev`).
   Nunca editar ni commitear directo en `dev`. Luego: implementar -> probar -> merge a `dev`.
3. **`dev` -> `main`** solo con **PR para review/aprobacion**, o si el usuario lo
   pide explicitamente. **Nunca** mergear a `main` por iniciativa propia.
4. **No** hacer `push` a `origin` salvo que el usuario lo pida.
5. Antes de integrar en `dev`: typecheck + tests en verde.
6. `main` esta protegida en GitHub (requiere PR; sin push directo, sin force-push,
   sin borrado).

## Proyecto `local-proxy`

- **TypeScript ESM**, sin dependencias de runtime. `src/*.ts` -> build a `dist/`
  con `npm run build`.
- **Runtime de produccion: Node.js** desde `dist/` (no Bun). Bun solo como
  tooling (`bun src/gateway.ts`, `bun test`, `bun --watch`).
- Comandos:
  - `npm run typecheck` - comprobacion de tipos (`tsc --noEmit`).
  - `npm test` - tests (`node --test` sobre `.ts`; ~134 tests, incluye user journeys).
  - `npm run test:journey` - solo las jornadas e2e (`test/journey.test.ts`).
  - `npm run stress` - generador de carga in-process (`scripts/stress.ts`).
  - `npm run build` - compila a `dist/`.
  - `npm run dev:gateway` / `npm run dev:exit` - desarrollo con `--watch`.
  - `npm run monitor` / `monitor:once` - alertas de salud (`scripts/monitor.ts`).
  - `npm run docker:build` / `docker:gateway` / `docker:exit` / `docker:e2e`.
  - `npm run service:install[:gateway|:exit]` / `service:uninstall` (Windows, admin).
- Endpoints:
  - Gateway: `GET /healthz` (liveness), `GET /readyz` (readiness),
    `GET /panel` (dashboard HTML; `PANEL_ENABLED`), `GET /__stats?token=`
    (requiere `STATS_TOKEN`), `GET /metrics` (Prometheus; `METRICS_TOKEN` opcional),
    `POST /__drain?token=`.
  - Exit: `GET /__health` (liveness), `GET /metrics`.
- **Health check multi-target**: `HEALTH_TARGETS` se prueba en orden aleatorio y basta con
  que uno responda; un destino caido no marca los exits como no sanos.
- **Operaciones**: Docker, servicio real (systemd/WinSW), alertas y panel; guias en
  `docs/` (`docker.md`, `service.md`, `alerts.md`, `testing.md`, `ci.md`). El servicio real
  y el arranque por Task Scheduler/cron **no deben usarse a la vez**.
- **Recarga en caliente**: el gateway recarga `PROXY_USERS`/`STATS_TOKEN`/`METRICS_TOKEN`
  y el exit `EXIT_USERS` al guardar `.env` (sin reiniciar). Puertos, timeouts,
  `SESSION_TTL_MS`, `MAX_CONNECTIONS*`, `EXIT_BLOCK_PRIVATE` y logs requieren reinicio.
- **Credenciales de exit**: una por exit; rotacion sin downtime con `EXIT_USERS` (solape)
  y `scripts/rotate-cred.ts`. Ver "Rotacion de credenciales" en el README.
- **Draining y seleccion P2C**: al reiniciar, `POST /__drain?token=<STATS_TOKEN>` drena el
  gateway (tuneles en vuelo terminan hasta `SHUTDOWN_GRACE_MS`; el exit hasta
  `EXIT_SHUTDOWN_GRACE_MS`); las sesiones nuevas eligen el menos cargado de dos exits sanos
  (P2C least-connections), con sticky/TTL sin cambios.
- **Despliegue (Windows)**: `npm run build` y reiniciar la tarea `local-proxy-autostart`
  (lanza desde `dist/`); verificar `/healthz` + `/readyz`. El watchdog
  `local-proxy-watchdog` sondea la salud cada 2 min. Script elevado opcional:
  `scripts/deploy-windows.ps1`.
- **Despliegue (VPS)**: copiar `dist/` + `package.json` + `scripts/` y ejecutar
  `scripts/restart-exit.sh` (mata solo el exit y lo relanza); verifica `/__health`.
  Evita `pkill` con el patron en la linea de comandos (se auto-mata).
- **Tailscale ACLs**: politica versionada en `tailscale/acl.hujson` (**no aplicada**; ver
  el orden seguro de aplicacion en el README).

## Idioma y estilo

- Documentacion y comentarios en espanol. Sin emojis salvo peticion expresa.
- No anadir dependencias de runtime sin aprobacion.
