# Bridge MCP de n8n

Capa aislada dentro de `my-pc-automations` para que ChatGPT pueda consultar y operar el MCP de instancia de n8n mediante GitHub Actions sin guardar credenciales en el repositorio.

## Estado validado

Servidor detectado durante las pruebas:

```text
n8n MCP Server v1.2.0
MCP protocol: 2025-06-18
Tools anunciadas: 54
```

Cobertura validada:

```text
Read layer
  tools clasificadas: 28
  PASS positivos:      23
  NEGATIVE-PASS:        5
  FAIL:                 0

Write/effect layer
  tools clasificadas: 26
  covered unique:      26
  missing:              0
  FAIL:                 0
```

Detalles:

- [READ_LAYER.md](./READ_LAYER.md)
- [WRITE_LAYER.md](./WRITE_LAYER.md)
- [CHATGPT_SETUP.md](./CHATGPT_SETUP.md)
- [TRIGGER_MODEL.md](./TRIGGER_MODEL.md)
- [WRITE_ADVERSARIAL_REVIEW.md](./WRITE_ADVERSARIAL_REVIEW.md)

## Arquitectura operativa

```text
ChatGPT
  |
  +-> read-request.json
  |     -> GitHub Actions: n8n MCP read
  |     -> MCP_READ_ONLY=true
  |
  +-> write-request.json
        -> GitHub Actions: n8n MCP write
        -> MCP_WRITE_ONLY=true
        -> requestId + targetRef
        -> confirmWrite=true
        -> confirmRisk=true cuando aplica
        -> expectedTargetName cuando aplica
```

Los dos canales operativos reaccionan únicamente a cambios en su propio archivo request:

- `n8n-mcp/read-request.json`
- `n8n-mcp/write-request.json`

Un cambio normal de código, documentación u otro archivo del repositorio no ejecuta una operación MCP.

Los workflows de diagnóstico y suites son manuales mediante `workflow_dispatch`.

## Estructura

```text
n8n-mcp/
  README.md
  READ_LAYER.md
  WRITE_LAYER.md
  WRITE_ADVERSARIAL_REVIEW.md
  TRIGGER_MODEL.md
  CHATGPT_SETUP.md
  .env.example
  package.json
  read-request.json
  write-request.json
  request.json
  src/
    mcp-client.mjs
    diagnose.mjs
    invoke.mjs
    tools.mjs
    read-suite.mjs
    write-suite.mjs

.github/workflows/
  n8n-mcp-read.yml
  n8n-mcp-write.yml
  n8n-mcp-diagnostic.yml
  n8n-mcp-invoke.yml
  n8n-mcp-read-suite.yml
  n8n-mcp-write-suite.yml
```

## Configuración

GitHub Repository Variable:

```text
N8N_MCP_URL
```

GitHub Actions Secret:

```text
N8N_MCP_TOKEN
```

Nunca commitear el token.

El cliente acepta la URL base y deriva `/mcp-server/http`, pero además fija el host permitido a `n8n.quisqueyatech.com`.

## Uso local

Requiere Node.js 20+.

Linux/macOS:

```bash
export N8N_MCP_URL="https://n8n.quisqueyatech.com"
export N8N_MCP_TOKEN="..."
node src/mcp-client.mjs doctor
node src/mcp-client.mjs tools
node src/mcp-client.mjs capabilities
```

PowerShell:

```powershell
$env:N8N_MCP_URL="https://n8n.quisqueyatech.com"
$env:N8N_MCP_TOKEN="..."
node src/mcp-client.mjs doctor
```

El token no se carga automáticamente desde `.env` y no se imprime en salida normal.

## Modelo de seguridad

- allowlist explícita de las 54 tools descubiertas;
- separación física y lógica entre read y write;
- fail-closed si una tool entra por el canal equivocado;
- `confirmWrite:true` obligatorio para operaciones con efecto;
- `tools/list` y schema vivo antes de cada invocación;
- host y path MCP fijados;
- timeouts por llamada;
- permisos de Actions mínimos: `contents: read`;
- write concurrency con `cancel-in-progress:false` para no abortar una mutación ya iniciada;
- UUID por request y bloqueo de reruns/replay;
- target assertions por ID + nombre antes de mutaciones protegidas;
- `confirmRisk:true` adicional para operaciones de alto impacto;
- validación profunda contra el schema vivo;
- `isError:true` del MCP se convierte en fallo real del job;
- resultados de write reducidos a metadata estructural en el repo público;
- `outputMode=full` bloqueado mientras el repositorio sea público.

## Triggers

GitHub Actions usa path filters para que una operación no se ejecute por cualquier cambio del repo.

```text
n8n MCP read
  push.paths -> n8n-mcp/read-request.json

n8n MCP write
  push.paths -> n8n-mcp/write-request.json

n8n MCP diagnostic
  workflow_dispatch

n8n MCP invoke
  workflow_dispatch

n8n MCP read suite
  workflow_dispatch

n8n MCP write suite
  workflow_dispatch
```

El canal por archivo request existe porque este conector de GitHub no expone actualmente una acción para crear un `workflow_dispatch` desde ChatGPT. Cuando el workflow esté en la rama por defecto, un humano sí puede usar el botón manual de Actions.

## Fuente de verdad

La documentación oficial describe el contrato general:

- n8n MCP: https://docs.n8n.io/connect/connect-to-n8n-mcp-server.md
- n8n MCP tools: https://docs.n8n.io/connect/connect-to-n8n-mcp-server/mcp-server-tools-reference.md
- GitHub Actions workflow syntax: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- GitHub workflow triggering: https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow

Para ejecutar una tool concreta, la fuente operativa final es el schema vivo anunciado por `tools/list` en la instancia desplegada.

## Limitación importante: repositorio público

Este repositorio es público. Los logs y artifacts de GitHub Actions deben tratarse como potencialmente visibles.

Por eso:

- no se permite `outputMode=full`;
- no se colocan secretos en los request JSON;
- no se deben solicitar payloads confidenciales, definiciones completas sensibles o datos privados a través de este transporte;
- para administración de alta fidelidad, el bridge debería migrarse a un repositorio privado o runner privado.

## Estado de los fixtures de escritura

La suite write conserva únicamente los recursos que no tienen delete expuesto por el MCP:

```text
Folder:     __MCP_WRITE_SUITE__
Data Table: MCP_Write_Suite
Row marker: write-suite-fixture
```

Los workflows temporales se despublican y archivan. Los Agents temporales se eliminan. Las columnas temporales se eliminan.
