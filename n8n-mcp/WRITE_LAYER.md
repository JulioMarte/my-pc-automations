# Capa de escritura del MCP de n8n

## Objetivo

Permitir operaciones de escritura sobre el MCP de instancia de n8n desde ChatGPT sin ejecutar automatizaciones por cambios normales del repositorio.

La entrada operativa es únicamente:

```text
n8n-mcp/write-request.json
```

El workflow `n8n MCP write` escucha cambios **solo** en ese archivo. Cambios en código, documentación, otros workflows o cualquier otro archivo del repositorio no ejecutan una operación MCP de escritura.

También existe `workflow_dispatch` para uso manual cuando el workflow esté disponible en la rama por defecto.

## Ruta de ejecución

```text
ChatGPT
  -> modifica write-request.json explícitamente
  -> GitHub Actions: n8n MCP write
  -> MCP_WRITE_ONLY=true
  -> initialize
  -> tools/list
  -> validación contra schema vivo
  -> confirmWrite=true obligatorio
  -> tools/call
  -> resultado sanitizado
```

## Guardas de seguridad

- Host fijado a `n8n.quisqueyatech.com`.
- Ruta MCP fijada a `/mcp-server/http`.
- `N8N_MCP_TOKEN` solo proviene de GitHub Actions Secrets.
- `N8N_MCP_URL` proviene de Repository Variables.
- `MCP_WRITE_ONLY=true` bloquea todas las tools clasificadas como read.
- Toda tool no-read requiere `confirmWrite: true`.
- Antes de `tools/call`, el runner vuelve a ejecutar `tools/list`.
- La tool solicitada debe seguir siendo anunciada por el servidor.
- Los argumentos se validan contra el schema vivo.
- Cada request HTTP tiene timeout.
- `outputMode=full` está bloqueado mientras el repositorio sea público.
- El workflow tiene `permissions: contents: read`.
- El workflow usa `concurrency` para evitar dos mutaciones concurrentes sobre la misma ref.
- El artifact sanitizado se conserva un día.

## Validación

Se clasificaron 26 tools como operaciones con potencial de escritura, ejecución o efecto externo.

La segunda corrida completa de la suite obtuvo:

```text
write tools:      26
covered unique:   26
missing:           0
fail:              0
```

La suite se ejecutó dos veces. La segunda corrida verificó que los fixtures persistentes se reutilizan y no se duplican.

### Operaciones positivas probadas

Se probaron con recursos exclusivos de la suite:

- `create_workflow_from_code`
- `update_workflow`
- `move_workflows_to_folder`
- `prepare_workflow_pin_data`
- `test_workflow`
- `execute_workflow` en modo manual
- `publish_workflow`
- `unpublish_workflow`
- `restore_workflow_version`
- `archive_workflow`
- `create_folder`
- `update_folder`
- `create_data_table`
- `rename_data_table`
- `add_data_table_column`
- `rename_data_table_column`
- `delete_data_table_column`
- `add_data_table_rows`
- `create_agent`
- `mutate_agent`
- `delete_agent`

El workflow temporal usado por la suite contiene solo:

```text
Manual Trigger -> Set
```

No contiene HTTP Request, credenciales, filesystem, Execute Command ni integraciones externas.

Antes de crearlo se validó con `validate_workflow`; el servidor devolvió `valid: true` y `nodeCount: 2`.

### Rutas validadas mediante rechazo controlado

No se deben probar positivamente en una suite inocua cuando ello pueda usar credenciales, modelos, canales o servicios externos:

- `call_agent`
- `publish_agent`
- `unpublish_agent`
- `revert_agent`
- `update_agent_integration`

El Agent temporal se creó sin modelo ni credencial. Estas rutas se ejercitaron esperando un rechazo de dominio válido. No se conectó Telegram, Slack, Linear, LLM ni otra integración real.

## Fixtures persistentes

El MCP actual no expone delete para Folder ni Data Table. Para no generar basura en cada corrida se conservan exactamente estos fixtures:

```text
Folder:     __MCP_WRITE_SUITE__
Data Table: MCP_Write_Suite
Row marker: write-suite-fixture
```

La segunda corrida confirmó que se reutilizan.

Las columnas temporales creadas durante la prueba sí se eliminan. Los Agents temporales se eliminan. Los workflows temporales se despublican y archivan.

## Fail-closed comprobado

Se hicieron pruebas específicas sobre el runner operativo:

1. Se intentó ejecutar `search_projects` desde el canal write.
   Resultado: `MCP_WRITE_ONLY` la bloqueó antes de `tools/call`.

2. Se intentó `archive_workflow` con `confirmWrite:false`.
   Resultado: el runner lo bloqueó antes de `tools/call`.

3. Se ejecutó `update_folder` sobre el fixture, asignándole su mismo nombre y con `confirmWrite:true`.
   Resultado: ejecución exitosa y sin cambio neto de estado.

## Uso normal desde ChatGPT

Una operación debe expresarse explícitamente en `write-request.json`.

Ejemplo conceptual:

```json
{
  "tool": "update_workflow",
  "arguments": {
    "workflowId": "<id>",
    "operations": []
  },
  "outputMode": "summary",
  "confirmWrite": true
}
```

Nunca poner tokens, contraseñas, cookies o secretos dentro del request.

Para una operación real, el flujo recomendado es:

1. Resolver IDs y contexto mediante la capa read.
2. Revisar el schema vivo.
3. Preparar la mutación mínima.
4. Ejecutar una sola tool write.
5. Leer nuevamente el recurso para verificar el estado posterior.
6. Para cambios de workflow, usar historial/versiones como mecanismo de recuperación cuando corresponda.

## Triggers de GitHub Actions

Los runners operativos read/write usan un `push.paths` extremadamente estrecho:

- `n8n MCP read` -> solo `n8n-mcp/read-request.json`
- `n8n MCP write` -> solo `n8n-mcp/write-request.json`

Esto es intencional: permite que ChatGPT dispare una operación concreta modificando el envelope de request, sin ejecutar MCP por cambios generales del repo.

Los workflows de diagnóstico y suites no tienen trigger por push; son `workflow_dispatch`.

GitHub documenta que los filtros `paths` limitan un workflow de `push` a cambios que coincidan con las rutas indicadas:
https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow

GitHub también documenta que `workflow_dispatch` solo recibe eventos si el archivo del workflow existe en la rama por defecto:
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax

El endpoint REST para crear un dispatch requiere permiso de Actions de escritura:
https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event

El conector GitHub disponible actualmente en este chat no expone esa acción de dispatch. Por eso read/write conservan el canal explícito por archivo request.

## Documentación oficial de n8n

Referencia oficial del MCP:
https://docs.n8n.io/connect/connect-to-n8n-mcp-server.md

Referencia oficial de las tools:
https://docs.n8n.io/connect/connect-to-n8n-mcp-server/mcp-server-tools-reference.md

Los schemas vivos anunciados por `tools/list` en esta instancia son la fuente operativa final para construir cada llamada, porque reflejan la versión realmente desplegada.

## Limitación del repositorio público

`my-pc-automations` es público.

Por eso:

- no se permite `outputMode=full`;
- no se deben meter payloads sensibles en los request JSON;
- logs/artifacts se tratan como potencialmente públicos;
- no se deben volcar definiciones completas de workflows, datos confidenciales de ejecuciones, Data Tables sensibles o secretos.

Para administración de alta fidelidad, el bridge debería vivir en un repositorio privado o un runner privado.
