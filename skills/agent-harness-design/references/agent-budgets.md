# Agent Budgets - 10 budget types, all must be declared

## Принцип (2026-05-16)

Любой agent loop (custom Agent SDK app, custom orchestrator, autoresearch loop, harness) **обязан** объявить **все 10 budget types** перед запуском. Безбюджетный loop = financial / latency / context risk.

«Я добавлю budgets потом» - anti-pattern. Агент работающий **без** explicit limits эмпирически уходит в:

- Long tool-call chains которые жгут $20-200/сессия
- Context window overflow с silent truncation
- Бесконечный retry loop при transient API error
- "Helpful" дополнительная работа сверх scope

Источник: skill `agents-best-practices` от Denis Sergeevitch (MIT, https://github.com/DenisSergeevitch/agents-best-practices) `references/agentic-loop.md` секция "Step budgets".

## 10 обязательных budgets

| Budget | Default (отправная точка) | Rationale |
|---|---|---|
| `max_model_turns` | 30 | После 30 turns без resolution - задача не sized; стоп -> user |
| `max_tool_calls` | 100 | 100 tool calls = $5-15 на средней модели; threshold для re-plan |
| `max_parallel_tool_calls` | 5 | Avoid rate limit, легче debug serialized failures |
| `max_wall_time_seconds` | 1800 (30 min) | После 30 мин wall-clock - re-evaluate, может user забыл |
| `max_input_tokens` | 800_000 | Для 1M ctx моделей - оставить headroom для output |
| `max_output_tokens` | 50_000 | Если нужно больше - это compaction handoff, не один output |
| `max_total_cost` | 10.00 USD | Default для standalone runs; production может быть выше с monitoring |
| `max_tool_result_chars` | 10_000 per tool | Больше -> external storage + reference (см. agent-tool-design.md) |
| `max_retries_per_model_call` | 3 | Transient API errors only; не для validation/permission failures |
| `max_retries_per_tool_call` | 2 | Idempotent tools only; non-idempotent - 0 retry |

Все 10 **обязаны быть** в config объекте. Отсутствие = treated as `0` (deny) или unbounded (deny) - depending на budget type.

## Stop format когда budget hit

```json
{
  "status": "stopped",
  "reason": "step_limit_reached" | "cost_budget_exceeded" | "wall_time_exceeded" | ...,
  "budget_hit": "max_tool_calls",
  "value_at_stop": 100,
  "limit": 100,
  "completed": false,
  "partial_artifacts_ref": "artifact://...",
  "next_safe_action": "Ask user whether to continue with budget X."
}
```

User видит что закончилось, может explicitly допустить +50% или прекратить.

## Когда применять

| Use case | Применять |
|---|---|
| Claude Code CLI session | Не нужно (harness уже за нас) |
| Custom Agent SDK Python script | **Да, обязательно** |
| autoresearch / iterative loop | **Да** + `max_iterations` |
| Subagent через Task tool | Уже есть internal limits, но при сложной задаче - добавить explicit user-facing budget в prompt |
| Serverless handler (RunPod / Modal / Lambda) | Cloud sets execution timeout, но **в** handler стоит trace `max_internal_iterations` |
| Probe / health-check tool | Каждый probe должен иметь `max_wall_time` (default: 5 sec) |
| Cron scheduled agents | **Да** + alert при hit, иначе silent waste |

## Anti-patterns

- "Default unbounded, set limit когда понадобится" - production hit раньше понимания
- Один shared budget для всех agents в team - нет ownership когда hit
- Hit budget -> silent retry без user notification - fabrication: agent заявит "done" с partial work
- `max_retries_per_tool_call > 3` для non-idempotent tool - multi-charge (payment), multi-send (email)
- `max_input_tokens` рядом с context limit - нет места для error response, OOM
- Все 10 = max - это unbounded, не "safe"

## Real-world failure modes этим правилом

**Overnight autoresearch без `max_iterations`**: один эксперимент в overnight session ушёл в 200+ итераций до утреннего noticing. Lost money + GPU hours. Fix: всегда `max_iterations: 50` на новый autoresearch loop.

**Cloud Serverless handler с unbounded poll loop**: handler.py имеет `poll_history()` цикл который без `max_polls` может крутить весь interval вызова. Cloud-уровень execution timeout срабатывает, но billable. Fix: внутри handler.py - explicit `max_internal_iterations`.

**Cron scheduled task**: stuck task ест tokens весь interval до next fire. Если interval = 1 hour и agent ушёл в loop - $50-100 за день. Fix: budget + alert при hit.

## Связь с другими правилами

- `agent-tool-design.md` - `max_tool_result_chars` enforce'ит structured result + external storage pattern
- `rules/no-pre-existing-evasion.md` - budget hit ≠ permission "stop with TODO"; нужен explicit user check
- `principles/01-harness-design.md` - budgets - часть harness boundary, не optional
- `principles/03-autoresearch.md` - iterative loops особенно требуют budget enforcement

## Mechanical enforcement (recommended pattern)

Helper Python module:

```python
@dataclass
class AgentBudgets:
    max_model_turns: int = 30
    max_tool_calls: int = 100
    max_parallel_tool_calls: int = 5
    max_wall_time_seconds: int = 1800
    max_input_tokens: int = 800_000
    max_output_tokens: int = 50_000
    max_total_cost: float = 10.00
    max_tool_result_chars: int = 10_000
    max_retries_per_model_call: int = 3
    max_retries_per_tool_call: int = 2

    def check(self, current_state: dict) -> BudgetCheck:
        # Returns first hit budget или OK
        ...
```

Все Agent SDK apps в проекте должны импортировать этот module чтобы default budgets были uniform.

## Источники

- Denis Sergeevitch / agents-best-practices `references/agentic-loop.md` (MIT)
- Anthropic API rate limit docs
- OpenAI Agents SDK budget patterns
