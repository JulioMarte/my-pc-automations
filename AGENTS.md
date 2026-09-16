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
2. Cada cambio: rama propia desde `dev` -> implementar -> probar -> merge a `dev`.
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
  - `npm test` - tests (`node --test` sobre `.ts`).
  - `npm run build` - compila a `dist/`.
  - `npm run dev:gateway` / `npm run dev:exit` - desarrollo con `--watch`.
- Endpoints: gateway `GET /healthz`, `GET /readyz`, `GET /__stats?token=`;
  exit `GET /__health`.
- **Despliegue (Windows)**: reiniciar la tarea `local-proxy-autostart` (lanza desde
  `dist/`) y verificar `/healthz` + `/readyz`. El watchdog `local-proxy-watchdog`
  sondea la salud cada 2 min. Script elevado opcional: `scripts/deploy-windows.ps1`.
- **Despliegue (VPS)**: copiar `dist/` + `package.json` + `scripts/exit-daemon.sh`,
  matar el proceso viejo y ejecutar el daemon; verifica `/__health`.

## Idioma y estilo

- Documentacion y comentarios en espanol. Sin emojis salvo peticion expresa.
- No anadir dependencias de runtime sin aprobacion.
