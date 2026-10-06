# Conexión de ChatGPT con el MCP de n8n

Este repositorio soporta dos formas distintas de trabajar con el MCP de instancia de n8n.

## 1. Conexión directa del cliente

Cuando ChatGPT/Codex soporte configurar directamente el servidor MCP, la ruta preferida es conectar el cliente directamente a n8n.

En n8n:

1. Abrir **Settings > Instance-level MCP**.
2. Habilitar MCP access.
3. Abrir la opción para conectar un cliente.
4. Preferir OAuth cuando esté disponible.
5. Si se usa token/API key, guardarlo únicamente en el almacenamiento privado del cliente.
6. El endpoint de esta instancia usa `/mcp-server/http`.

Nunca guardar tokens en este repositorio.

## 2. Bridge actual mediante GitHub Actions

Para esta conversación se implementó además un bridge controlado usando GitHub Actions.

Este bridge existe porque el conector GitHub disponible en ChatGPT permite editar archivos del repositorio y consultar Actions, pero no expone actualmente una acción para crear un `workflow_dispatch` arbitrario.

Por eso existen dos envelopes explícitos:

```text
n8n-mcp/read-request.json
n8n-mcp/write-request.json
```

### Lectura

Modificar `read-request.json` ejecuta únicamente:

```text
n8n MCP read
```

Ese workflow establece:

```text
MCP_READ_ONLY=true
```

y rechaza cualquier tool clasificada como escritura/efecto antes de enviar `tools/call`.

### Escritura

Modificar `write-request.json` ejecuta únicamente:

```text
n8n MCP write
```

Ese workflow establece:

```text
MCP_WRITE_ONLY=true
```

y además toda operación write requiere:

```json
"confirmWrite": true
```

Una tool read enviada por el canal write se bloquea localmente. Una tool write sin confirmación también se bloquea localmente.

## Qué NO dispara el MCP

Los cambios normales en:

- scripts;
- documentación;
- README;
- otros workflows;
- código de tests;
- archivos fuera de los dos request envelopes;

no disparan operaciones MCP.

Los workflows siguientes son manual-only:

- `n8n MCP diagnostic`
- `n8n MCP invoke`
- `n8n MCP read suite`
- `n8n MCP write suite`

## Procedimiento recomendado para una operación real

1. Usar la capa read para resolver IDs y contexto.
2. Revisar el schema vivo anunciado por `tools/list`.
3. Elegir la operación mínima necesaria.
4. Para escritura, preparar `write-request.json` con `confirmWrite:true`.
5. Ejecutar una sola mutación.
6. Volver a leer el recurso para verificar el estado posterior.
7. Si se modifica un workflow, conservar historial/versiones como mecanismo de recuperación.

No asumir que una tool existe o que mantiene el mismo schema entre versiones: el schema vivo del servidor desplegado es la fuente operativa final.

## Validación realizada

La instancia anunció 54 tools:

```text
28 read
26 write/effect
```

Resultados:

```text
Read:  28/28 cubiertas, 0 FAIL
Write: 26/26 cubiertas, 0 FAIL
```

La suite write utiliza recursos de prueba aislados y evita integraciones externas reales.

## Seguridad del repositorio público

`my-pc-automations` es público.

No colocar en los request JSON:

- tokens;
- contraseñas;
- cookies;
- refresh tokens;
- payloads privados;
- secretos de workflows;
- datos personales o empresariales sensibles.

Además, `outputMode=full` está bloqueado en el runner mientras el repositorio sea público.

Para tareas administrativas de alta fidelidad o contenido sensible, mover el bridge a un repositorio privado o a otro canal de ejecución privado.

## Documentación oficial

n8n:

- https://docs.n8n.io/connect/connect-to-n8n-mcp-server.md
- https://docs.n8n.io/connect/connect-to-n8n-mcp-server/mcp-server-tools-reference.md

GitHub Actions:

- https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow
- https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
