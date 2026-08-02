---
name: system-and-data-design
description: >
  Decide whether the system will hold, and where the data lives: requirements and load
  first, then back-of-the-envelope numbers, building blocks (cache, queue, load
  balancer, CDN), and the data layer in depth — storage engines, indexes, replication,
  partitioning, transactions and consistency, batch vs stream. Use when sizing or
  scaling anything; choosing a database, cache, queue or index; when asked "will this
  hold", "how many machines", "which database", "do we need a queue", "read replica",
  "sharding", "eventual consistency", "why is this query slow at scale"; when designing
  an ingestion or processing pipeline; or when a service is slow under load rather than
  wrong. Do NOT use for module layout, dependency direction or domain boundaries (use
  architecture-first), for function- and naming-level quality (use code-complexity), for
  restructuring code that is already too large (use refactoring-safely), or for a
  low-traffic internal tool where the honest answer is one process and one database.
---

# System and data design — will it hold, and where does the data live

Two questions that are usually asked together and answered separately, badly. Capacity
without storage internals gives a diagram that cannot be built; storage internals without
capacity gives a database choice with no reason behind it.

## Scope guard — read first

The most common failure here is answering at the wrong scale.

| Situation | Honest answer |
|---|---|
| Internal tool, tens of users | One process, one database, no cache. Stop. |
| Product with real traffic, single region | Estimate first; add a cache and a queue only where the numbers say |
| Multi-region, or data outgrowing one machine | Full pass: estimation → building blocks → replication/partitioning → consistency |

Adding a cache before measuring is the canonical way to convert one problem into two.

## Step 1 — requirements before architecture

- **Functional**: what must it actually do? Write it as verbs, not components.
- **Non-functional, with numbers**: users, requests/sec at peak, payload size, growth,
  read:write ratio, acceptable latency, acceptable staleness, retention.
- **Constraints**: budget, team size, existing stack, compliance, where data may live.

"Acceptable staleness" is the single most useful number and the one nobody asks for. It
decides caching, replication and consistency all at once.

## Step 2 — back-of-the-envelope, before any diagram

Estimate storage/day, bandwidth at peak, QPS, and working-set size. The point is not
precision; it is discovering that the answer is "one machine" or "this cannot work as
described" before drawing anything.

Anchors worth remembering: memory reads are ~100ns, SSD ~100µs, a same-region round trip
~0.5ms, cross-continent ~150ms. Anything crossing a network is ~1000× a memory access —
which is why one N+1 query pattern outweighs most micro-optimisation.

## Step 3 — building blocks, each with a reason

| Block | Add it when | Cost you accept |
|---|---|---|
| Cache | Read-heavy, tolerable staleness, measured hot set | Invalidation becomes your problem |
| Queue | Work can be async; spikes must be absorbed | Ordering, retries, duplicate delivery |
| Read replica | Reads dominate; stale reads acceptable | Replication lag becomes visible to users |
| Partitioning | One machine cannot hold data or throughput | Cross-partition queries and transactions get hard |
| CDN | Static or cacheable content, geographically spread | Purge and versioning discipline |

Each row is a trade, not an upgrade. A block added without its reason written down is a
future mystery.

## Step 4 — the data layer

- **Storage engines**: log-structured (LSM) favours writes and compaction; B-tree favours
  predictable reads and in-place updates. Choose by the workload's read:write shape, not
  by brand.
- **Indexes** are a write-cost you pay for a read-benefit. An index nobody's query plan
  uses is pure cost.
- **Replication**: single-leader is the default and enough for most systems; multi-leader
  and leaderless buy availability and pay in conflict resolution you must then design.
- **Partitioning**: choose the key by access pattern, not by what looks even. Hot keys
  and unbounded partitions are the two failures; both are visible in a histogram before
  they are visible in production.
- **Transactions**: know which isolation level you actually get. Read-committed does not
  prevent lost updates; "we use transactions" is not a consistency argument.
- **Batch vs stream**: batch for correctness and reprocessing, stream for freshness.
  Streams that cannot be replayed lose the ability to fix a bug retroactively.

## Review pass

- Is every component justified by a number, or by habit?
- What happens at 10× — which part breaks first, and is that acceptable?
- Where can it lose data, and is that written down?
- What is the failure mode of each dependency: degrade, queue, or fail loudly?
- Does any user-visible read cross a replication lag nobody bounded?

## References — load on demand

- `references/system-design/four-step-process.md`, `estimation-numbers.md`,
  `building-blocks.md`, `database-scaling.md`, `common-designs.md`,
  `reliability-operations.md`
- `references/ddia-systems/storage-engines.md`, `data-models.md`, `replication.md`,
  `partitioning.md`, `transactions.md`, `batch-stream.md`, `fault-tolerance.md`
- `*-original.md` — the source skills' own framework prose, kept verbatim

## Gotchas

- **Designing for a scale you do not have.** The cost is paid now, the benefit maybe
  never. Estimate first; the estimate frequently says "one machine".
- **Cache as a fix for a slow query.** It hides the query and adds invalidation. Fix the
  query, then decide about the cache.
- **Eventual consistency chosen by accident.** A read replica added for speed silently
  makes some reads stale. Decide which reads may be stale, and say so.
- **The queue that became a database.** Unbounded retention plus a consumer that never
  catches up is a data store with none of the guarantees of one.

## Troubleshooting

| Symptom | Likely cause | Where to look |
|---|---|---|
| Fine in test, slow in production | Working set exceeds memory; disk seeks per request | Storage engine, index coverage |
| Latency spikes at intervals | Compaction, GC, or a cron competing for IO | Storage engine internals, host metrics |
| One shard hot, others idle | Partition key follows structure, not access | Partitioning |
| Users see their own write disappear | Read served by a lagging replica | Replication, read-your-writes |
| Duplicate side effects | At-least-once delivery without idempotency | Queue semantics |
