# n8n MCP Write Layer

## Purpose

This layer gives ChatGPT a deliberately explicit path for mutating the instance-level n8n MCP without coupling MCP calls to ordinary repository changes.

The operational write path is physically separated from reads and sets `MCP_WRITE_ONLY=true`.

## Trigger model

Only a push that changes:

```text
n8n-mcp/write-request.json
```

can automatically start the operational workflow `n8n MCP write`.

A parked request with `confirmWrite:false` is a successful no-op: the workflow exits without opening an MCP connection or sending `tools/call`. This lets HEAD remain safely parked without leaving an intentionally failing check.

Changes to source code, documentation, other workflows, or unrelated repository files do **not** trigger an n8n write.

The diagnostic, general invoke, read-suite, and write-suite workflows are `workflow_dispatch` only. GitHub documents that `paths` filters constrain `push` workflows to matching changed paths, and that `workflow_dispatch` only receives events when the workflow file exists on the default branch.

## Write gates

A write request must pass all of these gates before `tools/call`:

1. The MCP endpoint must be HTTPS.
2. Host must be exactly `n8n.quisqueyatech.com`.
3. Path must be exactly `/mcp-server/http`.
4. The requested tool must be advertised by the live MCP `tools/list`.
5. The request arguments must pass the live tool schema.
6. `MCP_WRITE_ONLY=true` rejects every tool classified as read-only.
7. Every non-read tool requires `confirmWrite: true`.
8. `outputMode=full` is blocked while this repository is public.

The read runner has the inverse guard: `MCP_READ_ONLY=true` rejects every non-read tool.

## Validation evidence

The write suite classified 26 MCP tools as write/execution tools and covered all 26.

Second idempotence run:

```text
write tools:    26
covered unique: 26
missing:         0
fail:            0
positive pass:  21
negative pass:   5
fixture pass:    3
```

The three fixture passes prove that the persistent Folder, Data Table and marker row were reused instead of duplicated.

The operational write runner was then validated independently:

- read tool through write runner -> blocked locally by `MCP_WRITE_ONLY`;
- write tool with `confirmWrite:false` -> blocked locally;
- confirmed idempotent `update_folder` against the dedicated fixture -> successful MCP call.

## Inert fixtures

The suite uses two persistent, clearly reserved resources because the live MCP catalog exposes no delete operation for them:

- Folder: `__MCP_WRITE_SUITE__`
- Data Table: `MCP_Write_Suite`
- Data Table marker row: `write-suite-fixture`

They are created once and reused. Temporary columns are deleted before completion.

Workflow tests use an inert `Manual Trigger -> Set` workflow with no credentials, HTTP requests, files, webhooks, databases, or external services. The workflow is archived at the end.

Agent tests create a temporary Agent with no model, credentials, tools, or integrations. Safe configuration mutation is tested positively. Operations that would require a real model, publication state, or external credential are exercised as controlled negative-path validations. The Agent is deleted at the end.

## Covered write/execution tools

- `execute_workflow`
- `publish_workflow`
- `unpublish_workflow`
- `prepare_workflow_pin_data`
- `test_workflow`
- `create_data_table`
- `rename_data_table`
- `add_data_table_column`
- `delete_data_table_column`
- `rename_data_table_column`
- `add_data_table_rows`
- `create_workflow_from_code`
- `create_folder`
- `update_folder`
- `move_workflows_to_folder`
- `archive_workflow`
- `update_workflow`
- `restore_workflow_version`
- `create_agent`
- `mutate_agent`
- `call_agent`
- `publish_agent`
- `unpublish_agent`
- `revert_agent`
- `delete_agent`
- `update_agent_integration`

## Operations deliberately treated as high risk

A successful transport/schema test is not permission to use a tool casually.

Before calling these against a real object, inspect the target and obtain an explicit user instruction:

- `execute_workflow`: may trigger downstream effects.
- `test_workflow`: can still execute nodes; use pin data and inert workflows for tests.
- `publish_workflow` / `unpublish_workflow`: changes availability/runtime state.
- `archive_workflow`: removes a workflow from normal active views.
- `restore_workflow_version`: replaces current workflow state with a historical version.
- `call_agent`: may invoke models/tools and incur external effects or cost.
- `publish_agent` / `unpublish_agent` / `revert_agent`: changes Agent lifecycle state.
- `update_agent_integration`: can connect an Agent to an external channel/credential.
- Data Table mutations: can alter persistent business data.

For a real destructive operation, prefer read-before-write, narrow arguments, explicit confirmation, and read-after-write verification.

## Explicit usage

To request one write, edit only `n8n-mcp/write-request.json`.

Example shape:

```json
{
  "tool": "update_folder",
  "arguments": {
    "projectId": "<project-id>",
    "folderId": "<folder-id>",
    "name": "<new-name>"
  },
  "outputMode": "summary",
  "confirmWrite": true
}
```

Never store tokens, credentials, passwords, API keys, webhook secrets, execution payloads, or private business data in the request file.

## Public repository limitation

This repository is public. Workflow logs, request files and uploaded artifacts must be treated as public-facing output.

The token remains a GitHub Actions secret, but **request arguments are committed to Git**. Therefore this bridge is suitable only for identifiers and non-sensitive control data. Do not use it to send secret values or confidential payloads.

For full-fidelity administrative writes containing sensitive arguments, move the bridge to a private repository or another private execution channel.
