# Remote transport safety

Date: 2026-07-28

This reference turns the local bridge lessons and current HTTP/SSH standards into
portable operating rules. It does not replace a provider's live limits or a host's
runbook.

## Connection hierarchy

1. Reuse an already verified bridge/session recorded by the local connection
   registry, if present.
2. If the route supports OpenSSH multiplexing, use a private `ControlPath` with
   `ControlMaster auto` and a bounded `ControlPersist` lifetime. Confirm the socket
   with a health probe before relying on it.
3. If multiplexing is unsupported or fails, batch the remote work into one command
   over the known bridge. A single short-lived batched connection is safer than many
   tiny logins.
4. If no route exists, stop and establish the documented bridge first. Do not guess
   a direct IP, bypass an access policy, or open parallel fallback routes.

`ControlMaster`/`ControlPersist` are optimizations, not a universal requirement.
ProxyCommand, Windows OpenSSH, and tunnel implementations can make a control
socket unusable. The fallback must be evidence-based and route-specific.

## Shared connection record

When the local registry is available, record only non-secret metadata:

```text
host_or_target
kind: tunnel | session | mount | rdp
route_or_alias
session_owner
created_at / heartbeat_at / ttl
health_probe
note: provider and purpose, not credentials
```

The registry is a coordination snapshot and its journal is an audit trail. A live
entry is a candidate for reuse; it is not proof that the far end is reachable.
Before reclaiming a stale entry, check the actual process/socket/tunnel. Mark a
provider or host locked out after a real lockout and stop knocking until the
documented cooldown expires.

## API request budget

Use one client/session per provider and task phase. A phase means one discovery,
one mutation, or one observation/reconciliation window for one provider/target.
Set a local budget before the first request:

```text
max_new_connections: 1 per provider/target/phase
max_parallel_requests: 1 by default
minimum_poll_interval: 5 seconds for ordinary status reads
max_status_reads: 12 per observation phase; switch long jobs to logs/webhooks
observation_deadline: explicit; default 15 minutes for readiness, then hand off
backoff: exponential with jitter, bounded by a task deadline
retryable: idempotent reads and explicitly idempotent mutations only
```

These are conservative local defaults, not vendor limits. Increase them only when
the provider documentation and the task's measured need justify it. Always:

- reuse HTTP keep-alive/connection pooling;
- group related reads instead of asking for the same state repeatedly;
- honor `Retry-After` on `429`/`503` before applying local backoff;
- stop at a retry/deadline budget and hand off the evidence;
- log counts, status classes, target IDs, and timestamps, never bearer tokens.

Use this default retry budget for an ordinary idempotent status read unless the
provider runbook says otherwise:

```text
max_attempts: 3 total, including the first request
backoff: 5s, 10s, 20s, capped at 60s, with bounded jitter
Retry-After: parse integer seconds or HTTP-date; use the larger of server delay and local backoff
invalid/missing Retry-After: use the local backoff, then stop at max_attempts
```

Record `attempt`, `status`, `retry_after`, `next_retry_at`, and `deadline` in the
local run journal. These values are local safety defaults, not permission to
approach a vendor's published limit.

For long jobs, use a webhook, stream, durable log, or checkpoint marker when the
provider supports it. Poll only the job that needs attention, and exit on a
terminal state. Never multiply a poll loop by the number of agents or open a new
authenticated client inside the loop.

## Mutation safety

Treat a lost response as an unknown outcome, not as a failure. Before retrying a
launch/restart/submit request:

1. preserve the request intent and local timestamp;
2. query the provider or bridge by exact ID, client idempotency key, or narrow
   creation-time/name filter;
3. distinguish “not created” from “created but not ready”;
4. retry only if the provider operation is documented as idempotent or the
   reconciliation proves no matching resource exists;
5. record the final state and cost evidence.

Do not use IP rotation, user-agent rotation, credential rotation, hidden retries, or
other evasion behavior as a substitute for respecting a service's limit. In a
read-only diagnosis, do not establish or re-register a missing bridge: report the
missing route and the exact one-probe authorization boundary instead.

## Standards and provider references

- OpenSSH `ControlMaster`, `ControlPath`, and `ControlPersist`: [ssh_config(5)](https://man7.org/linux/man-pages/man5/ssh_config.5.html).
- HTTP `429` and optional `Retry-After`: [RFC 6585](https://www.rfc-editor.org/rfc/rfc6585.html).
- HTTP `Retry-After` semantics: [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html#section-10.2.3).
- RunPod request limits and backoff guidance: [Send API requests](https://docs.runpod.io/serverless/endpoints/send-requests).
