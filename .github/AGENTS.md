# AGENTS.md - .github

Aplica a `.github/**` ademas del `AGENTS.md` raiz. No contradice la politica del
repositorio; solo anade reglas locales mas estrictas.

## Reglas

- **Los workflows son orquestadores finos.** Solo conectan triggers, matriz y
  publicacion de artefactos; la logica vive en los scripts del repo.
- **La seleccion de suites y servicios vive en `scripts/registry`
  (`tests/suites.json`)**, no en YAML especifico por feature. Un workflow nuevo
  no debe codificar a mano que tests corren para una feature concreta.
- **Permisos minimos**: declarar `permissions: contents: read` y ampliar solo lo
  imprescindible y justificado.
- **Cancelar ejecuciones superadas**: `concurrency` con `cancel-in-progress:
  true` agrupado por workflow y ref.
- **Gates agregados fail-closed**: un job agregado debe fallar si cualquiera de
  sus dependientes no fue exitoso (`needs` + verificacion explicita del
  resultado), no solo si se salta o se cancela.
