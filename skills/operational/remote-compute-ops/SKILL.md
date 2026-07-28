---
name: remote-compute-ops
description: "Operate GPU and remote compute across RunPod (Pods and Serverless), Massed Compute VMs, and owned or virtual remote servers through existing bridges, SSH sessions, MCP/API adapters, bounded polling, cost controls, and resumable lifecycle checks. Use when the user mentions RunPod, Massed Compute, a remote GPU/server/VM, SSH bridge/tunnel/bastion/Tailscale, training or inference on rented compute, GPU inventory, billing, or asks to minimize API/SSH connections and avoid rate limits. Do not use for generic cloud architecture, local-only GPU work, or application code with no remote-resource operation."
---

# Remote compute operations

Use this skill as the provider-neutral workflow for remote GPU and server work. The
provider is an adapter, not the name of the skill: RunPod, Massed Compute, and an
owned/virtual server must all follow the same evidence, transport, lifecycle, and
handoff rules.

When auditing this skill or designing a plan offline, do not call a provider, SSH,
or bridge at all; state that live mode/identity is unproven. The read-only lookup
below applies only when the user explicitly asks to inspect live remote state.

## Non-negotiable transport rule

Reuse the already-created bridge or live connection before opening a new one. The
purpose is reliable, rate-limit-compliant operation and avoiding unnecessary
authentication attempts; never disguise traffic, evade a provider limit, rotate
identities, or bypass a ban.

- Inspect the local connection registry/bridge health when one exists. A registry is
  a coordination hint, not proof that a tunnel is alive. Resolve the existing
  helper through `%USERPROFILE%\\.claude\\scripts\\conn_registry.py` on Windows or
  `$HOME/.claude/scripts/conn_registry.py` on POSIX when that file exists; if it is
  not discoverable, report “registry unavailable” instead of guessing a path.
- In a read-only investigation, do not create or re-register a bridge. If a live
  route is required, allow at most one explicitly authorized health probe. Record
  the host alias/route, registry entry age, session owner, local PID/service or
  control-socket metadata when available, target identity, last probe result, and
  whether a probe was permitted; never record credentials.
- Use one persistent provider client/session per task phase. Group compatible
  read-only queries and reuse keep-alive connections; do not create a client or
  authenticate once per command.
- The bridge probe has the stricter budget: local registry/config inspection is
  network-free, but SSH/tunnel health is at most one attempt total per target and
  phase, with no SSH retry after a timeout or connection error. The API-read retry
  budget in [transport-safety.md](references/transport-safety.md) does not apply to
  that probe.
- Batch related remote shell checks into one SSH invocation. Use
  `ControlMaster`/`ControlPersist` only after the exact route has passed a health
  check. If multiplexing fails on the platform or bridge, do not retry it blindly:
  use one batched command over the known working bridge.
- Do not fan out API or SSH calls merely to reduce wall-clock time. Parallelism is
  allowed only when the provider documents it, the connection budget allows it, and
  the calls cannot duplicate a mutation.
- For `429`, `503`, connection resets, or transport timeouts, stop increasing the
  request rate. Honor `Retry-After`, use bounded exponential backoff with jitter,
  and record the retry budget. See [transport-safety.md](references/transport-safety.md).

## Workflow

### 1. Freeze the target and read the architecture

Before a remote mutation, read the repository `AGENTS.md`, provider runbook, and
the relevant reference. Establish:

- provider and mode (RunPod Pod, RunPod Serverless, Massed VM, or owned server);
- exact target ID/name, region, image/template, job ID, and intended outcome;
- traffic path: existing bridge, bastion, VPN/Tailscale, SSH host alias, proxy, or
  provider API endpoint;
- current checkout, deployment/source revision, process/job state, storage and
  checkpoint path, and cost/burn boundary.

Do not infer a live state from a stale handoff, old dashboard, or a command that
only proves that a process exists locally.

### 2. Classify the provider mode before choosing a channel

Use existing target metadata first. If the mode is unknown, make one read-only
control-plane lookup and classify it before touching SSH:

- **RunPod Serverless:** endpoint/job ID, `/run`/`/status`/`/health`, webhook, or
  stream. Do not try to SSH to a Serverless job.
- **RunPod Pod:** exact Pod ID plus a documented SSH/TCP/HTTP connection route and
  exact bridge/host alias. Use SSH only when the target is an actual Pod and the
  route is already verified; never infer Pod identity from a generic job name.
- **Massed VM:** instance UUID and the provider-returned SSH target, plus Massed
  MCP for account/instance state.
- **Owned/virtual server:** documented host alias and existing bridge/tunnel.

If the provider or mode remains ambiguous after that one lookup, stop and report
the missing identity instead of opening a second kind of connection.

### 3. Reconcile read-only state through the cheapest valid path

Prefer this order:

1. existing bridge/session health and the shared connection registry;
2. one batched remote probe for host, GPU, process, disk, and durable logs;
3. one provider client session for exact inventory, billing, target, or job state;
4. a second provider call only when the first result is incomplete or ambiguous.

For long jobs, prefer durable logs, checkpoints, job events, or a webhook over a
tight status loop. If polling is the only supported observation path, use one
job-specific timer with a minimum interval, a maximum deadline, a request budget,
and terminal-state exit. Never poll every target independently from several agents.

### 4. Select the provider adapter

Read [provider-matrix.md](references/provider-matrix.md) and then the provider's
existing detailed skill/runbook when available.

- **RunPod:** use the local `runpod-gpu-ops` skill if it is installed; otherwise
  use [provider-matrix.md](references/provider-matrix.md) and the linked official
  RunPod docs for account-specific images, volumes, and lifecycle. Serverless is
  the default for scale-to-zero inference; a Pod is a persistent billed resource
  and needs an explicit reason plus a cleanup owner. Use the returned
  endpoint/job/pod ID as the identity for all later calls.
- **Massed Compute:** use the Massed MCP tools and read
  [massed-compute-recipes.md](references/massed-compute-recipes.md) for
  provider-specific recipes. Prefer read-only tools first; destructive tools may
  be absent from a read-only key by design. Keep the MCP session and reconcile
  after any timeout before considering a retry.
- **Owned or virtual server:** do not invent a cloud API. Reuse the verified SSH or
  tunnel route, batch probes, inspect the actual service/process/GPU/log state, and
  use the host's runbook for restart or shutdown decisions.

### 5. Mutate only the named resource

Launching or restarting affects cost and capacity. State the chosen target, image,
quantity, region, expected hourly/per-job burn, checkpoint/storage path, and stop
condition before executing within the user's request.

Termination, deletion, key removal, volume destruction, and any action that can
lose unrecoverable work require exact target disclosure, explicit confirmation,
the smallest possible scope, and post-action verification. A vague label such as
"the idle pod" is not an exact target.

### 6. Reconcile instead of duplicating

Every mutation must have an identity and a durable observation record. If a launch
or restart times out, assume it may have succeeded: list/get by exact ID, name,
client idempotency key, or a narrow creation-time filter before retrying. Do not
send a second launch because the first response was lost.

For each state transition, record provider, target ID, bridge/session used, source
revision, last observation timestamp, state, job/checkpoint marker, and next
allowed action. Do not record tokens, passwords, private keys, or full response
bodies containing credentials.

### 7. Close the loop

After launch/restart/deploy, verify the actual user-facing or job outcome, not only
that a VM is listed as `running`:

- SSH/bridge reaches the intended host;
- GPU and process are the expected ones;
- service/job health is ready and the first safe probe succeeds;
- output/checkpoint/log marker advances;
- cost and cleanup owner are known.

If a remote action is left running, write the handoff/journal entry and state the
exact next observation. Do not leave a paid resource without a shutdown rule.

## Gotchas

- Provider rate limits are not interchangeable. RunPod publishes limits per
  endpoint and operation; Massed Compute documents a generic 429 recovery path.
  Always re-check the current provider page and response headers.
- An SSH control socket can be unsupported or broken on a particular Windows or
  ProxyCommand route. The safe fallback is one batched connection, not a storm of
  short SSH calls and not an unverified direct route.
- A “running” Pod can still be starting a service; a Serverless `/health` result is
  not the same as a completed job. Check the service/job marker and logs.
- A timeout is an ambiguous mutation result. Reconcile by exact identity before
  retrying; never rely on a fresh list alone when multiple jobs have similar names.
- A shared connection registry can contain stale entries. Heartbeat expiry narrows
  the candidates but cannot replace an external health probe.
- API keys and VM passwords stay in the approved local secret store or provider
  UI. Never copy them into this skill, a handoff, Git, or a command transcript.
- Do not terminate a GPU merely because it is idle for one observation. Compare the
  active task, owner, checkpoint/output progress, and declared stop condition.

## Troubleshooting

- **Several agents keep opening SSH/API sessions** -> inspect the shared connection
  registry and active bridge, nominate one owner for the connection, batch the
  remaining checks, and make other agents consume the durable log/heartbeat.
- **`429` or `503`** -> stop fan-out, honor `Retry-After`, back off with jitter,
  reduce polling frequency, and retry only idempotent reads. For an ambiguous
  mutation, reconcile first.
- **ControlMaster reports a socket or getsockname error** -> mark multiplexing
  unavailable for that route, use the verified bridge with one batched command, and
  preserve the local guard/reminder that prevents repeated calls.
- **RunPod shows a healthy endpoint but the job is stuck** -> inspect queue/worker
  state and job status, then worker logs and the actual output marker. Do not create
  a diagnostic Pod by default.
- **Massed tools are missing** -> check the MCP entry and token scope; a read-only
  key intentionally hides launch/restart/terminate/key-management tools. Do not
  compensate with ad-hoc REST calls unless the provider runbook explicitly allows it.
- **A launch command timed out** -> list/get the exact target and check billing,
  inventory, and capacity before any retry. Treat the first request as possibly
  successful.
- **A bridge is recorded but unreachable** -> do not re-register or reconnect in a
  read-only investigation. Report the route/alias, registry age, owner/session,
  local PID/service or control-socket metadata when available, last health result,
  target identity, and whether one authorized probe was allowed. Perform only the
  local checklist: registry heartbeat/TTL, bridge process/socket presence, SSH
  alias and ProxyCommand mapping, and bridge-owner confirmation. Never reclaim a
  live tunnel based only on a stale timestamp.
