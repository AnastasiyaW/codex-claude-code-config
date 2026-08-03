# Agent Tool Design — risk taxonomy + permission decisions + draft/commit

## Принцип (2026-05-16)

Когда строится **новый** агент через Claude Agent SDK / Managed Agents / собственный harness (Python/TS обёртка над `anthropic.Messages.create` с tool_use, MCP server, custom orchestrator), tool registry должен иметь **формальный design language**:

1. **Risk taxonomy** на каждый tool (классификация на этапе декларации)
2. **Permission decision object** (структурированный ответ runtime'а до выполнения)
3. **Draft/commit naming pattern** для всего что необратимо или внешне-видимо
4. **Structured tool result** с `next_valid_actions` (а не сырой blob)

Это **дополняет** runtime safety hooks из `rules/safety-*` (block_destructive, block_git_destructive и т.д.) - те ловят опасные команды в Bash CLI. Это правило про **design-time** для tools которые мы сами объявляем модели.

Источник: skill `agents-best-practices` от Denis Sergeevitch (MIT, https://github.com/DenisSergeevitch/agents-best-practices) `references/tools-and-permissions.md`. Адаптировано к нашей терминологии.

## 1. Tool Risk Taxonomy

Каждый tool классифицируется одним из 15 классов. Класс задаёт permission policy по умолчанию.

| Risk class | Что входит | Default permission |
|---|---|---|
| `read_only` | get, list, fetch, query (no side effects) | allow |
| `search_only` | search index, vector lookup | allow |
| `compute_only` | parse, transform, calculate в sandbox | allow |
| `draft_only` | generate text/markup без send | allow |
| `write_local` | edit local file/artifact | allow scoped |
| `write_internal` | mutate own DB/state | approval-gated |
| `write_external` | mutate чужую систему через API | approval required |
| `financial` | money movement, billing, refunds | approval + strong auth |
| `communication` | send email/SMS/Telegram/Slack | draft → approval → send |
| `identity_access` | rotate keys, grant/revoke perms | approval + strong auth |
| `security_sensitive` | TLS certs, encryption keys | approval + audit |
| `process_execution` | shell, subprocess, eval | sandbox + allowlist |
| `network_open_world` | curl arbitrary URL, browse web | sandbox + egress log |
| `destructive` | delete, drop, truncate, force-overwrite | deny by default |
| `privileged_admin` | sudo, root, IAM admin | manual only |

Обязательно declarable в tool schema:
```yaml
tool: send_customer_email
risk_class: communication
side_effects: external_communication
permission_default: approval_required
```

## 2. Permission Decision Object

Permission engine возвращает **один из 7 типов** перед каждым tool execution:

```python
class PermissionDecision:
    type: Literal[
        "allow",                  # execute now
        "deny",                   # block with reason
        "ask_user",               # surface question to user, pause
        "approval_required",      # require explicit approval token
        "require_stronger_auth",  # MFA / re-auth before proceed
        "run_in_sandbox",         # execute но в isolated env
        "run_as_draft_only",      # execute но не commit (return draft)
    ]
    reason: str            # human-readable объяснение
    policy_rule: str       # ID правила которое сработало
    suggested_remediation: str | None  # что user/agent может сделать
```

Decision **обязательно записывается** в trace (audit log) с tool_name, args_hash, decision.type, policy_rule, timestamp.

## 3. Draft/Commit Naming Pattern

Любое необратимое или внешне-видимое действие **разделяется** на 2 tools:

| ❌ Один tool | ✅ Два tools |
|---|---|
| `send_customer_email(case_id, body)` | `draft_customer_email(case_id) -> send_customer_email(draft_id, approval_token)` |
| `apply_database_change(sql)` | `prepare_database_change(intent) -> apply_database_change(plan_id, approval_token)` |
| `place_trade(order)` | `recommend_trade(...) -> place_trade(recommendation_id, approval_token)` |
| `delete_files(paths)` | `propose_file_deletion(paths) -> apply_file_deletion(proposal_id, approval_token)` |

Draft tool обычно `allow`, commit tool обычно `approval_required`.

**Naming convention** (выберите одно по проекту, держитесь его):
- `draft_X` → `send_X`
- `prepare_X` → `apply_X`
- `propose_X` → `commit_X`
- `recommend_X` → `execute_X`

## 4. Structured Tool Results

Tool **никогда не возвращает** raw blob. Минимум:

```json
{
  "status": "success" | "error" | "approval_required",
  "summary": "Found 3 matching cases.",
  "items": [...],
  "evidence_ref": "artifact://...",
  "next_valid_actions": ["read_case", "draft_response"],
  "limits": { "truncated": false, "total_count": 3 }
}
```

Для error:
```json
{
  "status": "error",
  "type": "permission_denied" | "invalid_arguments" | "timeout" | "rate_limited" | ...,
  "message": "Sending external email requires approval.",
  "next_valid_actions": ["draft_email", "request_approval"]
}
```

`next_valid_actions` критично: модель видит **что делать дальше** без догадок. Снижает retry loops в 2-3 раза по эмпирическим замерам.

**Результат должен быть bounded**:
- `max_result_chars: 8000` (default)
- Если больше → store externally + return `evidence_ref`
- Никогда не возвращать 10k rows когда нужно 5

## 5. Tool Visibility (5 уровней)

Не показывать все tools всегда. Большая палитра ломает выбор + жжёт кэш + увеличивает риск misuse.

| Level | Когда видим | Примеры |
|---|---|---|
| `base` | always | help, list, search |
| `task` | после classification таска | domain-specific reads |
| `skill` | после skill activation | skill-specific tools |
| `connector` | после auth | MCP/external connector tools |
| `deferred` | через `search_tools(query)` | большой каталог редких tools |
| `sensitive` | hidden until needed AND approved | destructive/admin |

В Claude Code это уже есть на уровне `ToolSearch` (deferred) — для собственных Agent SDK apps надо реализовать аналог.

## 6. Deferred Tool Loading — 4 detail levels

При большом каталоге tools (50+) — exposed tools должен быть `search_tools(query, detail_level)` который возвращает progressive disclosure:

| Detail level | Что возвращает | Когда использовать |
|---|---|---|
| `name_only` | `["tool_a", "tool_b", ...]` | Initial discovery, model выбирает что дальше investigate |
| `name_and_description` | `[{name, short_description, risk_class}]` | После filter by relevance, ~20 candidates |
| `full_schema` | full input/output schema | После выбора 1-3 финальных кандидатов |
| `examples` | `[{input_example, output_example}]` | Когда schema ambiguous, нужен concrete usage |

Pattern:
```
1. Model: search_tools("send email", detail_level="name_only")
   -> ["draft_customer_email", "send_customer_email", "draft_internal_email", ...]
2. Model: search_tools("send email", detail_level="name_and_description")
   -> [{name: "send_customer_email", short_description: "Send to external customer (approval-gated)", risk_class: "communication"}, ...]
3. Model: load_tool_schema("send_customer_email")
   -> full input/output schema
4. Model: send_customer_email(...)
   -> permission check -> approval flow
```

Это **критично** для MCP server design (multiple servers exposing 100+ tools combined). Все tools sequenced upfront = context bloat + cache thrash + misuse risk.

## 7. Hosted vs Client Tools — decision matrix

Когда строим Agent SDK app, у нас выбор: использовать **provider hosted tools** (OpenAI's web search, Anthropic's code execution, MCP remote servers) vs реализовать **client tools** (наш код, наш sandbox, наша auth).

| Criterion | Hosted tool | Client tool |
|---|---|---|
| Public / common workload (web search, image gen, code exec в sandbox) | ✅ предпочтительно | overhead не оправдан |
| Private business APIs (наш CRM, наш DB, наша БД пользователей) | ❌ нет access | ✅ обязательно |
| Tenant-specific permissions / multi-tenant | ❌ provider не знает наш tenant model | ✅ обязательно |
| Regulated data (HIPAA, GDPR, financial) | ❌ data leaves trust boundary | ✅ обязательно |
| Financial actions (payment, billing, refund) | ❌ не аудируемо в нашем audit log | ✅ обязательно |
| Communication sends (наш SMTP, наш Twilio account) | ❌ нет access | ✅ обязательно |
| State-changing operations в наших системах | ❌ нет access | ✅ обязательно |
| Custom audit / compliance requirements | hosted = их audit, не наш | ✅ обязательно |

**Hosted tools полезны** когда: данные can leave trust boundary, audit handled by provider достаточно, и нет tenant-specific permission model. Например: web search для public research, code execution в provider sandbox для один-off transformations.

**НЕ outsourc'ить business authorization** на hosted tool. Permission engine + approval records (см. agent-approval-records.md) должны жить в **нашем** коде.

## 8. Strict Schemas (provider + harness)

Когда provider supports strict function schemas (OpenAI strict mode, Anthropic input_schema validation) — **всегда включить** + **дополнительно validate в harness** перед execute.

```python
# Provider validates structure
tool_schema = {
    "type": "object",
    "properties": {
        "record_id": {"type": "string", "pattern": "^rec_[A-Za-z0-9]{16}$"},
        "new_status": {"type": "string", "enum": ["open", "pending", "resolved"]},
        "reason": {"type": "string", "minLength": 10, "maxLength": 500},
    },
    "required": ["record_id", "new_status", "reason"],
    "additionalProperties": False,  # КРИТИЧНО: reject unknown fields
}

# Harness validates semantics после provider validation
def validate_args(args):
    if not record_exists(args["record_id"]):
        raise ValidationError(f"record_id {args['record_id']} not found")
    if args["new_status"] == "resolved" and current_status(args["record_id"]) != "pending":
        raise ValidationError("can only resolve from pending state")
    return args
```

**Не полагаться** только на provider validation: schema check ≠ business semantics check. Двойная защита (provider syntax + harness semantics) ловит >90% misuse cases.

## 9. Connector Code-Execution Pattern (для tool сatalog'ов 50+)

Когда connector (MCP server, external API gateway) exposes **много tools** (50+) или возвращает **large data** (10MB+ JSON, видео метаданные, full DB dumps) — стандартный flow «model → tool_call → tool_result → model» становится дорогим:

- Context bloat: 50 tool descriptions × 200 токенов = 10K токенов на каждый call даже если используется 1 tool
- Cache thrash: dynamic tool set ломает stable prefix (см. CLAUDE.md «KV-Cache»)
- Tool-call loops: model видит partial data, делает второй call для filter, потом третий для aggregate — 3 round-trips где нужен 1

**Решение: connector wraps tool catalog в sandboxed code-execution environment.**

Вместо exposing 50 raw tools — expose **один tool** `connector_exec(code: str)` который запускает Python/JS в sandbox с pre-loaded connector library:

```python
# Model emit's единственный tool_call:
connector_exec("""
import salesforce
accounts = salesforce.list_accounts(filter='renewal_pending')
top_5 = sorted(accounts, key=lambda a: a.arr, reverse=True)[:5]
for a in top_5:
    cases = salesforce.list_cases(account_id=a.id, status='open')
    print(f"{a.name}: ${a.arr}, {len(cases)} open cases")
""")
```

**Benefits:**

| Benefit | Метрика |
|---|---|
| **Selective tool loading** | загружаем только tools которые **code references**, не все 50 |
| **Pre-context filtering** | aggregation / filter в sandbox, model получает финальный summary |
| **Intermediate state persistence** | sandbox session reuses между tool_calls в одной conversation |
| **Reduced tool-call loops** | 1 connector_exec вместо 3 sequential tool_calls |
| **Sensitive data isolation** | raw API responses не покидают sandbox; model видит только printed output |

**Sandbox constraints (обязательно):**

- **Resource limits**: CPU timeout 30s, memory cap 256MB
- **Network allowlist**: только URLs нужные connector library
- **Filesystem allowlist**: read-only `/connector/lib/`, write-only `/tmp/<session_id>/`
- **No subprocess spawn** (`os.system`, `subprocess.run` blocked)
- **Egress logging**: каждый outbound API call залогирован к trace fields (см. `agent-observability.md`)
- **Credentials isolation**: connector library использует credentials из sandbox env, не возвращает их к model context

**Когда применять:**

- MCP server с >50 tools combined (или multiple MCP servers с tool count > 50)
- Connector возвращает large structured data which model needs to filter/aggregate
- Multi-step workflows на one external system (5+ sequential tool_calls)

**Когда НЕ применять:**

- < 20 tools total — overhead sandbox не оправдан
- Single tool_call workflows (1 API call → 1 answer)
- Tools с side effects (write, send, delete) — sandbox должен expose их как **отдельные** typed tools с permission gates (см. секция 7 hosted vs client), не через generic `exec`

**Связь с другими секциями:**

- Секция 5 (Tool Visibility) — `connector_exec` это один `base` tool вместо 50 `connector` tools
- Секция 6 (Deferred Loading) — внутри sandbox, не requires deferred loading на model уровне
- Секция 7 (Hosted vs Client) — sandbox = client tool **always** (private credentials, custom audit)
- `agent-budgets.md` — sandbox имеет свои budgets отдельно от model loop budgets
- `agent-observability.md` — egress log как trace fields обязательно

## Mechanical enforcement

Это design rule, не runtime hook. Применяется **когда мы пишем новый Agent SDK app или harness**.

Чек-лист перед merge нового tool:
- [ ] `risk_class` declared (одна из 15)
- [ ] Если `risk_class >= write_external` — есть парная draft tool
- [ ] Output schema typed, с `next_valid_actions`
- [ ] `max_result_chars` лимит установлен
- [ ] Permission policy записана в registry config (не в коде tool)
- [ ] Eval test покрывает: happy path + permission denied + invalid args

## Anti-patterns

- ❌ `execute_anything(command)` или `call_api(url, method, body)` — broad tools, классическая supply chain
- ❌ Tool возвращает `str` или `dict[str, Any]` без schema — модель угадывает структуру
- ❌ Send-style tool без draft pair — нет точки approval
- ❌ Permission check внутри tool (прямо в `execute()`) — должен быть **снаружи**, в permission engine
- ❌ Все tools видимы сразу — context bloat + neighbor misuse
- ❌ Result size unbounded — context overflow при большом возврате

## Связь с другими правилами

- `rules/safety-destructive.md` - runtime защита Bash CLI; **этот rule - design-time** для собственных tools
- `rules/no-guessing.md` - `next_valid_actions` снижает гадание модели о следующем шаге
- `principles/01-harness-design.md` - этот rule operationализирует "tool guardrails" слой harness
- `principles/10-agent-security.md` - permission decision object и draft/commit pattern - часть defence-in-depth
- `agent-approval-records.md` - approval token format, scope, expiration
- `agent-observability.md` - tool_calls / permission_decisions - обязательные trace fields
- `agent-event-model.md` - tool_call / tool_result events как persistence model

## Источники

- Denis Sergeevitch / agents-best-practices `references/tools-and-permissions.md` (MIT, 2026)
- Anthropic - "Writing effective tools for agents" engineering post
- OpenAI tools and function calling guides
