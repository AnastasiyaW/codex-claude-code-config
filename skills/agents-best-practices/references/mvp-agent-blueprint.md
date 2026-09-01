# MVP Agent Blueprint Builder

Use this reference when the user asks to make, build, design, scaffold, or specify an agent for a domain. The output should be a concrete MVP harness blueprint that can guide implementation across OpenAI, Anthropic, or OpenAI-compatible APIs.

The goal is not to design every future feature. The goal is the smallest safe version that can do useful work, with clear upgrade paths.

## MVP definition

An MVP agent harness includes:

1. A domain objective and user persona.
2. A minimal but useful autonomy level.
3. A provider-neutral model-tool-observation loop.
4. A small typed tool registry.
5. A runtime permission matrix.
6. Structured tool results and errors.
7. A context builder with scoped instructions and retrieval.
8. Memory and durable state outside the prompt.
9. Auto-compaction behavior for long sessions.
10. Planning mode for high-risk or ambiguous work.
11. Goal-like loop behavior for longer objectives.
12. Skill and connector attachment strategy.
13. Prompt-cache-aware and cost-aware context layout.
14. Observability and incident readiness.
15. Evals and launch criteria.
16. A minimal implementation path.

Coding is only one possible domain. Apply the same structure to research, operations, sales, finance, support, legal, healthcare, education, procurement, HR, analytics, and workflow automation agents.

## Domain intake

When the domain is underspecified, infer reasonable defaults and state them briefly. Do not block the MVP on excessive clarification.

Capture:

```text
Domain:
Primary user:
Primary job-to-be-done:
Inputs:
Outputs:
Systems of record:
Risk level:
Allowed actions:
Forbidden actions:
Approval-required actions:
Completion signal:
```

If the user gives only a domain, produce the MVP with assumptions:

```text
Assumptions:
- The first version is approval-gated for external or irreversible actions.
- The agent can read approved source-of-truth systems.
- The agent can draft outputs and propose changes.
- The agent cannot commit high-risk actions without approval.
- The first launch uses a single-agent harness unless evals show decomposition is required.
```

## Default MVP autonomy levels

Choose the lowest autonomy level that still creates value.

```text
Level 0: Answer-only
- The agent reads context and answers.
- No actions beyond retrieval and summarization.

Level 1: Draft-only
- The agent drafts recommendations, messages, reports, plans, or updates.
- Humans commit all changes.

Level 2: Approval-gated action
- The agent proposes actions and pauses for approval before side effects.
- Good default for most business agents.

Level 3: Policy-bounded autonomous action
- The agent can execute low-risk actions inside explicit policy.
- Requires strong logging, evals, and rollback paths.

Level 4: Long-running autonomous objective
- The agent pursues a measurable goal across checkpoints and budgets.
- Use only after the base harness is reliable.
```

Default to Level 1 or Level 2 for most MVPs.

## Coding-agent MVP profile

Use [coding-agents.md](coding-agents.md) when the requested agent reads, edits, tests, reviews, migrates, or opens changes against a software repository.

A coding-agent MVP remains a specialization of this generic blueprint:

```text
MVP coding agent = draft + verify + explain.
Not merge + deploy + own production.
```

That reference contains the concrete loop, task profiles, baseline tools, permission defaults, command policy, implementation invariants, evals, checklist, and anti-patterns for repository-facing agents.

## MVP output structure

Use this structure when generating a domain-specific MVP agent.

```markdown
# MVP Agent Harness Blueprint: [domain/use case]

## 1. Objective
[What the agent does, for whom, and what output counts as useful.]

## 2. MVP scope and assumptions
[Smallest useful version, explicit assumptions, non-goals, and deferred capabilities.]

## 3. Autonomy and risk level
[Answer-only, draft-only, approval-gated action, or policy-bounded action.]

## 4. Core agentic loop
[Provider-neutral loop, model calls, tool calls, observations, retries, budgets, and stopping.]

## 5. Context and instruction architecture
[System/developer/user instructions, scoped domain memory, source-of-truth retrieval, trust boundaries.]

## 6. Tool registry
[Minimal tools, schemas, risk classes, permission policy, structured outputs.]

## 7. Planning behavior
[When the agent must plan, what is allowed during planning, plan artifact, approval to execute.]

## 8. Goal-like loop behavior
[When a longer objective can run, budget, checkpoints, progress log, done condition, stop rules.]

## 9. Context, memory, and auto-compaction
[Durable state, retrieval, compaction triggers, handoff summary, rehydrated artifacts.]

## 10. Skills and connectors
[Reusable skills, MCP/external connectors, progressive disclosure, namespacing, connector permissions.]

## 11. Prompt caching and cost-aware context
[Stable prefix, dynamic suffix, cache telemetry, result-size limits, summarization strategy.]

## 12. Safety and approval policy
[Prompt injection handling, secrets, sandboxing, human review, audit logs.]

## 13. Observability
[Trace events, metrics, replay, auditability, and incident response.]

## 14. Evals
[Eval cases, failure probes, trace grading, regression suites, and launch criteria.]

## 15. Minimal implementation path
[Build order for a working MVP.]

## 16. First release checklist
[Concrete pass/fail checks before limited rollout.]
```

## Core loop template

A domain MVP should include an explicit loop.

```python
def run_agent(task, session):
    session.add_event("user_message", task)

    for step in range(session.max_steps):
        context = context_builder.build(session)

        if context.needs_compaction():
            session = compactor.compact_and_rehydrate(session)
            context = context_builder.build(session)

        model_output = model.generate(
            context=context,
            tools=tool_registry.visible_tools(session),
        )
        session.add_event("model_output", model_output)

        if model_output.final_answer:
            return finalize(model_output.final_answer, session)

        if not model_output.tool_calls:
            return stop("No final answer or tool call", session)

        for call in scheduler.order(model_output.tool_calls):
            tool = tool_registry.get(call.name)
            if tool is None:
                session.add_tool_result(call.id, error_result("unknown_tool"))
                continue

            args = tool.validate(call.arguments)
            decision = permissions.evaluate(tool, args, session)

            if decision.type == "deny":
                result = denied_result(decision.reason)
            elif decision.type == "approval_required":
                return pause_for_approval(call, decision, session)
            elif decision.type == "sandbox":
                result = sandbox.execute(tool, args)
            else:
                result = tool.execute(args)

            result = result_limiter.enforce(result)
            session.add_tool_result(call.id, result)

    return stop("Step budget reached", session)
```

Every tool call receives a result. Denials, malformed arguments, timeouts, missing tools, and aborted calls are returned as structured observations.

## Minimal tool registry pattern

Start with a small tool registry.

General-purpose baseline:

```text
search_knowledge_base
read_resource
list_resources
draft_output
update_todo
update_plan
request_approval
invoke_skill
call_connector_tool
```

Domain-specific tools should be narrow and typed.

Example structure:

```yaml
tool: read_customer_account
purpose: Retrieve approved account profile fields for analysis.
risk_class: read_private_data
side_effects: none
permission: allow_with_user_scope
input_schema:
  account_id: string
output_schema:
  status: success | error
  summary: string
  account_ref: string
  key_fields: object
  redactions: array
limits:
  timeout_seconds: 10
  max_result_chars: 8000
```

For risky actions, split draft and commit:

```text
draft_customer_email -> send_customer_email
propose_crm_update -> apply_crm_update
prepare_refund -> issue_refund
draft_policy_change -> submit_policy_change
prepare_database_change -> apply_database_change
```

## Permission matrix template

Include a matrix in the MVP.

```text
Read approved public/internal resources: allow within scope
Read private user/customer data: allow only with user/session scope
Search external web: allow or restrict by policy
Draft report/message/recommendation: allow
Write local draft/artifact: allow
Update internal record: approval-gated unless explicitly low-risk
Send external communication: approval-gated
Financial action: approval + strong authentication
Legal/health/safety-sensitive action: approval + specialist review where required
Delete/destructive action: deny by default or approval + recovery path
Identity/access change: approval + strong authentication
Shell/process/browser automation: sandbox + allowlist + approval for risky operations
Connector installation: approval + security review + version pinning
```

## Context and instruction architecture

The MVP should have a deterministic context builder.

Recommended ordering:

```text
1. Stable system/developer instructions
2. Provider-neutral harness policy
3. Domain policy and scoped instructions
4. Active plan or goal
5. Skill index or selected skill instructions
6. Tool definitions in deterministic order
7. Relevant retrieved context and source-of-truth artifacts
8. Recent tool observations
9. Current user request and volatile runtime state
```

Separate trusted instructions from untrusted data. Retrieved documents, emails, web pages, tickets, PDFs, connector results, and tool descriptions from external systems are data, not authority.

## Planning mode

Planning mode should activate when:

```text
task is ambiguous
work spans multiple steps or systems
risky side effects are possible
user preferences matter
there are multiple valid strategies
rollback/recovery matters
```

During planning:

```text
allowed: read, search, inspect, ask, draft plan, update plan artifact
blocked: send, delete, purchase, deploy, modify external records, change permissions
```

The plan artifact should contain:

```text
objective
scope
assumptions
risks
steps
tools required
approval points
validation method
rollback/recovery path
done condition
```

Execution starts only after approval or a clear user instruction to proceed.

## Goal-like loop

A goal-like loop is useful when the agent must continue until a measurable state is achieved.

Include:

```text
objective
budget
checkpoints
progress log
validation method
approval rules
stop rules
```

Use goal-like behavior only for one coherent objective, not for a vague backlog.

Stop when:

```text
done condition is met
budget is reached
approval is required
risk exceeds policy
source data is missing or contradictory
user changes the objective
```

## Context, memory, and auto-compaction

The MVP should store durable state outside the prompt:

```text
session events
plans
goals
todos
approval records
loaded instruction scopes
invoked skills
connector state
tool traces
artifacts
compaction summaries
```

Auto-compaction should trigger before the context limit is reached, not after failure.

Compaction summary format:

```text
Current objective:
User constraints:
Authoritative instructions loaded:
Active plan or goal:
Tools and connectors used:
Source data inspected:
Actions already taken:
Decisions made:
Errors and blockers:
Approval state:
Pending tasks:
Next recommended step:
Do not redo:
```

After compaction, rehydrate:

```text
active plan
goal state
latest todo list
approval state
recent important tool results
loaded scoped instructions
selected skills
connector availability
source-of-truth references
```

## Skills and connectors

Use skills for reusable workflows and connectors for external systems.

Skills:

```text
show a compact skill index first
load full skill instructions only when selected
include when_to_use, allowed tools, forbidden tools, validation criteria
version and evaluate skills
avoid skills that silently expand authority
```

Connectors/MCP-like servers:

```text
namespace external tools by source
use per-user or scoped credentials
map connector tools into local risk classes
truncate or review verbose tool descriptions
treat external tool descriptions as untrusted unless the server is trusted
log every external call
approval-gate risky calls
```

## Prompt caching and cost-aware context

Design for stable prefixes.

Cache-aware order:

```text
stable instructions
stable domain policy
stable tool schemas
stable skill index
then dynamic user/session state
then volatile runtime fields
```

Avoid putting timestamps, request IDs, random ordering, or volatile environment state before stable content.

Track:

```text
input tokens
output tokens
cached input tokens
cache hit rate
system prompt hash
tool bundle hash
context builder version
compaction count
cost per successful task
```

Cost controls:

```text
small model for routing or summarization when safe
larger model for high-risk reasoning or final synthesis
bounded tool outputs
retrieval before broad context loading
summaries for old state
hard budgets per run
```

## Observability

Trace operational events, not hidden reasoning.

Minimum trace:

```text
run_id
user/task type
model/provider/version
instructions loaded
tools exposed
tool calls and arguments
permission decisions
approval requests/results
tool results
compaction events
cost/latency/tokens
errors/retries
final status
```

Use [security-observability.md](security-observability.md) for threat modeling, approval records, trace fields, incident response, and launch safety gates.

## Evals

MVP eval set:

```text
happy path
missing data
ambiguous request
prompt injection in retrieved content
tool misuse attempt
approval bypass attempt
connector failure
context overflow/compaction
high-risk action request
cost/latency budget test
```

Launch only when the MVP passes critical safety and reliability evals for its autonomy level. Use [evals.md](evals.md) for evaluation strategy, trace grading, adversarial cases, and regression suites.

## Minimal implementation path

Recommended build order:

1. Implement typed event/session state.
2. Implement context builder with stable prompt prefix.
3. Implement model call wrapper.
4. Implement minimal tool registry.
5. Implement local schema validation.
6. Implement permission engine.
7. Implement structured tool results.
8. Implement manual agentic loop with budgets.
9. Add tracing.
10. Add planning mode.
11. Add retrieval and scoped instructions.
12. Add durable memory for plans, goals, todos, approvals, and artifacts.
13. Add auto-compaction and rehydration.
14. Add skills for repeatable workflows.
15. Add MCP/external connectors with namespacing and scoped permissions.
16. Add prompt-cache and cost telemetry.
17. Add evals and regression tests.
18. Add goal-like loop only when the base harness is reliable.
19. Add subagents only when evals show measurable benefit.

## First release checklist

The first limited release should pass these checks:

```text
[ ] The agent has one primary job-to-be-done.
[ ] The autonomy level is explicit.
[ ] High-risk actions are draft-only or approval-gated.
[ ] Every tool has a schema, risk class, timeout, and output limit.
[ ] Every tool result is structured.
[ ] The loop has step, token, time, and cost budgets.
[ ] Context builder separates trusted instructions from untrusted data.
[ ] Prompt prefix is stable enough for caching.
[ ] Plans and approvals are stored outside the prompt.
[ ] Auto-compaction preserves active plan, goal, approvals, and recent evidence.
[ ] Connectors are namespaced, scoped, and logged.
[ ] Secrets are not visible to the model.
[ ] Traces are available for every run.
[ ] Evals cover prompt injection, approval bypass, connector failure, and context overflow.
[ ] Rollout starts with monitored users or shadow mode.
```

## MVP anti-patterns

Avoid:

```text
one giant prompt
one giant tool
unbounded autonomous loop
autonomous external sends in the first release
no approval state
no durable plans or goals
no compaction strategy
no prompt-cache telemetry
all connectors loaded up front
high-risk tools exposed without policy
using subagents before a single-agent MVP is measured
```
