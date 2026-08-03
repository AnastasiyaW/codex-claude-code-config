# Agent Event Model — typed events для harness state

## Принцип (2026-05-16, forward-looking)

Когда строится Agent SDK app или harness с persistence layer, state хранить как **типизированные events**, не как chat messages. Typed events улучшают replay / audit / compaction / evals / debugging — каждое из этих требует selective filter (что-то одного типа).

Без event model: state = массив сообщений. Невозможно эффективно ответить «какие tool calls сделал агент за этот run» — приходится парсить prose.

С event model: каждое state-changing операция = объект конкретного типа. `events.filter(e => e.type === "tool_call")` — за 1мс.

Источник: skill `agents-best-practices` от Denis Sergeevitch (MIT) `references/architecture.md` "Event model" section.

## 13 канонических event types

Минимальный stable set для Agent SDK persistence:

| Event type | Когда emit | Mandatory fields |
|---|---|---|
| `user_message` | User sends input | `id`, `ts`, `content`, `session_id` |
| `assistant_message` | Model emits text (final or intermediate) | `id`, `ts`, `content`, `model`, `tokens` |
| `tool_call` | Model requests tool execution | `id`, `ts`, `tool_name`, `args_hash`, `args_redacted`, `risk_class` |
| `tool_result` | Tool execution returns observation | `id`, `ts`, `tool_call_id`, `status`, `summary`, `evidence_ref` |
| `approval_request` | Permission engine returns `approval_required` | `id`, `ts`, `tool_call_id`, `approval_type`, `target`, `preview_ref` |
| `approval_result` | User responds to approval request | `id`, `ts`, `approval_request_id`, `status`, `approved_by`, `scope`, `expires_at` |
| `plan_update` | Plan artifact created / version bumped | `id`, `ts`, `plan_id`, `version`, `change_summary` |
| `goal_update` | Goal-loop progress / status change | `id`, `ts`, `goal_id`, `status`, `progress_pct`, `checkpoint` |
| `skill_invocation` | Skill activated for this session | `id`, `ts`, `skill_name`, `trigger_phrase` |
| `memory_load` | Memory file loaded into context | `id`, `ts`, `memory_path`, `scope` |
| `context_compaction` | Compactor produced summary | `id`, `ts`, `before_tokens`, `after_tokens`, `summary_ref` |
| `connector_call` | External connector (MCP, API) invoked | `id`, `ts`, `connector_name`, `method`, `result_status` |
| `error` | Caught exception / failed validation | `id`, `ts`, `severity`, `error_type`, `context`, `recovery_attempted` |
| `final_answer` | Run terminates with answer | `id`, `ts`, `content`, `evidence_refs`, `confidence` |

**Project-specific events** допустимы (e.g. `payment_initiated`, `email_drafted`) но **должны** наследовать общую схему: `id` + `ts` + `type` + payload.

## Storage layout

```
~/.agent-state/<app-name>/sessions/<session_id>/
  events.jsonl           # append-only event stream
  artifacts/             # bulky payloads referenced by events
    <evidence_ref>.{md,json,png,...}
  index.json             # latest state derived from events.jsonl
```

**Append-only events.jsonl** — каждая строка = один event JSON. Никогда не редактировать прошлые строки (immutable audit trail). Index файл re-derived из events stream при загрузке.

## Event format (минимальный)

```python
@dataclass
class Event:
    id: str                          # uuid-v4
    ts: str                          # ISO-8601 with timezone
    type: Literal[...]               # one of 13 types
    session_id: str                  # cross-event correlation
    payload: dict                    # type-specific fields
    parent_event_id: str | None      # для tool_result → tool_call link
```

Cross-references через `parent_event_id`:
- `tool_result.parent_event_id = tool_call.id`
- `approval_result.parent_event_id = approval_request.id`
- `final_answer.parent_event_id = last assistant_message.id` (optional)

## 5 операций которые становятся тривиальными с event model

| Операция | Without events | With events |
|---|---|---|
| **Replay run** | manually re-construct messages array | iterate events.jsonl in order |
| **Audit «who approved X»** | grep prose, error-prone | `events.filter(e => e.type === "approval_result")` |
| **Compaction** | summarize whole conversation | keep durable events (approvals, plans), summarize bulk message text |
| **Eval grading** | parse prose for tool_call presence | direct count of typed events |
| **Cost analysis** | sum tokens across all events of any type | sum from `assistant_message.tokens` only |

## Связь с другими правилами

- `agent-observability.md` — 16 trace fields per model call — это **summary** view; event model — **detailed** view (один model call = много events)
- `agent-plan-artifact.md` — `plan_update` event фиксирует version bump в audit log
- `agent-approval-records.md` — `approval_request` / `approval_result` events — это persistence для approval records формата
- `agent-evals.md` — eval categories могут проверяться напрямую на event stream
- `~/.claude/skills/agents-best-practices/references/architecture.md` — original source

## Когда применяется

| Use case | Event model? |
|---|---|
| Claude Code CLI session | Уже за нас (harness держит events) |
| Custom Agent SDK app с persistence | **Да, обязательно** |
| Stateless one-shot script | Не нужно, overhead |
| Multi-turn conversation app | **Да** (replay + compaction критичны) |
| Cron scheduled agent | **Да** + retain events для post-mortem |
| Subagent через Task tool | parent uses events, subagent may not need own |

## Anti-patterns

- ❌ Mutable events (редактирование прошлых записей) — audit trail сломан
- ❌ Event log = только chat messages (assistant/user) — теряешь tool_call / approval / plan events
- ❌ Bulky payload inline (10MB blob в events.jsonl) — storage/grep тяжёлые. Use `evidence_ref` к external file
- ❌ Event types без stable schema (free-form payloads) — broken eval queries, broken dashboards
- ❌ Synchronous write per event на slow disk — latency. Buffer + batch flush каждые N events или K секунд

## Real-world применение

При построении новых Agent SDK apps (cloud handlers, probe systems, processing pipelines):

1. **First session**: implement minimal event types (user/assistant/tool_call/tool_result/final_answer)
2. **After first incident** which needs audit: add approval_request/result + error events
3. **After context overflow**: add context_compaction events
4. **After multi-session work**: add plan_update + goal_update

Не реализовывать все 13 сразу — реализовывать **по triggers**.

## Source

- Denis Sergeevitch / agents-best-practices (MIT) `references/architecture.md` "Event model"
- Distributed systems event-sourcing patterns (Greg Young, "Event Sourcing")
- Anthropic conversation state best practices
