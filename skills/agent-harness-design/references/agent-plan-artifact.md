# Agent Plan Artifact — стандартный формат + plan-validate-execute

## Принцип (2026-05-16)

Когда агент делает **non-trivial multi-step task** (особенно с side effects), `Plan` это не paragraph в conversation, а **durable artifact** с фиксированной структурой. Approval привязывается к **версии** plan'а, а не к одобрению на словах.

Это **mode** (planning mode vs execution mode), не просто инструкция. В planning mode mutation tools заблокированы. Execution начинается только после approval.

Источник: skill `agents-best-practices` от Denis Sergeevitch (MIT) `references/planning-and-goals.md`.

## Когда **обязательно** entering planning mode

| Триггер | Пример |
|---|---|
| > 1 valid strategy | refactor approach A vs B vs C |
| Touches multiple systems | DB migration + API change + client update |
| Hard-to-undo side effects | data migration, pricing change |
| User preferences materially affect outcome | UI redesign, copy tone |
| Regulated / high-stakes domain | legal, financial, healthcare |
| Tool execution expensive | $10+ per run, multi-hour GPU |
| Validation criteria unclear | "improve performance" |
| Likely > 1 context window | large refactor, multi-file feature |

**Не входить** в planning mode для:
- Simple read-only questions
- Obvious single-step actions
- Bug fixes с явным reproducer
- Routine maintenance в известных файлах

## Что разрешено / запрещено в planning mode

```
ALLOWED:                        BLOCKED:
- read                          - writes (file mutation)
- search                        - sends (email, message, API POST)
- inspect (logs, configs)       - deletes
- ask clarifying questions      - payments
- compare approaches            - permission changes
- draft plan artifact           - deployments
- estimate risks/validation     - external commitments
- update plan artifact          - other irreversible side effects
```

Permission engine (см. `agent-tool-design.md`) должен **сам** enforce'ить — не «model promised not to», а runtime check.

## Plan artifact — обязательный формат

Хранить в **файле** (не в conversation). Path convention: `<project>/plans/<plan-id>-<slug>.md`.

```markdown
# Plan: <objective summary>

## Plan ID
plan-<YYYY-MM-DD>-<short-slug>

## Version
1 (incremented when plan changes; approval invalidates if version changes)

## Objective
<1-2 sentences: what success looks like>

## Scope
**Included:**
- <bullet 1>
- <bullet 2>

**Excluded:**
- <explicit non-goals>

## Assumptions
- <what we're betting on; verify before execute>

## Risks
- <risk 1>: <mitigation>
- <risk 2>: <mitigation>

## Steps
1. <step 1 with tool name>
2. <step 2 with tool name>
...

## Tools required
- `tool_name_1` (risk_class: ...)
- `tool_name_2` (risk_class: ...)

## Approval points
- <after step N: requires approval before continuing>
- <after step M: requires approval>

## Validation
- <how we verify objective achieved>
- <durable artifact: test result, log entry, UI screenshot, etc.>

## Rollback or recovery
- <if step N fails: undo path>
- <if all steps complete but validation fails: revert path>

## Done condition
- <measurable: "all 3 tests pass and prod /health returns 200">
```

Все 10 fields обязательны (можно «N/A» с обоснованием, не пустые).

## Plan approval format

Approval запрашивается через **structured request**, не «можно?»:

```json
{
  "approval_type": "plan_execution",
  "plan_id": "plan-2026-05-16-db-migration",
  "plan_version": 1,
  "summary": "Migrate users table from MyISAM to InnoDB on prod",
  "exact_actions_requiring_approval": [
    "Step 3: ALTER TABLE users ENGINE=InnoDB",
    "Step 5: drop legacy temp table"
  ],
  "risk_class": ["destructive", "write_internal"],
  "expected_outcome": "Users table is InnoDB with same data; reads continue uninterrupted",
  "rollback_path": "Snapshot taken before step 3; restore from snapshot if step 3 fails",
  "scope": "this_plan_version_only",
  "expiration": "2026-05-16T18:00:00Z"
}
```

User approves → approval token attached to plan_id + version. Если plan **changes** (version bump) — approval invalidates, новый approval нужен.

## Plan-Validate-Execute pattern

Для fragile или high-risk operations:

```
1. Gather source-of-truth (read deployed state, не assume)
2. Create structured plan (см. format above)
3. Validate plan against source data:
   - Все mentioned files exist?
   - Все expected configurations match?
   - Tools required actually available и authorized?
4. Request approval (если risk class требует)
5. Execute approved plan, ONE step at a time
6. After EACH step: validate result, не continue if validation fails
7. Produce final audit summary (link to plan, link to approval, list of artifacts)
```

Применяется к: data migrations, customer communications, financial adjustments, legal document changes, operational runbooks, deployment процедуры.

## Связь с другими правилами

- `agent-tool-design.md` — permission engine enforces planning mode tool restrictions
- `agent-approval-records.md` — approval JSON schema (parallel rule)
- `agent-budgets.md` — plan execution budget; planning mode само имеет budget на гадание
- `~/.claude/rules/no-guessing.md` — Validate шаг 3 = source-of-truth verification
- `~/.claude/skills/agents-best-practices/references/planning-and-goals.md` — full source
- principle 02 (Proof Loop) — execute step → validate → durable artifact = same pattern

## Anti-patterns

- ❌ «Plan» в conversation message vs durable file — теряется после compaction
- ❌ Approval verbal («ok делай») без attached plan_id — нет audit trail, нельзя revert «не я одобрял»
- ❌ Plan changes mid-execution без version bump + re-approval — scope creep, approval bypass
- ❌ Skip Validation step (3) — execute против stale state
- ❌ Continue after step failed validation — compounding error, harder to revert
- ❌ Planning mode in name only (model «promised not to write») — not enforced; permission engine должен block

## Real-world применение (когда правило сработает)

- Production DB migration: planning mode → DBA review → approval → step-by-step execute с validation после каждого
- Mass email campaign: draft template → segment audience → approval → batch send с pause после first 100
- Refactor 10+ files: plan list of files + sequence + rollback (git revert если CI fails)
- LoRA training run: hyperparameter plan + cost estimate → approval → trigger train с budget hit alerts

## Source

- Denis Sergeevitch / agents-best-practices (MIT) `references/planning-and-goals.md`
- Internal practice: long-run-harness.md First Release Checklist предполагает что project имеет такой workflow для high-risk changes
