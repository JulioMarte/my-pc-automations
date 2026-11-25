# AGENTS.md - tests

Aplica a `tests/**` ademas del `AGENTS.md` raiz. No contradice la politica del
repositorio; solo anade reglas locales mas estrictas.

## Reglas

- **Ubicacion fisica = propiedad y ejecucion; marcadores/estado = clase de
  evidencia.** La ruta indica a quien pertenece el test y como se ejecuta; las
  etiquetas (`unit`, `integration`, `e2e`, `stress`, `architecture`) indican que
  clase de evidencia aporta.
- **Taxonomia de suites**: `unit`, `integration`, `e2e`, `stress`,
  `architecture`. Toda suite nueva se clasifica en una de estas clases.
- **Integridad de evidencia**: un test verde solo cuenta como evidencia si un
  defecto plausible lo haria fallar. No fabricar el resultado esperado en el
  setup ni aserir lo que el propio fixture acaba de escribir.
- **Contrato de ejecucion declarativo**: `tests/suites.json` mas
  `scripts/run-suite.mjs` definen que corre. Las suites se seleccionan por
  politica (`pr`, `merge`, `nightly`, `manual`), no por YAML especifico de una
  feature.
- **Mundo fresco por suite**: cada suite arranca su propio estado y no depende de
  datos dejados por otra suite; el orden de ejecucion no debe importar.
- **Artefactos en `results/<selector>/`**: logs, JSON y evidencia de cada corrida
  se escriben bajo ese directorio y no se commitean.
