# Remote compute provider matrix

Date: 2026-07-28

Use this as a routing map. Provider details and limits can change; refresh the
linked documentation and live account state before a mutation.

Classify the mode from an existing endpoint/pod/instance/job identity before
choosing transport. A Serverless job is controlled by endpoint API/job events;
SSH belongs to an actual Pod or a server with a verified route.

| Provider/mode | Control plane | Data/ops plane | Default observation | Main guard |
|---|---|---|---|---|
| RunPod Serverless | REST API / SDK | endpoint job, webhook, stream, logs | job ID plus `/status`, `/health`, or webhook | scale-to-zero default; no diagnostic Pod unless required |
| RunPod Pod | REST/CLI/console | SSH, TCP/HTTP proxy, logs | pod ID plus SSH/service/output probe | persistent hourly resource; exact owner and cleanup condition |
| Massed Compute VM | Massed MCP/API | SSH from the provider's returned target | instance UUID plus SSH/GPU/process/log probe | read-only key first; full-scope mutations only when needed |
| Owned/virtual server | local inventory/runbook | existing SSH/tunnel/VPN bridge | bridge health plus one batched remote probe | no guessed direct route; no repeated login flood |

## RunPod

The official API reference says requests use an API key and exposes Pods,
Serverless endpoints, network volumes, templates, and billing. Serverless job
operations include `/run`, `/runsync`, `/status`, `/stream`, `/cancel`, and
`/health`. The official request guide publishes per-endpoint operation limits and
returns `429` when the effective limit is exceeded; it recommends exponential
backoff. The currently published examples include `/run` at 1000 requests per 10
seconds and `/status` at 2000 requests per 10 seconds, but treat those numbers as
versioned provider data, not a local target.

For Serverless, submit once, retain the returned job ID, and use the provider's
status/stream/webhook path. For Pods, use key-based authentication and the exact
SSH command/route shown by the Pod's Connect panel; do not infer a proxy, public
IP, or port. Prefer one verified SSH route for long-running work.

## Massed Compute

The official MCP overview documents the MCP endpoint and says the same API key is
used for the assistant and scripts. The tools reference separates read-only tools
from full-access launch/restart/terminate/key-management tools; hidden mutation
tools are an intentional safety boundary. The troubleshooting guide says a `429`
means request limits were hit and recommends waiting before trying again.

Use live MCP tool discovery and the existing Massed recipes for exact operations.
Do not turn the provider-specific tool names into the universal skill's workflow;
keep them inside this adapter boundary.

## Owned or virtual servers

There is no universal provider API. First inspect the bridge registry and the
documented route, then batch a read-only probe for host identity, GPU, process,
disk, service, and durable log state. Keep the bridge open for the whole phase or
reuse the existing one. If the route is temporarily locked out, stop issuing new
connections and resolve the access condition; do not probe harder.

## Source references

- [RunPod API overview](https://docs.runpod.io/api-reference/overview)
- [RunPod request operations and rate limits](https://docs.runpod.io/serverless/endpoints/send-requests)
- [RunPod Serverless operation reference](https://docs.runpod.io/serverless/endpoints/operation-reference)
- [RunPod SSH](https://docs.runpod.io/pods/configuration/use-ssh)
- [Massed Compute MCP overview](https://vm-docs.massedcompute.com/docs/mcp/overview)
- [Massed Compute tools reference](https://vm-docs.massedcompute.com/docs/mcp/tools)
- [Massed Compute troubleshooting](https://vm-docs.massedcompute.com/docs/mcp/troubleshooting)
