# Prompt Caching and Cost Control

## Purpose

Prompt caching reduces repeated prefill work when multiple model calls share the same prefix. In long-running agents, this can materially reduce input-token cost and time-to-first-token latency.

Treat prompt caching as part of harness architecture, not as a provider afterthought. The context builder, tool registry, instruction manager, compactor, and telemetry layer all affect cache hit rate.

## Core rule: stable prefix, dynamic suffix

Most prompt-cache systems reward exact or near-exact prefix reuse. Design requests so stable content appears first and volatile content appears late.

Recommended ordering:

```text
1. Tool definitions, in deterministic order
2. Static system/developer instructions
3. Stable scoped instructions or skill index
4. Stable reference context likely to be reused
5. Prior conversation or typed event history, append-only where possible
6. Dynamic runtime environment
7. New user message or current task suffix
```

Dynamic values belong near the end:

```text
current date/time
request ID
session ID
working directory
cursor state
fresh search results
latest tool output
user's newest message
```

Do not put changing values at the start of the system prompt.

## Deterministic serialization

Cache stability depends on the byte-level or token-level request shape. Make serialization deterministic:

```text
stable tool order
stable JSON key order
stable schema formatting
stable instruction block order
stable skill listing order
stable whitespace where possible
versioned prompt bundles
versioned tool bundles
```

Avoid nondeterministic middleware that injects trace IDs, timestamps, randomized examples, or variable environment blocks into the stable prefix.

## Multi-turn behavior

Keep conversation and event history append-only until compaction is required.

Good shape:

```text
turn 1: stable_prefix + user_1
turn 2: stable_prefix + user_1 + assistant_1 + user_2
turn 3: stable_prefix + user_1 + assistant_1 + user_2 + assistant_2 + user_3
```

Bad shape:

```text
turn 2: rewritten summary of turn 1 + stable_prefix + user_2
turn 3: reordered tools + rewritten system prompt + user_3
```

Append-only history lets the provider reuse prior prefix work. Rewriting history every turn often destroys cache reuse.

## Compaction and caching

Compaction is often necessary, but it resets or changes the reusable prefix.

Use these rules:

```text
compact only when useful
make compaction boundaries explicit
make the summary itself stable after creation
do not rewrite the summary on every turn
preserve recent high-value messages exactly when possible
prune oversized tool outputs consistently rather than rewriting all history
store bulky artifacts externally and reference them
```

After one cold turn following compaction, the compacted summary can become part of the new stable prefix.

## Tools and schemas

Tool definitions are usually part of the reusable prefix. Tool churn can destroy cache hit rate.

Best practices:

```text
expose only relevant tools
sort tools deterministically
avoid dynamic text inside tool descriptions
version tool sets deliberately
separate stable tool guidance from dynamic tool availability notes
use deferred tool search for large tool inventories
keep structured output schemas stable
```

When a tool changes materially, record a prompt/tool bundle version so cache changes are explainable.

## Provider-specific implementation notes

### OpenAI

OpenAI prompt caching is automatic on supported API requests. Current OpenAI docs describe a minimum prompt length for caching, a `cached_tokens` usage field, and optional retention controls such as extended retention for supported models.

Implementation notes:

```text
log usage.prompt_tokens_details.cached_tokens
keep stable instructions and tools before volatile context
use provider-supported cache keys or retention parameters when appropriate
monitor cache hit rate, cost, and time-to-first-token
avoid overly narrow cache routing keys in low-traffic buckets
```

### Anthropic

Anthropic prompt caching commonly uses explicit cache-control markers or automatic caching, depending on the API path and model. Use provider documentation for the current exact syntax and TTL behavior.

Implementation notes:

```text
place cache markers after stable blocks, not before volatile blocks
respect provider limits on cache breakpoints
choose short or extended TTL based on expected inter-request gaps
monitor cache read and cache write token fields
```

### OpenAI-compatible and self-hosted APIs

OpenAI-compatible APIs vary widely. Some implement prefix caching, some only emulate OpenAI message shapes, and some expose backend-specific controls.

Implementation notes:

```text
test the exact provider and model
verify whether cached-token usage is reported
use tenant-safe cache isolation where supported
monitor backend prefix-cache hit-rate if self-hosted
keep request serialization stable even when cache support is uncertain
```

## Monitoring

Log cache diagnostics on every model call when available:

```json
{
  "request_id": "...",
  "session_id": "...",
  "provider": "openai|anthropic|openai-compatible",
  "model": "...",
  "prompt_bundle_version": "...",
  "tool_bundle_version": "...",
  "system_prompt_hash": "...",
  "tools_hash": "...",
  "input_tokens_new": 0,
  "cache_read_tokens": 0,
  "cache_write_tokens": 0,
  "cached_tokens": 0,
  "output_tokens": 0,
  "time_to_first_token_ms": 0,
  "total_latency_ms": 0,
  "estimated_cost": 0
}
```

Track:

```text
cache hit rate by session
cache hit rate by tenant or segment
unique system prompt hashes per day
unique tool bundle hashes per day
cost split: uncached input, cached input, output
latency split: prefill, time-to-first-token, generation
cache hit rate before and after compaction
```

Alert when a long-prefix agent unexpectedly reports zero cached tokens over many turns, or when stable prompt/tool hashes fragment unexpectedly.

## Cache-killing anti-patterns

Avoid:

```text
timestamp at the start of the system prompt
request ID in the stable prefix
randomized tool order
randomized JSON key order
injecting live environment state before static instructions
including per-user secrets in the prefix
rewriting conversation history every turn
re-summarizing the whole session every turn
changing schema formatting without versioning
putting volatile retrieval results before stable instructions
using overly granular cache keys with low request volume
failing to log cached-token fields
```

## Prompt-cache-aware context builder

A cache-aware context builder should produce two zones:

```text
stable_prefix:
  tool definitions
  static instructions
  scoped stable instructions
  stable skill index
  stable schemas and output contracts

volatile_suffix:
  current task
  dynamic runtime state
  latest observations
  new retrieved snippets
  approval request/response
```

This does not mean all stable content should always be included. Relevance still matters. The best request is both cache-friendly and context-efficient.

## Cost-control checklist

- Keep stable content before volatile content.
- Remove timestamps and request IDs from stable instructions.
- Sort tools and schemas deterministically.
- Log provider cache usage fields.
- Track system and tool hash fragmentation.
- Avoid compaction churn.
- Use long retention only when reuse justifies it.
- Prefer skill and tool progressive disclosure over loading huge inventories.
- Measure cost and latency before and after each prompt/tool bundle change.
