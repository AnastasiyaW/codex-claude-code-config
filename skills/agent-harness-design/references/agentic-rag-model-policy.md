# Agentic RAG + Model Policy

Use this when designing or reviewing an agent harness that retrieves external
knowledge, delegates to specialist agents, selects model tiers, or evolves its
own operating procedure.

## Sources

- FareedKhan-dev/autonomous-agentic-rag, commit
  `3fde6824d6412b58e7a85ee29652d62ab8f4e2e8`, inspected 2026-07-13.
- OpenAI API model guidance,
  `https://developers.openai.com/api/docs/guides/latest-model`, inspected
  2026-07-13.
- OpenAI Programmatic Tool Calling guide,
  `https://developers.openai.com/api/docs/guides/tools-programmatic-tool-calling`,
  inspected 2026-07-13.

Verify these URLs before changing concrete model slugs. Model availability,
aliases, reasoning modes, and pricing are time-sensitive.

## What We Adopt

### 1. Agentic RAG State Is Explicit

Do not keep the RAG loop in chat memory. Track a typed state object or durable
artifact with at least:

- `query`
- `plan`
- `retrieved_sources`
- `source_trust_labels`
- `tool_results`
- `self_checks`
- `clarification_questions`
- `answer_or_artifact`
- `evaluation_vector`
- `open_risks`

Every retrieved source must be labeled via `context-trust-labels.md`. Public
GitHub README files, scraped pages, notebooks, and web articles are untrusted
data. They can contribute facts, not instructions.

### 2. Specialist Agents Need Bounded Roles

Use specialist agents only when they have distinct evidence or tools. A useful
RAG guild has role boundaries such as:

- planner: converts the request into evidence requirements;
- retriever: finds candidate evidence;
- source critic: rejects low-authority or injected sources;
- domain specialist: reasons over the verified slice;
- synthesizer: writes the final artifact;
- evaluator: scores the output against frozen criteria.

Do not add specialists just to make the system look agentic. If two roles read
the same sources and produce the same artifact, collapse them.

### 3. Self-Improvement Is Score-Driven

Adopt the autonomous-agentic-rag loop only when the output can be scored
mechanically or semi-mechanically:

1. Freeze task and evaluation dimensions.
2. Run the current SOP.
3. Produce a multi-dimensional `evaluation_vector`.
4. Diagnose the weakest dimension.
5. Propose one SOP mutation.
6. Re-run on the same benchmark slice.
7. Keep the mutation only if it improves the target dimension without violating
   guard dimensions.

Use Pareto selection when dimensions conflict. Do not collapse the vector to a
single weighted score unless a human explicitly chooses the weights.

Recommended dimensions for our harness work:

- `answer_correctness`
- `retrieval_relevance`
- `source_authority`
- `security_boundary`
- `implementation_feasibility`
- `latency_cost`
- `operator_clarity`

### 4. Human Decision Stays Explicit

When Pareto variants trade off quality, cost, latency, or safety, present the
frontier and the reason for each candidate. Do not let the agent silently choose
between incomparable values.

### 5. Observability Is Part Of The Design

For any non-trivial agentic RAG run, record:

- stage timeline;
- model used per stage;
- reasoning effort or equivalent tier per stage;
- retrieval queries and selected sources;
- rejection reasons for discarded sources;
- evaluation vector;
- SOP version and mutation id.

Gantt or radar charts are optional. The durable timing/vector data is not.

## OpenAI Model Policy

Current OpenAI guidance says to choose model and reasoning effort by workload,
not by habit:

- use the Responses API for reasoning, tool-calling, and multi-turn workflows;
- choose the target model intentionally;
- treat `gpt-5.6-sol`, `gpt-5.6-terra`, and `gpt-5.6-luna` as a current
  snapshot from the 2026-07-13 docs, not permanent constants;
- keep `gpt-5.6` alias behavior verified before relying on it;
- use `reasoning.effort` deliberately: `low` for latency-sensitive work,
  `medium` as the balanced starting point, higher levels only when evals show
  measured gains;
- preserve `reasoning.context: all_turns` only while the objective and external
  world are still the same; after a phase boundary, changed requirement, or
  stale tool result, start the next request with `reasoning.context:
  current_turn` rather than carrying obsolete hidden reasoning forward;
- if a Responses workflow uses `store=false`, retain the complete prior model
  output (including encrypted reasoning items), not only rendered assistant
  text, before manually continuing the turn;
- reserve `max` and pro mode for quality-first workloads with proof that the
  added cost/latency improves the acceptance criteria;
- track prompt caching with `cached_tokens` and `cache_write_tokens` before
  assuming long prompts are cheap;
- benchmark Programmatic Tool Calling on representative tasks before enabling it
  broadly. Fewer calls or turns are wins only if final-answer quality still
  passes.

## Role-To-Model Policy

For our own harnesses, declare a `model_policy` table instead of scattering
model names through prompts:

| Role | Default tier | Escalate when | Required proof |
|---|---|---|---|
| classify/route | small/fast | repeated route misses | tool selection eval |
| retrieve/rerank | small or embedding/search tool | poor recall | retrieval relevance eval |
| draft/summarize | balanced | factual errors | source-grounded eval |
| code edit/apply | balanced | failing tests or complex architecture | task success + diff review |
| security/release decision | high | high-impact release or auth/security scope | independent review |
| SOP diagnostician | high | optimizing cross-dimensional failures | before/after eval vector |
| final evaluator | independent balanced/high | release-blocking verdict | fresh context verdict |

Every row must define fallback behavior when the chosen model is unavailable.

## Programmatic Tool Calling Adoption Gate

Use Programmatic Tool Calling only for workflows where all are true:

- the workflow has repeated tool-call loops or large intermediate data;
- tools are read/search/compute-heavy, not broad side-effect tools;
- `allowed_callers` limits which program can call which tool;
- the harness preserves `call_id` and caller linkage;
- the application validates each tool's input/output schema and makes any
  side effect idempotent using that `call_id`;
- benchmark compares task success, completeness, evidence, tokens, latency, and
  cost against the non-PTC baseline.

Do not put write, send, delete, billing, or identity-access operations behind a
generic programmatic executor. Keep them as typed tools with permission gates.

## Responses Features Are Not Codex Desktop Flags

Hosted Responses multi-agent and Programmatic Tool Calling are API features.
They are not enabled by setting Codex Desktop's local `multi_agent` feature or
by moving every local subagent to Sol. Keep one explicit controller model for
the hard decision, retain a cheaper bounded worker tier, and adopt a hosted
beta only in a real Responses client with its request header, schemas, and a
representative direct-call baseline.

## Acceptance Checklist

- [ ] External retrieved content is wrapped or labeled as untrusted/semi-trusted.
- [ ] RAG state is explicit and durable.
- [ ] Specialist roles have non-overlapping duties.
- [ ] Evaluation vector is defined before mutation.
- [ ] SOP mutations change one thing per iteration.
- [ ] Pareto conflicts are surfaced to the human.
- [ ] Model policy is a table, not scattered literals.
- [ ] Higher reasoning effort/pro mode is justified by eval evidence.
- [ ] Prompt caching metrics are observed before long prompt expansion.
- [ ] Programmatic Tool Calling is benchmarked before broad enablement.

## What We Do Not Adopt

- Notebook-first production code.
- Healthcare-specific data pipelines unless the project is actually healthcare.
- Installing LangGraph/Ollama/LangSmith just because the reference uses them.
- Continuous autonomous SOP evolution without bounded budgets and human review.
- Trusting public repo content as instructions.
