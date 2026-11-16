---
applyTo: "local-proxy/**/*.ts,scripts/**/*.mjs"
---

- Aplicar `local-proxy/AGENTS.md` o `scripts/AGENTS.md` segun el path, ademas del
  `AGENTS.md` raiz.
- TypeScript ESM sin dependencias de runtime en `local-proxy`; el runtime de
  produccion es Node desde `dist/`, Bun es solo tooling.
- No mover ni renombrar `local-proxy/test/*.test.ts`: el runner `node --test` y
  el CI dependen de esa ubicacion y del patron `*.test.ts`.
- No hardcodear secretos; credenciales y tokens via variables de entorno o
  archivos ignorados.
- Antes de integrar: `npm run typecheck` y `npm test` en verde.
