# n8n MCP Read Layer

## Purpose

This layer gives ChatGPT a controlled, read-only path into the instance-level n8n MCP through GitHub Actions.

The read path is physically separated from the general invoke path and sets `MCP_READ_ONLY=true`. Any tool that is not in the explicit `READ_ONLY_TOOLS` allowlist is rejected before `tools/call`.

## Runtime path

```text
ChatGPT
  -> GitHub repository change
  -> n8n MCP read workflow
  -> invoke.mjs
  -> MCP initialize
  -> tools/list
  -> live schema validation
  -> tools/call
  -> sanitized result
```

## Safety properties

- Host is pinned to `n8n.quisqueyatech.com`.
- MCP path is pinned to `/mcp-server/http`.
- Token is only read from `N8N_MCP_TOKEN` GitHub Actions secret.
- Base URL is read from `N8N_MCP_URL` repository variable.
- Read workflow sets `MCP_READ_ONLY=true`.
- Explicit allowlist separates read tools from mutating/executing tools.
- Live `tools/list` is fetched before each invocation.
- Requested tool must still be advertised by the current server.
- Arguments are checked against the live tool schema before `tools/call`.
- Each network call has a 15 second timeout.
- `outputMode=full` is blocked while the repository is public.
- Artifacts are retained for one day.

## Validation status

The comprehensive read suite covers all 28 read-classified MCP tools.

Final result:

```text
total:         28
positive pass: 23
negative pass: 5
skip:           0
fail:           0
```

A positive pass means a real read completed successfully using live context where required.

A negative pass means the route, authentication and schema were exercised with a deliberately nonexistent or invalid context and the MCP returned the expected domain rejection. This is used only when the instance has no real safe object of that type to read.

The five negative-path validations are:

- `get_agent`
- `validate_agent`
- `list_agent_versions`
- `discover_agent_assets`
- `explore_node_resources`

The first four use a deliberately nonexistent Agent because `search_agents` currently returns no accessible real Agent. `explore_node_resources` uses an invalid credential/method combination specifically to validate routing without contacting an external credential-backed service.

## Positive read coverage

Validated against real instance data or live node metadata:

- `search_workflows`
- `get_workflow_details`
- `search_workflow_executions`
- `get_workflow_execution`
- `get_workflow_history`
- `get_workflow_version`
- `get_workflow_versions_diff`
- `list_credentials`
- `list_n8n_gateway_services`
- `list_workflow_tags`
- `search_data_tables`
- `get_data_table_rows`
- `search_nodes`
- `get_node_types`
- `get_workflow_best_practices`
- `validate_workflow`
- `validate_node_config`
- `search_projects`
- `search_folders`
- `get_workflow_sdk_reference`
- `search_agents`
- `get_agent_builder_reference`
- `verify_agent_mcp_server`

## Fail-closed tests

The dedicated read runner has also been tested against:

1. A write tool (`archive_workflow`) with `confirmWrite=true`.
   - Result: blocked locally by `MCP_READ_ONLY`.
   - No `tools/call` was sent.

2. A valid read tool with an unknown argument (`bogusArgument`).
   - Result: rejected by live-schema preflight before `tools/call`.

## Daily usage

Edit only:

```text
n8n-mcp/read-request.json
```

Example:

```json
{
  "tool": "search_workflows",
  "arguments": {
    "limit": 20,
    "sortBy": "updatedAt:desc"
  },
  "outputMode": "summary",
  "confirmWrite": false
}
```

The workflow `n8n MCP read` runs automatically.

## Public repository limitation

This repository is public. GitHub Actions logs and artifacts must therefore be treated as public-facing output. Do not request full workflow definitions, execution payloads, Data Table contents, credential metadata or other sensitive material through this public transport.

For full-fidelity administrative reading, move this MCP bridge to a private repository or another private execution channel first.
