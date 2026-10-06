# CFO Telegram / Provider Remediation

## Incident

A Telegram turn reached the router and the CFO workflow correctly. Telegram delivery was healthy.

Relevant chain:

- Telegram parent execution: `1215`
- CFO child execution: `1217`
- CFO workflow: `QBCmQypRRV25Ln8F` — `11 - CFO Conversacional`

Telegram accepted both the acknowledgement and the terminal fallback response. The business receipt classified the turn as:

```text
status = assistant_unavailable
verified = false
notification_sent = true
```

The failure occurred after the first successful model response and subsequent tool calls. The first DeepSeek call completed with `finish_reason=tool_calls`; the agent then continued through financial read tools and later failed to obtain a provider response.

This is therefore not a Telegram connectivity failure.

## Specific remediation implemented

### Model-only retry

`DeepSeek CFO Model` now uses:

```text
retryOnFail = true
maxTries = 3
waitBetweenTries = 1500 ms
```

The root Agent deliberately remains:

```text
retryOnFail = false
```

Do not enable whole-Agent retry without a stronger transaction boundary. The Agent has access to tools that can write financial state; replaying the Agent can replay tool decisions.

### Context and latency bounds

The following limits were reduced:

```text
Simple Memory context window: 12 -> 8

Interactive max output:
8192 -> 4096 tokens

Daily/weekly batch max output:
16384 -> 8192 tokens

Model timeout:
180000 ms -> 90000 ms
```

The Agent max-iteration policy was deliberately left unchanged:

```text
interactive: 12
daily/weekly/scheduled reconciliation: 35
```

Changing that limit without observing the new provider behavior could truncate legitimate multi-tool reconciliation turns.

## Why this retry boundary matters

Retries belong around the transient provider call, not around a transaction-capable Agent.

A safe financial retry boundary is:

```text
Agent decision
  -> provider model call may retry
  -> tool request
  -> Controlled Writer
       -> deterministic external_key
       -> exclusive writer lock
       -> intent record
       -> Firefly write
       -> post-write verification
       -> audit record
       -> release lock
```

## Controlled Writer audit

`WF — CFO Controlled Writer` already contains:

- context validation;
- deterministic `external_key`;
- intent registration;
- exclusive writer lock;
- pre-write state read;
- safe write preparation;
- post-write Firefly verification;
- verified receipt;
- audit storage;
- lock release;
- a dedicated error workflow;
- caller policy restricted to workflows from the same owner.

Concurrent execution `1058` was rejected as `busy` while execution `1057` owned the writer. The second execution did not reach `Escribir Firefly`.

Do not replace this mutex/audit design casually.

## Remaining architectural risks

### Tool result amplification

During incident `1217`, an account-activity tool was asked for:

```text
start = 2015-01-01
end = 2026-10-05
limit = 200
```

The initial model call already used more than 22k total tokens before later tool results were fed back into the Agent. Long historical reads can therefore amplify context substantially.

Preferred future design:

- enforce server-side/tool-level result limits;
- use aggregation before raw transaction lists;
- default interactive queries to recent windows;
- paginate deliberately;
- reserve large historical scans for scheduled reconciliation;
- never depend only on prompt instructions to limit data.

### Error semantics

n8n execution status can be `success` while the CFO business receipt is `assistant_unavailable`, because the workflow intentionally handles the provider failure and sends a truthful fallback.

Monitoring must use the CFO receipt/business status, not only n8n's top-level execution status.

### Model fallback

OpenRouter already performs provider routing for the selected model. Do not add a second Agent as a naive fallback.

A cross-model fallback is acceptable only when:

1. the fallback receives the same read-only conversational state;
2. writes remain exclusively behind the Controlled Writer;
3. the same deterministic write intent key is preserved;
4. tool calls cannot be replayed blindly.

## Operational rule

For provider failures:

1. retry only the model subnode;
2. if retries fail, return the truthful fallback;
3. preserve the turn receipt as `assistant_unavailable`;
4. do not automatically replay the entire Agent or financial writes;
5. investigate the provider/model execution using the receipt and execution IDs.

## Validation still required

The configuration changes are saved in n8n and verified by read-after-write.

A new real Telegram turn is still needed to prove the full path end-to-end under the remediated configuration. Until such a turn completes, treat the remediation as configuration-validated, not incident-reproduction-validated.
