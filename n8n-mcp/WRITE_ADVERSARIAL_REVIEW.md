# n8n MCP Write Adversarial Review

## Scope

This review treats the GitHub Actions write bridge as an adversarial control plane. The goal is not only to prove that valid writes work, but to verify that ambiguous, stale, replayed, malformed, cross-target, and high-impact requests fail closed.

Reviewed components:

- `.github/workflows/n8n-mcp-write.yml`
- `n8n-mcp/write-request.json`
- `n8n-mcp/src/invoke.mjs`
- the live n8n instance-level MCP server
- GitHub Actions push/path/concurrency behavior

## Final posture

The write channel is suitable for non-secret control data in this public repository when used one request at a time.

It is **not** exactly-once transactional infrastructure and it is **not** a secure transport for confidential request arguments.

## Findings and mitigations

### Critical: active write cancellation could leave ambiguous remote state

Original risk:

- `cancel-in-progress:true` could terminate a runner after n8n had committed a mutation but before the result was recorded.
- A retry could then duplicate or overwrite state.

Mitigation:

- write concurrency now uses `cancel-in-progress:false`.
- an active write is never intentionally canceled by a newer request.
- GitHub reruns are blocked with `github.run_attempt == 1`.

Residual:

- the supported concurrency mode does not provide a durable arbitrary-depth FIFO queue.
- only submit the next write after the previous run reaches a terminal state.

### Critical: MCP domain failure could be reported as GitHub success

Original risk:

- `tools/call` may return a normal JSON-RPC result whose MCP payload has `isError:true`.
- the previous runner treated that as `ok:true`.

Mitigation:

- `isError:true` now throws and fails the job.
- verified using `create_folder` with an intentionally invalid project ID.

### High: valid ID could point to the wrong resource

Original risk:

- a syntactically valid workflow/folder/table/agent ID could target a real but unintended object.

Mitigation:

- protected mutations require `expectedTargetName`.
- the runner performs a read-before-write identity lookup.
- mismatch blocks before the mutation.
- folder and Data Table list lookups require an exact ID match and do not fall back to the first returned name.
- Data Table column rename/delete additionally require `expectedColumnName` matching the exact `columnId`.

Verified:

- an existing folder ID paired with an intentionally wrong expected name was blocked.
- the same ID paired with the correct expected name succeeded with an idempotent rename-to-same-name operation.

### High: insufficient confirmation for operations with external/destructive impact

Mitigation:

Two explicit confirmation levels exist:

- `confirmWrite:true` for every mutation/effect tool.
- `confirmRisk:true` additionally for high-impact operations.

High-risk currently includes workflow execution/testing/lifecycle and rollback operations, workflow updates, persistent Data Table mutations that can break consumers, Agent mutation/execution/lifecycle operations, and external Agent integration changes.

Verified:

- `archive_workflow` with `confirmWrite:true` but `confirmRisk:false` was blocked locally before a mutation.

### High: shallow local JSON Schema validation

Original risk:

- the previous preflight checked mostly top-level types.
- array cardinality, nested objects, enums, patterns, anyOf/oneOf/allOf, and numeric/string limits could reach the server unnecessarily.

Mitigation:

- recursive live-schema preflight now validates:
  - required properties
  - additionalProperties
  - object nesting
  - arrays and item schemas
  - minItems/maxItems
  - string length/pattern
  - enum/const
  - number limits
  - anyOf/oneOf/allOf
  - primitive types

Verified:

- `move_workflows_to_folder` with `workflowIds: []` was rejected locally for violating `minItems`.

The n8n server remains authoritative and performs its own validation.

### High: GitHub rerun/replay

Mitigations:

- each request has a UUID `requestId`;
- prior versions of `write-request.json` in branch history are scanned and a reused UUID is rejected;
- `github.run_attempt > 1` skips the write job;
- `targetRef` must exactly match `github.ref`.

Verified:

- deliberate duplicate `requestId` failed in the envelope gate and never reached the MCP invocation step;
- rerunning a failed write produced a skipped attempt 2.

Residual:

- a user with sufficient repository control can rewrite Git history or generate a new UUID for semantically identical work. Repository permissions remain part of the trust boundary.

### High: public repository output leakage

Original risk:

- key-name redaction is insufficient; business data can appear under arbitrary field names.

Mitigation:

- successful writes in a public repository do not serialize the full MCP response.
- write output is reduced to structural metadata:
  - `isError`
  - whether structured content exists
  - content types
  - top-level structured keys
- `outputMode=full` remains blocked in a public repository.

Verified:

- a successful hardened `update_folder` emitted only structural response metadata.

Residual:

- **request arguments themselves are committed to public Git history**. Never send secrets or confidential payloads in this bridge.

### High: mixed commit could smuggle code changes with the write request

GitHub `paths` means a workflow runs if a matching changed path is present; it does not mean that only that file changed.

Mitigation:

- checkout uses full history.
- the job diffs the push range.
- it fails unless the changed-file set is exactly:
  - `n8n-mcp/write-request.json`

The MCP token is not used after a failed single-purpose check.

### Medium: unauthorized branch/actor

Mitigation:

The write job requires:

- `github.actor == github.repository_owner`
- first run attempt only
- an approved control ref (`main` or the current MCP feature branch)
- `targetRef` matching the actual ref

The branch restriction is implemented at the job gate rather than `push.branches` because the feature-branch workflow was observed to behave inconsistently while the workflow itself was under active syntax changes.

After merge, remove the temporary feature branch from the allowed-ref expression and keep `main` (or move operations to a dedicated protected control branch).

### Medium: oversized request / accidental bulk payload

Mitigation:

- request JSON is limited to 64 KiB before MCP initialization.

Residual:

- complex workflow-creation code larger than this limit must use another controlled path rather than silently increasing the limit.

## n8n-specific safety implications

Official n8n documentation states that instance-level MCP access is user-scoped but not separately scoped per MCP client: connected clients can see the workflows/agents exposed for that n8n user. The GitHub bridge therefore cannot rely on n8n to isolate this client from another connected MCP client.

n8n also documents that:

- `execute_workflow` defaults to the published production version, while manual execution can run the current unpublished version;
- pinning/mocking is a development aid to avoid repeatedly hitting external systems;
- restoring workflow history changes the current editable version and should be treated as a rollback operation;
- Agents exposed through MCP are currently a preview feature and may change.

These behaviors justify the additional `confirmRisk`, target assertions, and read-after-write rules.

## Ambiguous failure protocol

A network timeout is fundamentally different from a clean validation failure.

If a write call times out or the connection drops after `tools/call` was sent:

1. Assume the mutation **may have happened**.
2. Do not use GitHub rerun.
3. Do not immediately send the same semantic write with a new UUID.
4. Read the target resource through the read channel.
5. Compare actual state to intended state.
6. Only then decide whether a compensating or new write is needed.

This is required because the bridge cannot provide a distributed transaction spanning GitHub Actions and n8n.

## Operational checklist

Before every real write:

1. Confirm no `n8n MCP write` run is active or pending.
2. Read the target resource and resolve IDs.
3. Generate a new request UUID.
4. Set the exact `targetRef`.
5. Use the narrowest tool and arguments.
6. Include `expectedTargetName` where required.
7. Include `expectedColumnName` for column rename/delete.
8. Set `confirmWrite:true`.
9. Set `confirmRisk:true` only after reviewing high-impact behavior.
10. Commit only `write-request.json`.
11. Wait for the run to finish.
12. Read the target again to verify the postcondition.
13. If ambiguous failure occurs, follow the read-before-retry protocol.

## Official references

n8n:

- https://docs.n8n.io/connect/connect-to-n8n-mcp-server/
- https://docs.n8n.io/build/work-with-data/pin-and-mock-data/
- https://docs.n8n.io/build/manage-workflows/view-change-history/
- https://docs.n8n.io/build/understand-workflows/save-and-publish-workflows/

GitHub Actions:

- https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow
- https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- https://docs.github.com/en/actions/concepts/workflows-and-actions/concurrency
