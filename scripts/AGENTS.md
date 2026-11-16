# AGENTS.md - scripts

Aplica a `scripts/**` ademas del `AGENTS.md` raiz. No contradice la politica del
repositorio; solo anade reglas locales mas estrictas.

## Reglas

- **Sin dependencias externas**: usar solo Node/biblioteca estandar o utilidades
  del sistema; no agregar paquetes.
- **Node ESM (`.mjs`) o bash**: scripts de automatizacion en `scripts/*.mjs` o
  `scripts/*.sh`; el runtime de produccion no depende de ellos.
- **Compatibles con Windows y Linux**: evitar rutas, separadores y comandos
  especificos de una sola plataforma, o aislarlos tras una rama explicita.
- **No hardcodear secretos**: credenciales y tokens se leen de variables de
  entorno o archivos ignorados; nunca se escriben en el script.
- **Salida estable y codigos de salida significativos**: mensajes parseables y
  `exit 0` en exito, distinto de cero en fallo, para que CI y orquestadores
  puedan decidir.
