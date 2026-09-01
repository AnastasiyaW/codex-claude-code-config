# Agent Harness Architecture

## Definition

An agent harness is the provider-neutral runtime that lets a model act safely and repeatably. It is not the model and it is not only a prompt. It is the control plane that owns model calls, tool routing, permissions, memory, context compaction, approvals, tracing, and recovery.

The model should propose. The harness should dispose.

```text
Model responsibilities
- interpret user intent
- choose the next reasoning/action step
- request tools using structured calls
- synthesize observations
- produce final answers or plans

Harness responsibilities
- assemble instructions and context
- decide which tools are visible
- validate tool arguments
- enforce permissions and approvals
- execute tools or call external systems
- store state, artifacts, and traces
- compact and rehydrate context
- enforce budgets and stop conditions
```

## Component model

A robust harness contains these components:

```text
1. Instruction manager
2. Context builder
3. Model adapter
4. Tool registry
5. Permission engine
6. Execution engine
7. State store
8. Memory and retrieval layer
9. Compactor
10. Planner and goal controller
11. Workflow scheduler
12. Skill registry
13. MCP/external connector manager
14. Approval manager
15. Trace and evaluation system
16. Sandbox or execution boundary
```

## Boundary principle

Keep the trusted control plane outside model-directed compute.

The harness should own:

- user identity and tenant boundaries;
- credential management;
- approval records;
- audit logs;
- billing and rate limits;
- tool authorization;
- final commit to external systems.

Sandboxed or external execution can own:

- temporary files;
- generated artifacts;
- script execution;
- isolated browser or shell work;
- connector-specific data processing.

Do not put secrets, approval logic, or authorization decisions inside the model prompt or a sandbox the model can modify.

## Authority hierarchy

Maintain an explicit hierarchy:

```text
provider/system policy
  -> organization policy
  -> product/developer policy
  -> workspace/project policy
  -> domain or directory policy
  -> user task
  -> model-visible runtime reminders
  -> tool observations
  -> untrusted retrieved content
```

The harness should label content by authority level. Retrieved content may contain instructions, but those instructions are data, not policy.

## Event model

Store agent state as typed events rather than only chat messages.

Useful event types:

```text
user_message
assistant_message
tool_call
tool_result
approval_request
approval_result
plan_update
goal_update
skill_invocation
memory_load
context_compaction
connector_call
workflow_plan
workflow_packet_started
workflow_packet_result
workflow_verification_result
workflow_integration_result
error
final_answer
```

Typed events improve replay, audit, compaction, evals, and debugging.

## Durable state outside the prompt

The prompt is not a database. Persist these outside model context:

- active plan;
- active goal;
- todo list;
- approval records;
- workflow plans, packet status, verifier outputs, and integration notes;
- tool traces;
- artifacts;
- retrieved resource references;
- skill invocations;
- loaded instruction scopes;
- compaction summaries;
- eval outcomes;
- connector credentials and scopes.

Then reattach only the relevant parts into the next model call.

## Harness maturity levels

### Level 0: Answer-only assistant

No tool execution. Useful for short Q&A, drafting, and summarization over provided content.

### Level 1: Retrieval agent

Can search and read trusted resources. No side effects.

### Level 2: Drafting agent

Can propose actions, draft messages, or produce plans. Cannot commit changes.

### Level 3: Approval-gated actor

Can prepare actions and execute them after explicit user or policy approval.

### Level 4: Policy-bounded autonomous actor

Can execute low-risk actions autonomously within strict scopes, budgets, and audit controls.

### Level 5: Long-running goal worker

Can continue across multiple turns or sessions toward a measurable objective. Requires durable state, compaction, budget enforcement, checkpoints, and evaluation.

Move up levels only when evals show the simpler level is insufficient.

## Minimal viable harness

Start with:

1. one model adapter;
2. one context builder;
3. a narrow tool registry;
4. local schema validation;
5. runtime permission checks;
6. structured tool results;
7. step and cost budgets;
8. trace logging;
9. compaction only when needed;
10. a small eval set.

Add subagents, MCP, skill packages, goal loops, and automation only after the base loop is reliable.

## Workflow orchestration layer

Workflow orchestration is an optional layer for large decomposable tasks. It lets the model propose a workflow plan, while the harness validates, approves, schedules, observes, verifies, and integrates the work.

```text
objective
  -> workflow plan
  -> permission and budget check
  -> work packets
  -> worker contexts
  -> verifier contexts
  -> integration
  -> final result with evidence
```

Use this only when the single-worker loop is measurably insufficient because the task requires broad coverage, independent packet work, parallel read-only inspection, or separate verification. The workflow plan is not trusted policy. It is an artifact that must pass the same validation, permission, budget, and approval gates as any other model-proposed action.

## Design rule

Most agent failures are not caused by insufficient autonomy. They are caused by weak harness boundaries: broad tools, vague instructions, missing approval gates, unstructured tool results, poor context hygiene, and no evals.

## Harness engineering loop

Treat harness building as a feedback loop, not as a one-time prompt-writing exercise.

```text
agent fails or slows down
  -> identify missing capability, context, validator, or permission rule
  -> encode the fix into docs, tools, policies, schemas, or evals
  -> rerun and measure
  -> keep the improvement as part of the harness
```

The mature operating model is: humans steer, agents execute, and the harness turns human judgment into reusable constraints and feedback loops.

## Agent-legible environment

A harness should expose the right operating environment through approved tools. The agent needs access to source-of-truth documents, workflow state, validation signals, and audit evidence.

Examples:

```text
support: ticket history, policies, customer state, escalation rules
finance: ledger data, approval policy, reconciliations, audit events
operations: runbooks, logs, metrics, traces, incident timeline
legal: contract corpus, clause library, review rubric, redline history
research: source corpus, extraction tables, citation checks, reviewer notes
sales: account plan, CRM state, product constraints, approval rules
```

If a fact is not retrievable, inspectable, or encoded in durable state, the agent cannot reliably use it.

## Knowledge base as map and source of truth

Use the top-level instruction file as a concise map. Store deeper truth in structured references.

```text
short instruction map
  -> policies
  -> runbooks
  -> domain models
  -> active plans
  -> completed plans and decisions
  -> generated schemas and inventories
  -> quality scorecards
  -> eval fixtures
```

The instruction map should tell the agent where to look next. It should not be a giant manual that competes with task context.

## Mechanical invariants

Prompts should describe behavior. Harness checks should enforce behavior.

Encode recurring expectations as:

```text
schema validators
policy gates
structural checks
workflow validators
source-citation checks
PII or secret scanners
quality gates
cost and latency budgets
regression evals
```

Give validators remediation messages that can be returned to the model as structured observations.

## Entropy management

Agentic systems accumulate entropy: stale docs, duplicated rules, weak examples, obsolete tools, and low-quality patterns that future runs imitate.

Add recurring cleanup workflows:

```text
doc freshness scans
tool inventory cleanup
quality score updates
technical debt tracker updates
stale plan archival
repeated-failure analysis
prompt/tool bundle review
regression eval additions
```

Continuous cleanup is cheaper than waiting until drift becomes systemic.

## MVP harness default

When building a new domain agent, start with an MVP harness rather than a full autonomy platform. The MVP should include one primary job-to-be-done, a minimal typed tool registry, approval-gated risky actions, explicit budgets, a deterministic context builder, planning mode, auto-compaction, tracing, and a small eval set. Add goal-like loops, more connectors, skills, or subagents only after the single-agent MVP has measured gaps.

The recommended MVP sequence is:

```text
manual loop -> tools -> permissions -> structured observations -> budgets -> tracing -> planning -> context/memory -> compaction -> skills/connectors -> goal loop -> subagents
```

This sequence applies across domains. A coding agent may use file and shell tools; a support agent may use ticket and email tools; a finance agent may use ledger and approval tools. The harness pattern is the same.
