# AGENTS.md - local-proxy

Aplica a `local-proxy/**` ademas del `AGENTS.md` raiz. No contradice la politica
del repositorio; solo anade reglas locales mas estrictas.

## Reglas

- **TypeScript ESM sin dependencias de runtime.** No agregar paquetes de
  produccion; `typescript` y `@types/node` son devDependencies.
- **Runtime de produccion: Node.js desde `dist/`.** Bun es solo tooling
  (`bun src/gateway.ts`, `bun test`, `bun --watch`); el build y el arranque
  real usan `node`.
- **Comandos canonicos**:
  - `npm run typecheck` - `tsc` sin emitir.
  - `npm test` - `node --test` sobre `test/*.test.ts`.
  - `npm run test:journey` - solo jornadas e2e.
  - `npm run stress` - carga in-process.
  - `npm run monitor` / `monitor:once` - alertas de salud.
  - `npm run docker:e2e` - end-to-end en Docker.
  - `npm run build` - compila a `dist/`.
- **No mover ni renombrar `test/*.test.ts`.** El runner `node --test` y el CI
  (`npm test`) dependen de esa ubicacion y del patron `*.test.ts`; los archivos
  de ayuda que no son tests quedan como `test/helpers.ts`.
- **Documentacion del proyecto en `local-proxy/docs/`** (`docker.md`,
  `service.md`, `alerts.md`, `testing.md`, `ci.md`); no duplicar esa guia en el
  README ni en este archivo.
- **Recarga en caliente vs reinicio**: al guardar `.env` se recargan
  `PROXY_USERS`/`STATS_TOKEN`/`METRICS_TOKEN` (gateway) y `EXIT_USERS` (exit);
  puertos, timeouts, `SESSION_TTL_MS`, `MAX_CONNECTIONS*`, `EXIT_BLOCK_PRIVATE`
  y logs requieren reiniciar el proceso.
- **No commitear secretos**: `.env`, `exits.json`, credenciales y tokens son
  locales; solo `.env.example`/`exits.example.json` van al repo.
