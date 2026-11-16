# Contribucion

Guia practica para contribuir a `my-pc-automations`. Es un resumen operativo:
la autoridad es `AGENTS.md` (raiz y anidados) y el indice `docs/README.md`; si
algo aqui contradice esos documentos, mandan ellos.

## Flujo de ramas

```
feat/<feature> | fix/<bug> | chore/<tarea> | docs/<cambio>
        --(tests + verificacion OK)-->  dev  --(PR + review)-->  main
```

- Cada cambio nace en su propia rama creada desde `dev` y se integra a `dev`.
- `dev` es la rama de integracion y trabajo diario.
- `main` es release candidate: **solo** recibe merges desde `dev` mediante PR.

## Limites de autoridad

- Un **commit local es un checkpoint**: puede quedar rojo mientras se trabaja.
- Un **push es publicacion**: solo se hace cuando el usuario lo pide.
- La autoridad de merge es el **CI exact-head del PR** sobre el commit revisado.
- **Nunca** push directo a `main` ni a `dev`.

## Antes de integrar

- `local-proxy`: `npm run typecheck` y `npm test` en verde.
- `vps-disaster-recovery`: `tests/static.sh` es el gate obligatorio (`make static`).
- Verificar el estado del repo; no commitear secretos ni artefactos de `results/`.

## Como correr suites

El contrato de ejecucion vive en `tests/suites.json` y `scripts/run-suite.mjs`.

```bash
node scripts/run-suite.mjs list           # selectores registrados
node scripts/run-suite.mjs select pr      # suites con politica pr
node scripts/run-suite.mjs run policy:pr  # ejecuta la politica pr
node scripts/run-suite.mjs run <selector> # ejecuta una suite concreta
```

- La evidencia de cada corrida se escribe en `results/<selector>/` y **no se
  commitea**.
- Validar el manifiesto: `node scripts/validate-suites.mjs`.
- Tests de gobernanza: `node --test "tests/architecture/**/*.test.mjs"`.

## Disciplina de reporte

1. Explicar que cambio en terminos del sistema (que comportamiento o contrato se
   movio), no solo que archivos se tocaron.
2. Indicar que **no** se cambio y que problemas son preexistentes y quedan fuera
   de alcance.
3. Exponer las decisiones tomadas y las decisiones pendientes.
4. **Nunca** afirmar que una verificacion paso salvo que se haya ejecutado de
   verdad en esa sesion.

## Clasificacion de gobernanza

Toda regla estructural se etiqueta (detalle en `AGENTS.md`):

- **HARD**: invariante o semantica que no se negocia; si se rompe, se falla
  cerrado.
- **CONTROLLED**: forma aceptada que evoluciona de manera deliberada y aprobada.
- **FLEXIBLE**: implementacion privada; puede cambiar si mantiene el contrato
  publico.
- **HISTORICAL**: material de procedencia; no es autoridad vigente.
