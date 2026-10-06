# Conexion del MCP de n8n

## Conexion recomendada para ChatGPT

La conexion debe hacerse directamente contra el MCP de instancia de n8n. El repositorio no actua como proxy de credenciales.

1. En n8n: Settings > Instance-level MCP.
2. Habilitar MCP access.
3. Abrir Connect / Connect a client.
4. Elegir ChatGPT cuando aparezca como cliente web y preferir OAuth.
5. Si se usa API key, copiar el Server URL y el token solo al almacenamiento privado del cliente. Nunca guardarlos en este repositorio.
6. El Server URL oficial termina en `/mcp-server/http`.

## Verificacion posterior

Una vez conectado el cliente:

1. Inspeccionar las tools anunciadas por el servidor.
2. Confirmar busqueda de workflows.
3. Confirmar lectura de un workflow MCP-enabled no critico.
4. Crear un workflow de prueba.
5. Modificarlo y validarlo.
6. Ejecutarlo en modo de prueba cuando corresponda.
7. Confirmar operaciones de data tables si el servidor las anuncia.
8. Confirmar operaciones de agents si la version/instancia las anuncia.
9. Solo despues trabajar sobre workflows reales.

## Restricciones de n8n

- `search_workflows` puede descubrir previews de workflows que el usuario conectado puede ver.
- Leer datos completos, ejecutar o modificar un workflow existente puede requerir que ese workflow este expuesto a MCP.
- Los permisos siguen siendo los del usuario autenticado.
- La disponibilidad exacta de tools depende de la version y funciones habilitadas en la instancia.
- No asumir una tool: descubrir primero el catalogo que anuncia el servidor.

## Secretos

Este repositorio es publico. No guardar aqui tokens, API keys, cookies, OAuth refresh tokens ni archivos de configuracion que los contengan.
