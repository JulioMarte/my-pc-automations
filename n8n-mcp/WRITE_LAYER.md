# n8n MCP Write Layer

Detailed threat-model evidence: [WRITE_ADVERSARIAL_REVIEW.md](./WRITE_ADVERSARIAL_REVIEW.md)

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
8. High-risk operations require `confirmRisk:true`.
9. Protected existing-resource mutations require an exact target-name assertion.
10. Nested JSON Schema constraints are validated locally against the live MCP schema.
11. MCP tool responses with `isError:true` fail the job.
12. Write responses in this public repository are reduced to structural metadata.
13. `outputMode=full` is blocked while this repository is public.

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
  "requestId": "<new-uuid>",
  "targetRef": "refs/heads/<control-branch>",
  "tool": "update_folder",
  "arguments": {
    "projectId": "<project-id>",
    "folderId": "<folder-id>",
    "name": "<new-name>"
  },
  "expectedTargetName": "<current-folder-name>",
  "outputMode": "summary",
  "confirmWrite": true,
  "confirmRisk": false
}
```

For high-risk tools, `confirmRisk` must be `true`. For Data Table column rename/delete, also include `expectedColumnName`.

Never store tokens, credentials, passwords, API keys, webhook secrets, execution payloads, or private business data in the request file.

## Public repository limitation

This repository is public. Workflow logs, request files and uploaded artifacts must be treated as public-facing output.

The token remains a GitHub Actions secret, but **request arguments are committed to Git**. Therefore this bridge is suitable only for identifiers and non-sensitive control data. Do not use it to send secret values or confidential payloads.

For full-fidelity administrative writes containing sensitive arguments, move the bridge to a private repository or another private execution channel.


## Adversarial hardening

The operational write path was attacked against accidental and ambiguous mutation cases after the original 26/26 write-tool suite passed.

Validated controls:

| Attack / failure mode | Expected behavior | Result |
|---|---|---|
| Valid resource ID but wrong expected name | Resolve target with a read and block before mutation | PASS |
| Correct ID and expected name | Permit the idempotent write | PASS |
| High-impact tool without `confirmRisk:true` | Block locally before target lookup/write | PASS |
| Nested/schema constraint violation | Block locally using live JSON Schema | PASS |
| MCP `tools/call` returns `isError:true` | Fail the GitHub job, never report success | PASS |
| New write arrives while another is running | Do not cancel the active write | PASS; pending replacement remains a documented GitHub limitation |
| Write output in public repository | Emit structural metadata only | PASS |
| Oversized request | Reject above 64 KiB | IMPLEMENTED |
| Request prepared for another branch | Reject `targetRef` mismatch | IMPLEMENTED |
| Workflow rerun | Reject `github.run_attempt > 1` | IMPLEMENTED |
| Push modifies request plus unrelated files | Reject before opening MCP | IMPLEMENTED |

### Confirmation levels

There are now two confirmation levels:

- `confirmWrite:true` is mandatory for every mutation/execution tool.
- `confirmRisk:true` is additionally mandatory for operations with material execution, lifecycle, destructive, integration, or rollback impact.

High-risk tools currently include:

- `execute_workflow`
- `test_workflow`
- `publish_workflow`
- `unpublish_workflow`
- `archive_workflow`
- `update_workflow`
- `restore_workflow_version`
- `rename_data_table`
- `add_data_table_column`
- `delete_data_table_column`
- `rename_data_table_column`
- `add_data_table_rows`
- `mutate_agent`
- `call_agent`
- `publish_agent`
- `unpublish_agent`
- `revert_agent`
- `delete_agent`
- `update_agent_integration`

### Request envelope and replay protection

Every operational write request carries:

- `requestId`: UUID. The workflow searches prior versions of `write-request.json` in Git history and rejects a reused ID.
- `targetRef`: must exactly equal the current `github.ref`, preventing a request prepared for one branch from being replayed on another.
- `confirmWrite:true`: mandatory for every actual mutation.
- `confirmRisk:true`: mandatory for high-risk tools.
- `expectedTargetName`: mandatory for protected mutations against an existing workflow, folder, Data Table, or Agent.
- `expectedColumnName`: additionally mandatory when renaming or deleting a Data Table column.

GitHub reruns are blocked with `github.run_attempt == 1`. A failed or ambiguous write is retried only by issuing a **new** request with a new UUID after verifying the current n8n state.

The write job also requires:

- trigger actor == repository owner;
- a supported control branch;
- a push whose diff contains only `n8n-mcp/write-request.json`;
- request file <= 64 KiB.

### Target identity assertion

For protected mutations against an existing resource, the request must include `expectedTargetName`. The runner performs a read-before-write lookup using the supplied ID and blocks the operation when the resolved name does not exactly match.

Folder and Data Table lookups are **exact-ID-or-block**: the runner no longer falls back to the first name returned by a list query.

For `delete_data_table_column` and `rename_data_table_column`, `expectedColumnName` must also match the exact resolved `columnId`. This prevents a valid table ID from masking a wrong column ID.

These controls protect against syntactically valid requests that target the wrong workflow, folder, Agent, Data Table, or column.

Creation operations are intentionally different: there is no pre-existing target to assert. Their payload is instead constrained by the live MCP schema and explicit write confirmation.

### Concurrency semantics

Writes use one concurrency group per branch with `cancel-in-progress:false`.

This guarantees the critical property: an already-running write is **not canceled** when a newer request arrives. Canceling an active runner would be unsafe because the remote mutation may already have committed even if GitHub has not recorded the response yet.

There is an important residual limitation: in the currently supported GitHub Actions concurrency behavior for this repository, only one pending run is reliably retained. A newer pending run may replace an older pending run. The attempted `queue:max` configuration was rejected by GitHub in this repository and is therefore not used.

Operational rule: **never submit a second write request until the previous write run has reached a terminal state**. ChatGPT must check the current `n8n MCP write` run before committing another request.

Concurrency is not a transaction or exactly-once mechanism. After any timeout, network disconnect, or ambiguous failure, perform a read-after-failure check before deciding whether to retry.

### Public-output policy

For writes executed from this public repository, the runner does not serialize the MCP response body into logs/artifacts. It records only:

- whether MCP marked the call as an error;
- whether structured content exists;
- returned content types;
- top-level structured-content keys.

If the MCP result has `isError:true`, the job fails and no success artifact is uploaded.

This is stricter than key-name redaction and avoids leaking unexpected business data under innocuous field names.


### Optional production approval gate

For a stricter production posture, the write job can be attached to a protected GitHub Environment whose deployment protection rules require approval and/or restrict allowed branches. GitHub withholds environment-scoped secrets until protection rules pass.

This is deliberately **not enabled** in the current bridge because it would require a human approval step for every write and reduce autonomous operation from ChatGPT. It is the recommended next control if the MCP token gains access to materially sensitive production operations.

The current `github.actor == github.repository_owner` condition is defense in depth, not a substitute for repository permissions or an Environment approval boundary.
