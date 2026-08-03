# Agent Approval Records — JSON schema, scope, expiration

## Принцип (2026-05-16)

«User said yes» — не approval. Approval это **structured record** с полями: action / risk / preview / scope / expiration / approver. Записывается в durable storage (file, DB), может быть verified at execution time, audit-trail-able.

Без structured approval records:
- Audit «кто одобрил» = guess
- Replay attack возможен (model claim'ит «approved earlier» когда нет)
- Scope ambiguous («one-time? recurring? all in this category?»)
- Expiration не enforced («approved 3 months ago» применяется сейчас)
- Self-approval не ловится («model approved its own action»)

Источник: skill `agents-best-practices` от Denis Sergeevitch (MIT) `references/security-evals-observability.md` "Approval records" + `references/tools-and-permissions.md`.

## Approval request format

Когда tool с risk_class требует approval — emit structured request:

```json
{
  "approval_id": "appr-<YYYY-MM-DDTHH:MM:SS>-<random6>",
  "approval_type": "external_send | financial_action | destructive | identity_access | plan_execution",
  "action": "send_email",
  "target": "customer@example.com",
  "risk": ["external_communication", "irreversible"],
  "preview_ref": "artifact://drafts/email_123.md",
  "expected_result": "Customer receives renewal reminder; email arrives within 30 sec",
  "rollback": "Cannot unsend; follow-up correction email possible within 1 hour",
  "scope": "single_send_only",
  "scope_details": {
    "max_recipients": 1,
    "max_amount_usd": null,
    "valid_until_utc": "2026-05-16T18:00:00Z"
  },
  "context": {
    "session_id": "uuid",
    "user_request_summary": "Send renewal reminder to customer X",
    "plan_id": "plan-2026-05-16-renewal-flow"
  },
  "requested_by": "agent_id"
}
```

## Approval result format

User response → durable record:

```json
{
  "approval_id": "appr-...",
  "status": "approved | rejected | modified | expired",
  "approved_by": "user_id (НЕ agent_id! см. anti-patterns)",
  "timestamp": "2026-05-16T15:32:11Z",
  "scope": "single_send_only",
  "scope_modifications": null,
  "expires_at": "2026-05-16T18:00:00Z",
  "comments": "Approved as drafted; verify subject line is correct",
  "auth_method": "session_cookie | mfa | biometric"
}
```

For **destructive / financial / identity_access** — `auth_method` MUST be `mfa` or stronger. Permission engine returns `require_stronger_auth` (см. agent-tool-design.md) если не выполнено.

## 4 правила approval scope

1. **Scope is exact action, not category.** «Send this email to X» ≠ «send any email to X». Approval ID привязан к конкретному `target` + `preview_ref`.

2. **Scope is single-use unless explicit.** Default = одно execution. Если нужно «approve N runs» — explicit `max_recipients: N` или `scope: "category_until_revoke"` с явной expiration.

3. **Expiration mandatory.** Default 1 hour для most tools, 5 minutes для financial / destructive. Approval старше expiration → automatic invalidate.

4. **Scope changes require new approval.** Если plan version bumps, target меняется, или amount растёт — текущий approval invalidates, новый request emitted.

## Re-approval triggers

Permission engine **обязан** request новое approval если:

- Plan version bump (см. agent-plan-artifact.md)
- Target changed (other recipient, other file path, other URL)
- Risk class escalated (unauthorized side effect discovered mid-execution)
- Time elapsed > expiration
- Approval was for «category» but new action is outside category boundary

## Audit log

Approval records **immutable**, append-only. Storage:

```
approvals/
  2026/
    05/
      16/
        appr-2026-05-16T15:32:11-abc123-request.json
        appr-2026-05-16T15:32:11-abc123-result.json
```

Audit query: «who approved external sends to customer X в last 30 days?» = grep + jq на этой иерархии. Без durable storage — нет answer.

## Anti-patterns

- ❌ **Self-approval**: model вызывает `request_approval(...)` и сам же returns `approved` — должен быть external user / system. Permission engine MUST verify approver != requester.
- ❌ **Verbal approval** в conversation вместо structured record — теряется после compaction, нет audit trail
- ❌ **Blanket approval** «делай что считаешь нужным» — не attached к scope, нельзя enforce
- ❌ **Stale approval reuse** — approval с expiration в прошлом всё ещё считается valid (без enforcement)
- ❌ **No preview_ref** — approval без artifact того что одобряется = blind sign-off
- ❌ **Approval logging в conversation only** — после context refresh теряется ground truth

## Real-world кейсы

- **Production DB migration**: approval scope = «one ALTER on table users», expiration 30 минут. Если agent потом делает второй ALTER — new approval needed, не reuse.
- **Mass email send**: scope = «send to segment X (12 recipients)», expiration 2 часа. Если agent добавляет recipient — new approval.
- **API key rotation**: scope = «rotate key for service Y», auth_method = mfa. Approval **invalid** если service Y not specified.
- **Bulk file deletion**: scope = «delete N files matching pattern», `max_files: N` в scope_details. Если matched count > N — abort, request new approval.

## Связь с другими правилами

- `agent-tool-design.md` — permission decision object types include `approval_required`; этот rule описывает что записывается когда approval_required triggers
- `agent-plan-artifact.md` — plan version bump = approval invalidation
- `agent-observability.md` — approval_requests / approval_results — обязательные trace fields
- `agent-evals.md` — eval категория 5 (approval_correctness) проверяет это правило
- `~/.claude/skills/agents-best-practices/references/security-evals-observability.md` — original source

## Source

- Denis Sergeevitch / agents-best-practices (MIT) `references/security-evals-observability.md` "Approval records"
- OpenAI Agents SDK guardrails-approvals docs
- Anthropic Managed Agents human-in-the-loop patterns
