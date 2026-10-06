# Cliente MCP de n8n

Cliente de diagnostico y operacion para el MCP de instancia de n8n. Vive aislado del resto de `my-pc-automations` y no contiene credenciales.

## Objetivo

Conectarse al endpoint oficial `/mcp-server/http`, negociar MCP, descubrir dinamicamente las capacidades y tools que expone la instancia y permitir invocarlas sin codificar una lista fija.

## Requisitos

- Node.js 20+ (usa `fetch` nativo; sin dependencias de runtime).
- n8n con **Instance-level MCP** habilitado.
- URL del servidor MCP y token personal generado por n8n.

## Configuracion

No guardes secretos en Git. Copia `.env.example` a un archivo local o exporta las variables en tu shell:

```bash
export N8N_MCP_URL="https://tu-n8n.example.com/mcp-server/http"
export N8N_MCP_TOKEN="..."
```

El cliente no carga `.env` por si solo para evitar agregar dependencias. En PowerShell:

```powershell
$env:N8N_MCP_URL="https://tu-n8n.example.com/mcp-server/http"
$env:N8N_MCP_TOKEN="..."
```

## Comandos

```bash
node src/mcp-client.mjs doctor
node src/mcp-client.mjs tools
node src/mcp-client.mjs capabilities
node src/mcp-client.mjs call <tool> '{"parametro":"valor"}'
node src/mcp-client.mjs rpc <metodo> '{"parametro":"valor"}'
```

`doctor` inicializa la sesion, muestra las capabilities negociadas y enumera todas las tools. `tools` sigue cursores de paginacion hasta obtener el catalogo completo.

## Alcance real de n8n

El MCP de instancia no equivale a acceso irrestricto a toda la base de datos de n8n. El servidor decide las tools disponibles y n8n aplica los permisos del usuario y la exposicion MCP de workflows. El cliente deliberadamente respeta ese modelo: descubre y llama lo que el servidor anuncie.

Desde n8n 2.13, el MCP de instancia puede crear y editar workflows. Versiones recientes tambien exponen operaciones de data tables y, cuando la funcion correspondiente esta habilitada, agentes. Para workflows existentes, n8n puede exigir que esten marcados como disponibles en MCP antes de leer el contenido completo, ejecutarlos o modificarlos.

## Seguridad

- Nunca commitear `N8N_MCP_TOKEN`.
- El token viaja solo en `Authorization: Bearer`.
- El programa no imprime el token.
- Si el token se expone, rotarlo en n8n inmediatamente.
- Para operaciones destructivas, revisar primero el schema de la tool con `tools`.

## Estructura

```text
n8n-mcp/
  README.md
  .env.example
  package.json
  src/
    mcp-client.mjs
```
