# Agent Streaming — buffering rules for incremental tool calls

## Принцип (2026-05-16, forward-looking)

Когда Agent SDK app использует **streaming responses** (`stream=True`), необходимо явное buffering чтобы избежать **partial tool execution** — модель ещё пишет JSON arguments, агент уже вызывает функцию.

Это правило **forward-looking**: сейчас наши Agent SDK apps синхронные (`stream=False`). При первой попытке стримить — следовать этому правилу с day 1, иначе типичный bug «выполнили tool с обрезанным argument string».

Источник: skill `agents-best-practices` от Denis Sergeevitch (MIT) `references/provider-api-patterns.md` "Streaming" section.

## 5 правил buffering для tool calls

| # | Правило | Anti-pattern |
|---|---|---|
| 1 | **Buffer полный tool_use block** до execute | Execute сразу как только видишь `tool_use_id` |
| 2 | **Validate complete JSON arguments** до execute | Parse partial → JSON decode error → retry чушь |
| 3 | **Deterministic ordering**: tools исполняются в **том порядке** в котором модель эмитнула | Race condition: tool B finishes first → результат attached к tool A |
| 4 | **Aborts = synthetic tool results** | Молча drop response; модель в следующем turn не понимает что произошло |
| 5 | **Do not stream partial sensitive data** к user до output guardrails | Secret leak через первые токены до output filter |

## Минимальный buffering pattern

```python
# Anthropic streaming example (концепция applies to OpenAI/compatible)
import anthropic

with client.messages.stream(...) as stream:
    pending_tool_use = None  # buffer для текущего tool_use block
    for event in stream:
        if event.type == "content_block_start" and event.content_block.type == "tool_use":
            pending_tool_use = {
                "id": event.content_block.id,
                "name": event.content_block.name,
                "input_buffer": "",  # accumulate partial JSON
            }
        elif event.type == "input_json_delta" and pending_tool_use:
            pending_tool_use["input_buffer"] += event.delta.partial_json
        elif event.type == "content_block_stop" and pending_tool_use:
            # COMPLETE — теперь validate + execute
            try:
                args = json.loads(pending_tool_use["input_buffer"])
            except json.JSONDecodeError as e:
                # synthetic error tool_result
                emit_tool_result(pending_tool_use["id"], {
                    "status": "error",
                    "type": "invalid_arguments",
                    "message": f"JSON parse failed: {e}",
                })
                pending_tool_use = None
                continue
            # validate against tool schema (см. agent-tool-design.md)
            validated = tool_schema_validate(pending_tool_use["name"], args)
            # permission check (см. agent-tool-design.md)
            decision = permission_engine.evaluate(...)
            if decision.type == "allow":
                result = tool_registry.execute(pending_tool_use["name"], validated)
                emit_tool_result(pending_tool_use["id"], result)
            # else: emit decision-based synthetic result
            pending_tool_use = None
```

## Abort handling

Streaming connections drop (network, rate limit, model error). Когда aborted **в середине** tool_use block:

1. **Не execute** partial tool — buffer не complete, JSON может быть невалидным
2. **Emit synthetic tool result** для каждого emitted-but-incomplete tool_use_id:
   ```json
   {
     "status": "error",
     "type": "stream_aborted",
     "message": "Stream terminated before tool arguments completed; tool not executed.",
     "next_valid_actions": ["retry_request"]
   }
   ```
3. **Не показывать** partial user-facing output если он был streaming'нут до abort — могут leak'нуться partial sensitive data; truncate с маркером «[response truncated due to stream error]»

## Output guardrails и streaming

Output guardrails (filter on sensitive output) должны работать **до** user-visible streaming, либо в **post-buffer** mode:

| Mode | Implementation | Tradeoff |
|---|---|---|
| **Post-buffer** | Stream → full buffer → guardrails → release к user | Higher latency; safest |
| **Token-level** | Каждый chunk проходит lightweight filter | Lower latency; risk of partial leak до filter catches pattern |
| **Hybrid** | Stream через token-level; full buffer для high-risk content classes | Moderate latency, моральный compromise |

Default рекомендация: **post-buffer** для всех output которые могут содержать secrets / PII / approved decisions. **Token-level** для cosmetic streaming (UX feel of typing) где content safe-by-construction.

## Связь с другими правилами

- `agent-tool-design.md` — validate_args + permission_engine вызываются ПОСЛЕ полного buffer (правило 2 выше)
- `agent-observability.md` — log streaming events (start, abort, complete) как trace fields
- `~/.claude/rules/safety-secrets.md` — output guardrail для secrets через post-buffer mode
- `~/.claude/skills/agents-best-practices/references/provider-api-patterns.md` — full source

## Когда правило не применяется

- `stream=False` (synchronous request) — нет partial state, не актуально
- Pure conversation без tool use — streaming text к user OK без buffering (но output guardrails всё ещё применимы)
- Anthropic Managed Agents — streaming handled provider-side, мы не управляем buffering вручную

## Anti-patterns

- ❌ Execute tool как только видишь `tool_use_id` — partial JSON, errors
- ❌ `assert json.loads(buffer)` без try/except — crash на legitimate stream abort
- ❌ Stream полный response к user без output guardrail — secret leak risk
- ❌ Multiple parallel tool calls in streaming без serializing finish events — race conditions в tool result ordering

## Source

- Denis Sergeevitch / agents-best-practices (MIT) `references/provider-api-patterns.md` "Streaming"
- Anthropic Streaming docs (content_block_start / input_json_delta / content_block_stop events)
- OpenAI Streaming function calling cookbook
