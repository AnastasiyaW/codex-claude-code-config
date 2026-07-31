---
paths:
  - "**/feature_list.json"
  - "**/feature_list.schema.json"
  - "**/init.sh"
  - "**/PROBLEMS.md"
  - "**/BACKLOG.md"
---

﻿# Long-Run Project Harness — feature_list.json + init.sh convention

## Принцип (2026-05-12)

Любой проект помеченный `[LONG-RUN]` в `MEMORY.md` получает два канонических артефакта поверх существующих (CLAUDE.md, PROBLEMS.md, handoffs, chronicles):

- **`init.sh`** в корне проекта — единый entry point "проект здоров?"
- **`feature_list.json`** в корне проекта — machine-readable state фич с verification commands

Источник: [Learn Harness Engineering](https://walkinglabs.github.io/learn-harness-engineering/), MIT-лицензированные шаблоны взяты из `walkinglabs/learn-harness-engineering/skills/harness-creator/templates/`.

## Зачем это, если у нас уже есть PROBLEMS.md + handoffs

| Артефакт | Закрывает вопрос |
|---|---|
| **CLAUDE.md** | Как работать с проектом (правила) |
| **PROBLEMS.md** | Что **сломано** прямо сейчас (incident log) |
| **handoffs/** | Что делать **дальше** в этой ветке работы (тактика) |
| **chronicles/** | Как мы **сюда пришли** (стратегия, история решений) |
| **feature_list.json** ← новое | Какие фичи проекта **сделаны** и как это **программно** проверить |
| **init.sh** ← новое | Проект **работоспособен** прямо сейчас? (binary check) |

Без `feature_list.json` информация о состоянии фич размазана по всем handoff'ам в свободной форме. Через 5 сессий невозможно ответить "сколько фич готово, какая прямо сейчас в работе". Без `init.sh` каждая новая сессия 10-15 минут разбирается "как это запустить" из README + handoff.

## init.sh — стандарт

**Один файл в корне проекта**. Запускается **не автоматически** (мы не блокируем session start), но является **единственным каноническим путём** проверить здоровье проекта. Если `init.sh` зелёный — baseline ОК, можно добавлять scope. Если красный — **fix baseline first**, не начинай новые фичи.

Структура:
```bash
#!/bin/bash
set -e

echo "=== Initialization ==="

# 1. Зависимости (язык-specific)
# Python:  uv pip install -r requirements.txt  ИЛИ  pip install -e .
# Node:    npm install  ИЛИ  bun install
# Rust:    cargo build --release

# 2. Static checks (L1 из 3-layer gate)
# Python:  ruff check . && mypy src/
# Node:    npm run check  ИЛИ  tsc --noEmit
# Rust:    cargo clippy -- -D warnings

# 3. Tests (L2 из 3-layer gate)
# Python:  pytest tests/ -x --tb=short
# Node:    npm test
# Rust:    cargo test

# 4. Build artifact ready (когда применимо)
# Node:    npm run build
# Rust:    cargo build --release
# Python:  обычно skip, но если есть entry point - import smoke test

echo "=== Verification Complete ==="
echo ""
echo "Next steps:"
echo "1. Read feature_list.json to see current feature state"
echo "2. Pick ONE 'not-started' feature with no unresolved dependencies"
echo "3. Update status to 'in-progress' before starting work"
echo "4. Re-run ./init.sh before claiming 'done'"
```

**Не клади в init.sh:**
- Long-running training / inference (это отдельные скрипты)
- Network calls на платные API (init должен быть бесплатным)
- Deploy steps (init = "локально работает", deploy = отдельный workflow)
- Команды требующие user input (init должен пробегать без интеракции)

**Целевая метрика**: новая Claude-сессия добегает от "git clone" до "./init.sh зелёный" за **3 минуты** vs ~15 минут без init.sh. Если init.sh идёт дольше 3 минут — разбить на `./init.sh` (быстрая часть) + `./init-full.sh` (полная).

## feature_list.json — стандарт

**JSON Schema**: см. публичный репозиторий [claude-code-config/templates/long-run-project/feature_list.schema.json](https://github.com/AnastasiyaW/claude-code-config/blob/main/templates/long-run-project/feature_list.schema.json).

Минимальная структура:
```json
{
  "features": [
    {
      "id": "feat-001",
      "name": "Document Import",
      "description": "Allow users to import PDF and TXT documents from local filesystem",
      "dependencies": [],
      "status": "done",
      "evidence": "L1: tsc clean (commit a3f2c1); L2: pytest tests/test_import.py::test_pdf_load passed; L3: manual upload of sample.pdf via UI rendered preview correctly (2026-05-10)"
    }
  ]
}
```

**4 состояния** (`status`):
- `not-started` — фича определена, не начата
- `in-progress` — активная работа сейчас (WIP=1: только **одна** фича в этом статусе)
- `blocked` — невозможно продолжить, причина в `evidence`
- `done` — все 3 layer'а прошли с durable artifacts в `evidence`

**Правила перехода:**
- `not-started` → `in-progress`: после check'а что нет другой `in-progress` фичи и все `dependencies` уже `done`
- `in-progress` → `done`: только когда `evidence` заполнен ссылками на L1+L2+L3 артефакты (см. 3-Layer Validation Gate в CLAUDE.md)
- `in-progress` → `blocked`: указать в `evidence` что именно блокирует
- `done` → откат запрещён. Если фича перестала работать — это **новая** фича `feat-NNN` "fix regression in feat-MMM"

## Где хранить и как поддерживать

- `feature_list.json` в **корне проекта** (рядом с CLAUDE.md, PROBLEMS.md)
- `init.sh` в **корне проекта** с исполняемым битом
- При создании нового `[LONG-RUN]` проекта — взять шаблоны из `templates/long-run-project/` (или с GitHub: `gh api repos/AnastasiyaW/claude-code-config/contents/templates/long-run-project/feature_list.template.json`)
- При закрытии каждой фичи (`status: "done"`) — coordinated update в session handoff: "feat-NNN done"
- Сторонне: `feature_list.json` НЕ заменяет PROBLEMS.md. PROBLEMS = баги/инциденты, features = фичи/scope

## Не применять для

- Краткосрочные проекты (< 5 сессий работы) — оверхед не оправдан
- Проекты где меньше 5 фич — список из 3 пунктов хорошо живёт в handoff
- Research / exploratory work — scope меняется, нет смысла фиксировать как features
- Утилиты-однострочники (`scripts/`)

## First Release Checklist — gate перед `[LONG-RUN]` mark

Источник (адаптировано): Denis Sergeevitch / agents-best-practices (MIT) `references/mvp-agent-blueprint.md` "First release checklist" + наш 3-Layer Validation Gate (см. `principles/01-harness-design.md`).

Перед тем как пометить проект `[LONG-RUN]`, **все 15 пунктов** должны быть зелёные. Это **не** то же самое что `init.sh` пробежал — `init.sh` проверяет L1+L2. Этот checklist шире, включает governance артефакты.

### Code-level (зелёный = mechanical artifact existing)

- [ ] **Один primary job-to-be-done** объявлен в первой строке CLAUDE.md
- [ ] **`init.sh` exists и exits 0** локально на чистой машине за <3 мин
- [ ] **`feature_list.json` exists** с min 5 фичами (включая 1+ `done` с заполненным `evidence`)
- [ ] **WIP=1 проверка** — ровно 0 или 1 фича `in-progress` в `feature_list.json`
- [ ] **`PROBLEMS.md` exists** (даже пустой) — incident log готов
- [ ] **`.gitignore` корректный** — `node_modules/`, `dist/`, `.env*`, `__pycache__/`, weights, datasets

### Process-level

- [ ] **Autonomy level explicit** — answer-only / draft-only / approval-gated / autonomous-within-policy. Документировано в CLAUDE.md
- [ ] **High-risk actions draft-only OR approval-gated** — список risk-classes в CLAUDE.md (см. skill `agent-harness-design`)
- [ ] **Step/cost/time budgets declared** для всех agents которые проект запускает (см. skill `agent-harness-design`)
- [ ] **Trust labels applied** для external content (см. skill `agent-harness-design`)

### Knowledge-level

- [ ] **CLAUDE.md ≤ 200 строк** — краткий map, не encyclopedia. Детали в `.claude/rules/` или `docs/`
- [ ] **Session-handoff workflow** установлен — handoff обязателен между сессиями
- [ ] **Project-level `.claude/rules/` initialized** — min: PROBLEMS-format, handoff-format
- [ ] **Validation signals declared** — что значит "feature works": какой test/probe/UI check

### Safety-level

- [ ] **Secrets не в git, не в CLAUDE.md, не в скриптах** — pre-push scan настроен (см. `secrets-as-data.md`)

Если checklist не пройден полностью — проект остаётся в обычном режиме (не помечается `[LONG-RUN]`). Можно переходить итеративно — закрыл item, отметил, повторил.

**Anti-pattern:** "помечу `[LONG-RUN]` сейчас, доделаю checklist завтра". Метка триггерит специальные правила (long-run-problems-log, project-chronicles, handoff-mandatory). Без gate они работают на пустом фундаменте — это deceptive state, не safety net.

## Связь с другими правилами

- **`no-pre-existing-evasion.md`** — добавляет WIP=1 + VCR Blocking как property над `feature_list.json`
- **`CLAUDE.md` 3-Layer Validation Gate** — определяет какие artifacts должны быть в `evidence` поле для `status: "done"`
- **project-level `.claude/rules/long-run-problems-log.md`** — PROBLEMS.md и feature_list.json параллельные, не конфликтуют
- **project-level `.claude/rules/session-handoff.md`** — handoff включает ссылку на текущую in-progress фичу
- **project-level `.claude/rules/project-chronicles.md`** — chronicle entry при закрытии каждой фичи

## Mechanical enforcement (active)

Два хука (оба с `--self-test`, fail-open/opt-in — см. `no-silent-validators`):

1. **`long-run-detector.py`** (SessionStart, informational) — **авто-ДЕТЕКТ** долгоиграющего
   проекта. Сигналы по `cwd`: ≥3 датированных handoff'а в `.claude/handoffs/<slug>/` (strong),
   ≥40 git-коммитов, ≥200 tracked-файлов, наличие `PROBLEMS.md`. Срабатывает при strong ИЛИ ≥2
   medium и **нуджит**: «похоже на long-run → прогнать First Release Checklist + пометить
   [LONG-RUN]». Молчит, если: проект уже принял харнесс (`feature_list.json`/`init.sh` есть),
   это агрегирующий хаб (>5 проектов-подпапок в handoffs), не-проект (нет `.git` и `.claude`),
   или уже нуджено <14 дней назад (стамп `.claude/.longrun-nudged`).
   - 🔴 **Детект — автоматический; сама метка [LONG-RUN] — человеческое решение по дизайну.**
     Хук НЕ пишет метку сам: преждевременная пометка = анти-паттерн (declared victory early).
     Авто = обнаружение «пора проверить»; гейт (15-пунктовый чеклист) остаётся за человеком.

2. **`feature-list-validator.py`** (Stop) — **энфорсит дисциплину** `feature_list.json` уже
   принятого long-run проекта: WIP=1 (не больше одной `in-progress`) + `done` несёт непустой
   `evidence`. Невалидный `status` отвергается. Opt-in: молчит, если `feature_list.json` нет.
   Bypass: `CLAUDE_SKIP_FEATURE_CHECK=1` / `.claude/.skip-feature-check`.

Оба прописаны в `~/.claude/settings.json` (SessionStart / Stop). Дополнительно дисциплину
держат `problems-md-validator.py` (Stop) и `activity-journal-guard.py` (per-resource журнал,
см. `activity-journal-and-state-registry.md`).

## Bootstrap существующего [LONG-RUN] проекта

Когда проект уже идёт давно и нет `feature_list.json` / `init.sh`:

1. **Inventory**: пройтись по последним 5-10 handoff'ам + chronicle, выписать что было сделано как list
2. **Дедуплицировать + сгруппировать** в фичи (5-15 фич обычно)
3. **Все существующие** → `status: "done"` с evidence-стрелкой на commit'ы / прошлый handoff
4. **Текущая работа** → `status: "in-progress"` (одна!)
5. **Запланированное** → `status: "not-started"` с dependencies
6. **`init.sh`**: написать минимальный (deps + tests) сразу же — если красный, починить **до** добавления новых фич
7. Commit оба файла одним changeset'ом с message: "harness: bootstrap feature_list + init.sh"

## Anti-patterns

- ❌ `feature_list.json` с 50+ записями — это уже backlog, не feature_list. Перенести non-active в `BACKLOG.md`
- ❌ `init.sh` который делает `pip install torch==2.5.1+cu121` без index URL — supply chain risk + CUDA mismatch
- ❌ `done` со словом "вроде работает" в evidence — нет artifact'а = не `done`
- ❌ Параллельно две `in-progress` "потому что блокировка не настоящая" — переводи одну в blocked или not-started

## Источники

- [Learn Harness Engineering Lecture 06 — Initialization Phase](https://walkinglabs.github.io/learn-harness-engineering/ru/lectures/lecture-06-why-initialization-needs-its-own-phase/)
- [Learn Harness Engineering Lecture 08 — Feature Lists as Harness Primitives](https://walkinglabs.github.io/learn-harness-engineering/ru/lectures/lecture-08-why-feature-lists-are-harness-primitives/)
- [Learn Harness Engineering Lecture 09 — Declaring Victory Too Early](https://walkinglabs.github.io/learn-harness-engineering/ru/lectures/lecture-09-why-agents-declare-victory-too-early/)
- Source templates (MIT): `walkinglabs/learn-harness-engineering/skills/harness-creator/templates/`
