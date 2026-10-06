# n8n MCP Trigger Model

## Design goal

Repository maintenance must not call n8n accidentally.

There are only two automatic MCP entry points:

| Workflow | Automatic trigger | Purpose |
|---|---|---|
| `n8n MCP read` | push changing only `n8n-mcp/read-request.json` | one explicit read request |
| `n8n MCP write` | push changing only `n8n-mcp/write-request.json` | one explicit confirmed write request |

All other MCP workflows are manual-only:

- `n8n MCP diagnostic`
- `n8n MCP invoke`
- `n8n MCP read suite`
- `n8n MCP write suite`

## Why request-file triggers exist

The GitHub connector available to ChatGPT can update repository files but does not currently expose a workflow-dispatch action in this environment.

GitHub also requires a `workflow_dispatch` workflow file to exist on the repository default branch before it can receive manual dispatch events. During development on a feature branch, relying exclusively on `workflow_dispatch` would make the bridge unusable from this connector.

A path-filtered request file is therefore the narrowest usable trigger:

- ordinary code changes do not invoke n8n;
- documentation changes do not invoke n8n;
- workflow maintenance does not invoke n8n;
- changing the read request invokes only the read runner;
- changing the write request invokes only the write runner.

## GitHub Actions behavior to remember

GitHub evaluates `paths` against files changed by a push. If at least one changed path matches, the workflow can run.

A matching path is enough for GitHub to create a workflow run, so `paths` alone does not prove that the commit changed only the request file. The write job therefore performs a second check using the push range and rejects the run unless the only changed file is `n8n-mcp/write-request.json`.

For manual workflows, `workflow_dispatch` becomes useful after these workflow files reach the default branch.

## Concurrency

Read and write use separate concurrency groups.

For writes, `cancel-in-progress:false` is mandatory. A write runner that has started must never be canceled merely because a newer request arrived: the remote n8n mutation may already have happened.

GitHub's compatible concurrency behavior here does **not** provide a durable FIFO queue for an arbitrary number of pending writes. Only submit one write at a time and wait for the current run to finish before committing another write request.

For reads, cancellation of obsolete runs is acceptable because reads do not mutate n8n.

Do not share a concurrency group between read and write.

## Secret model

- `N8N_MCP_TOKEN` -> GitHub Actions secret.
- `N8N_MCP_URL` -> GitHub Actions repository variable.
- Neither value belongs in tracked files.
- Logs/artifacts must never contain the bearer token.
