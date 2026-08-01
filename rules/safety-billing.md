# Safety: Billing — Silent Subscription Overrides in Claude Code

## Правило (advice layer)

В Claude Code задокументированы **два класса silent billing override**, при которых сессия молча переключается с подписки (Pro/Max/Team/Enterprise) на pay-as-you-go API charges. Без warning. Без подтверждения. С возможным auto-recharge на API account.

Задокументированные кейсы: $152, $187, $200.98 overcharges на Max подписках. Anthropic в части случаев отказывает в refund, классифицируя как non-refundable technical error.

Это **первая линия обороны** до запуска `claude` в любом проекте.

## Риск 1 — HERMES.md в git history

[GitHub Issue #53262](https://github.com/anthropics/claude-code/issues/53262), статьи: [MindStudio](https://www.mindstudio.ai/blog/hermes-md-bug-claude-max-billing-subscription-pricing), [Consumer Rights Wiki](https://consumerrights.wiki/w/Anthropic_Claude_Code_HERMES.md_billing_flaw), [thekavin.com case study](https://thekavin.com/post/hermes-md-claude-code-billing-bug/).

**Что происходит**: Claude Code system prompt при инициализации читает git status / git log репозитория и подставляет в context. Если в commit messages, file names, или branch names встречается строка `hermes.md` (любой регистр, по подтверждённым кейсам) — срабатывает harness-detection regex который маркирует сессию как "third-party agentic tool" и переключает billing на extra-usage tier.

**Причина**: detection logic делает pattern-match на строку без verify что harness actually active. После Anthropic policy 2026-04-04 (Pro/Max не могут routing flat-rate plan через third-party agentic tools), проверка срабатывает на ложно-положительные.

**Mandatory check** при первой работе в новом git repo (перед запуском `claude`):

```bash
git log --all --pretty=format:'%s %an' 2>/dev/null | grep -i hermes
git log --all --name-only 2>/dev/null | grep -i hermes
git branch --all 2>/dev/null | grep -i hermes
```

**Если найдено — cleanup до запуска `claude`**:
- File name: `git filter-repo --path hermes.md --invert-paths`
- Commit message: `git filter-branch --msg-filter "sed 's/[Hh][Ee][Rr][Mm][Ee][Ss]\.md/legacy-config.md/g'" -- --all`
- Branch name: rename + delete remote stale branch

После filter — `git push --force-with-lease` (предварительно сделать backup branch).

## Риск 2 — `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` в env

[Issue #53728](https://github.com/anthropics/claude-code/issues/53728) (silent precedence), [#53638](https://github.com/anthropics/claude-code/issues/53638) (project .env override), [#39903](https://github.com/anthropics/claude-code/issues/39903) ($152 subagent case), [reddit r/ClaudeAI](https://www.reddit.com/r/ClaudeAI/comments/1tbaq2d/) ($187 case).

**Что происходит**: при запуске Claude Code, если в environment установлен `ANTHROPIC_API_KEY` (например из `.env` Supabase/Vercel/любого backend сервиса использующего Claude API напрямую), Claude Code **silently** предпочитает этот ключ над OAuth subscription credentials. Никакого warning не показывается. Если на API account включено auto-recharge — billing увеличивается без вопросов.

**Особенно опасно**:
- Sub-agent spawning через `Agent` tool — child processes наследуют env, могут использовать API key даже если main session на subscription
- `.env` файлы в project root, читаемые автоматически через direnv / python-dotenv / dotenv-cli
- Inherited environment variables (запустили `claude` из shell где раньше делали `source .env` для другого проекта)

**Mandatory check** перед каждым `claude` startup в новом shell:

```bash
# Bash / zsh
[ -n "$ANTHROPIC_API_KEY" ] && { echo "⚠️ LEAK"; unset ANTHROPIC_API_KEY; }
[ -n "$ANTHROPIC_AUTH_TOKEN" ] && { echo "⚠️ LEAK"; unset ANTHROPIC_AUTH_TOKEN; }
```

```powershell
# PowerShell (Windows)
if ($env:ANTHROPIC_API_KEY) { Write-Output "⚠️ LEAK"; $env:ANTHROPIC_API_KEY = $null }
if ($env:ANTHROPIC_AUTH_TOKEN) { Write-Output "⚠️ LEAK"; $env:ANTHROPIC_AUTH_TOKEN = $null }
```

**Pre-project check**: при первой работе с проектом — `grep -r ANTHROPIC_API_KEY .env* 2>/dev/null`. Если найдено для другого сервиса — переименовать в `${SERVICE}_ANTHROPIC_API_KEY` или загружать только когда нужно конкретному backend сервису.

## Риск 3 — Auto-charge на API account при исчерпании credits

Anthropic Console (console.anthropic.com) имеет default включаемый auto-recharge при исчерпании credits. Если ANTHROPIC_API_KEY подхватился (Риск 2), auto-recharge может triggered на полную сумму billing limit без warning.

**Mitigation**:
1. console.anthropic.com → Settings → Billing → **Disable auto-recharge**
2. Установить **hard spend limit** (Hard limit triggers stop, не recharge)
3. Email alerts на 50% / 75% / 90% threshold
4. Periodically (раз в неделю) — review usage на console

## Риск 4 — Dynamic Workflows как «машина по истреблению токенов» (2026-05-30)

[Claude Code dynamic workflows](https://code.claude.com/docs/en/workflows) (research preview
с 2026-05-28, вместе с Opus 4.8) спавнят до **1000 субагентов** на один прогон (16
concurrent). Это не silent billing override как Риск 1-2, а **легитимный, но кратный**
расход: оркестратор + N агентов жгут лимит/кредиты в N+ раз быстрее. Прикидка из практики:
если в один поток лимит уходит за ~4 часа, х7 агентов сделает это за ~35 минут. Кейсы с
$500+ чеками такие системы умножают, особенно на API-биллинге.

**Почему это в billing-safety**: на Pro workflows **выключены по дефолту** именно потому,
что «выжигают быстро» — Anthropic перестраховался. Включение в `/config` → Dynamic workflows.

**Дисциплина (наша, до запуска любого workflow):**
1. **Opt-in обязателен** — запускать workflow только когда user явно дал согласие (keyword
   `workflow`, ultracode on, или прямая просьба). Не запускать «инициативно».
2. **Оценить масштаб ДО** — сколько агентов реально заспавнит скрипт (fan-out по списку из
   N → N агентов на стадию). >10 агентов = обсудить расход с user.
3. **Демо/проверка флоу** — 2-4 агента, read-only.
4. **`budget`-guard в loop-флоу**: `while (budget.total && budget.remaining() > 50_000)`.
   Без гарда на `budget.total` → `remaining()` = Infinity → цикл до 1000-агентного потолка.
5. **`/model` перед большим прогоном** — рутинные стадии на меньшей модели (`model` в
   `agent()` или сессионная модель); каждый агент наследует модель сессии.
6. **Стоп без потерь** — `/workflows` → `x` останавливает прогон, завершённые агенты не
   теряются (resume-кэш в той же сессии).

**Recurring symptom**: лимит/кредиты уходят аномально быстро + в `/workflows` висит активный
прогон с десятками агентов → пауза (`p`) или стоп (`x`), пересмотреть масштаб скрипта.

Детали написания безопасных workflows — skill `workflow-orchestration` (секция BILLING).

## Hook (mechanical enforcement)

Идея PreToolUse hook на Bash (TBD, не реализован):

```python
# hooks/billing-safety-guard.py
# Если Bash command содержит:
#   - touch/edit/commit файла с именем "hermes.md" (any case)
#   - export ANTHROPIC_API_KEY=... или ANTHROPIC_AUTH_TOKEN=...
# → block + suggest rename / unset
```

Идея SessionStart hook:

```python
# hooks/check-billing-env.py
# Проверяет $ANTHROPIC_API_KEY на старте, если set — печать warning в context
# Можно расширить существующий validate_config.py если используется
```

Реализация — opportunity для contributors. Сейчас правило text-only с mandatory pre-session checks.

## Real-world кейсы

| Кейс | Trigger | Сумма | Outcome |
|---|---|---|---|
| Anonymous Max user | `hermes.md` в commit message | $200.98 | Refund после reproducer binary-search и clear report |
| Reddit r/ClaudeAI user | ANTHROPIC_API_KEY из project `.env` (Supabase) | $187 | Auto-recharge triggered, refund denied initially |
| Max plan subscriber (#39903) | Subagent processes наследовали env | $152 | Issue logged, awaiting fix |

## Что rule НЕ покрывает

- **Hardcoded API keys в коде** — rule scope = environment + git metadata, не source files
- **Third-party services которые сами биллят** через Claude API — это их отдельные подписки
- **Bedrock / Vertex AI deployment** — отдельный billing path, проверять provider-specific docs
- **Future Claude Code updates** — Anthropic может изменить detection logic, делать periodic re-check этого rule

## Recovery когда incident произошёл

1. **Immediately** unset `ANTHROPIC_API_KEY`, exit current `claude` session
2. **Check git history** на HERMES.md trigger — если есть, cleanup и force-push
3. **Anthropic Console** → check billing → identify the charges → request refund (отказывали в части случаев, но reproducer + GitHub issue link помогает)
4. **Email Anthropic support** с reproducer steps + screenshot of charge + reference to Issue #53262 / #53728
5. **Audit other projects** — running `claude` в каждом — та же проблема может повториться

## Источники

- [Issue #53262: HERMES.md billing trigger](https://github.com/anthropics/claude-code/issues/53262)
- [Issue #53728: Silent ANTHROPIC_API_KEY precedence](https://github.com/anthropics/claude-code/issues/53728)
- [Issue #53638: Desktop project API keys override](https://github.com/anthropics/claude-code/issues/53638)
- [Issue #39903: Max Plan subscribers billed through API key ($152)](https://github.com/anthropics/claude-code/issues/39903)
- [MindStudio: The Hermes.md Bug analysis](https://www.mindstudio.ai/blog/hermes-md-bug-claude-max-billing-subscription-pricing)
- [GIGAZINE: HERMES.md billing bug report](https://gigazine.net/gsc_news/en/20260430-hermes-claude-code/)
- [Consumer Rights Wiki: Anthropic Claude Code HERMES.md billing flaw](https://consumerrights.wiki/w/Anthropic_Claude_Code_HERMES.md_billing_flaw)
- [Anthropic Help Center: Manage API key environment variables](https://support.claude.com/en/articles/12304248-manage-api-key-environment-variables-in-claude-code)
- [reddit r/ClaudeAI: $187 charge case](https://www.reddit.com/r/ClaudeAI/comments/1tbaq2d/)

## Связанное

- [`rules/no-claude-attribution.md`](no-claude-attribution.md) — запрет `Co-Authored-By: Claude` в commits/PR (защищает от harness-detection regex'ов в будущих updates)
- [`secrets-as-data.md`](secrets-as-data.md) — политика секретов + защита `.env`
- [`safety-hooks.md`](safety-hooks.md) — api-key-leak detector + все safety-хуки
