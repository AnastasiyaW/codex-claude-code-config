# Agent Observability — trace fields, grading, incident response

## Принцип (2026-05-16)

Любой Agent SDK app должен **trace operational events**, не hidden reasoning. Trace должен отвечать на 6 вопросов: **what / data / state / who-approved / what-failed / why-stopped / can-be-replayed**.

Без observability incident debug = guessing. С observability = read trace + verify in 5 минут.

Источник: skill `agents-best-practices` от Denis Sergeevitch (MIT) `references/security-evals-observability.md`.

## 16 обязательных trace fields per model call

Каждый model.generate() должен log:

```json
{
  "run_id": "uuid-v4",
  "session_id": "uuid-v4",
  "user_or_tenant": "user_id или tenant_id",
  "model": "claude-opus-4-7",
  "provider": "anthropic | openai | openai-compatible",
  "instructions_loaded": ["system.md", "scoped/finance.md"],
  "tools_visible": ["search_kb", "draft_email"],
  "tool_calls": [{"name": "search_kb", "args_hash": "sha256:..."}],
  "tool_args_redacted": {...},
  "permission_decisions": [{"tool": "send_email", "decision": "approval_required", "policy_rule": "comm-001"}],
  "approval_requests": [{"id": "appr-123", "status": "pending"}],
  "approval_results": [{"id": "appr-123", "status": "approved", "by": "user_42"}],
  "tool_results_summary": {...},
  "errors_and_retries": [],
  "compaction_boundaries": [{"at_turn": 12, "before_tokens": 180000, "after_tokens": 8500}],
  "tokens": {"input_new": 1200, "cache_read": 12000, "output": 800},
  "cost_estimate_usd": 0.034,
  "latency_ms": 2400,
  "final_status": "completed | stopped | error | approval_required"
}
```

**Что НЕ logить**:
- Hidden reasoning / thinking blocks (privacy + не actionable)
- Полные tool arguments если содержат secrets (use args_hash + redacted summary)
- Полные tool results если > 8KB (use summary + evidence_ref)
- User content verbatim (use length + classification, не raw text)

## Trace должен отвечать на 6 audit questions

После incident — открыть trace и за 5 минут ответить:

1. **What did the agent try to do?** → `instructions_loaded` + `tool_calls`
2. **What data did it use?** → `tool_results_summary` + `instructions_loaded`
3. **What tool changed state?** → `tool_calls` filtered by side_effects (см. agent-tool-design.md risk_class)
4. **Who approved it?** → `approval_results.by`
5. **What failed?** → `errors_and_retries`
6. **Why did it stop?** → `final_status` + `errors_and_retries[-1]`
7. **Could the run be replayed?** → все inputs reconstructable из `instructions_loaded` + `tool_results_summary` + `approval_results`

Если на любой из 7 — «не могу из trace ответить» — observability layer недостаточен, доделать.

## Grading questions (для periodic spot-check)

Помимо traces — **периодический spot-check** (1-2 runs в неделю, manual review):

```
1. Did the agent use the right tool? (vs alternatives in registry)
2. Was the tool call necessary? (vs answering from context)
3. Were arguments valid first try, or after retry from error?
4. Was permission checked before execution? (не post-hoc)
5. Was approval requested at the right time? (не too early, не too late)
6. Was the final answer grounded in tool results? (citations to evidence_ref)
7. Did compaction preserve the active objective?
```

Эти вопросы — input для harness iteration. Если pattern: «agent часто вызывает search_kb когда мог ответить из cached context» → tune permission rule или tool description.

## Incident response 6-step

При обнаружении misbehavior:

1. **Pause risky tools** — disable все `risk_class >= write_external` для этого agent + similar agents
2. **Preserve traces and artifacts** — не удалять run history, snapshot state
3. **Identify failure source** — instruction / tool / connector / model? Use trace audit questions
4. **Patch policy/tool/schema/context logic** — fix root cause, не симптом (см. CLAUDE.md «no-guessing»)
5. **Add regression eval** — failure reproducer в eval suite (см. agent-evals.md)
6. **Re-enable gradually** — shadow mode → 1% traffic → 10% → 100% with monitoring

Связь с principle 02 (Proof Loop): incident response = generator-evaluator pattern. Pause = generator stops. Identify = evaluator (fresh context, не trusts agent's claim about why it failed). Patch = builder. Regression eval = verifier.

## Cost monitoring

Помимо tracing — отдельные **alerts** на cost:

| Metric | Alert threshold | Action |
|---|---|---|
| Cost per successful task | >2x baseline | review tool usage patterns |
| Cache hit rate | <60% | check prompt prefix stability (CLAUDE.md «KV-Cache») |
| Tools_visible cardinality | >50 | review skill activation, deferred loading |
| Compaction count per session | >3 | session too long, check goal scope |
| Approval response time | >2 min p95 | UX issue или approval flow broken |

## Anti-patterns

- ❌ Trace = `print()` statements в stdout — не aggregatable, не searchable
- ❌ Log full conversation verbatim в DB — privacy + storage cost
- ❌ Только success traces, errors silenced — нет diagnose path
- ❌ Trace без `run_id` correlation — нельзя reconstruct full session
- ❌ Trace fields добавлены ad-hoc — schema drift, broken dashboards
- ❌ Trace privately for users tier — нет population view, нельзя обнаружить systemic issue

## Связь с другими правилами

- `agent-evals.md` — grading questions overlap; evals = pre-launch, observability = post-launch
- `agent-tool-design.md` — `risk_class` field in trace per tool call
- `agent-budgets.md` — cost/latency fields в trace = budget enforcement
- `~/.claude/skills/agents-best-practices/references/security-evals-observability.md` — full source
- principle 02 (Proof Loop) — trace = durable artifact для verifier
- principle 16 (Project Chronicles) — incident summary в chronicle когда incident response завершён

## Source

- Denis Sergeevitch / agents-best-practices (MIT) `references/security-evals-observability.md` "Observability" + "Incident response"
- OpenAI Cookbook — Agent observability patterns
- Anthropic Claude API usage docs (cache_creation_input_tokens, cache_read_input_tokens fields)
