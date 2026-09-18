# Mapa de documentacion

Indice de la autoridad **vigente** del repositorio `my-pc-automations`. No es un
diario de cambios: lista que documento manda hoy y en que orden.

## Cadena de precedencia

1. **`AGENTS.md` raiz** - politica de alcance repositorio completo (ramas,
   disciplina de reporte, clasificacion de gobernanza).
2. **`AGENTS.md` anidado** - reglas locales mas estrictas para su path; nunca
   contradicen el raiz.
3. **Docs de proyecto** - guias operativas de cada sub-proyecto.
4. **Material historico** - procedencia, no autoridad actual.

## Gobernanza

- `AGENTS.md` - reglas del repositorio.
- `local-proxy/AGENTS.md` - reglas de `local-proxy/**`.
- `vps-disaster-recovery/AGENTS.md` - reglas de `vps-disaster-recovery/**`.
- `tests/AGENTS.md` - taxonomia de tests e integridad de evidencia.
- `scripts/AGENTS.md` - convenciones de scripts.
- `.github/AGENTS.md` - convenciones de workflows.
- Adaptadores finos (no manuales): `CLAUDE.md`, `GEMINI.md`,
  `.github/copilot-instructions.md`, `.github/instructions/*.instructions.md`.

## Contribucion y garantias

- `CONTRIBUTING.md` - guia practica de ramas, autoridad de merge y suites.
- `tests/guarantees.json` - inventario declarativo de garantias del repositorio
  y los selectores de suite que las prueban.

## Documentacion por proyecto

### `local-proxy`

- `local-proxy/README.md` - vision general y operacion.
- `local-proxy/docs/docker.md` - Docker y Compose.
- `local-proxy/docs/service.md` - servicio real (systemd/WinSW).
- `local-proxy/docs/alerts.md` - alertas y monitor.
- `local-proxy/docs/testing.md` - suite, journeys y stress.
- `local-proxy/docs/ci.md` - integracion continua.

### `vps-disaster-recovery`

- `vps-disaster-recovery/README.md` - laboratorio y comandos locales.
- `vps-disaster-recovery/docs/backup-and-disaster-recovery.md` - operacion DR.
- `vps-disaster-recovery/docs/TESTING.md` - jerarquia de pruebas.

## Material historico (procedencia)

- `vps-disaster-recovery/candidate/` - payload y SHA del candidato ya probado.
- `vps-disaster-recovery/patches/` - parches de versiones pasadas.

Se conserva por trazabilidad; **no** se usa para decidir el presente.
