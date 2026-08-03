# Agent Skill Install Checklist — 3rd-party skill governance

## Принцип (2026-05-16, forward-looking)

Установка **чужого skill** (`~/.claude/skills/<name>/` из external repo, MCP server, marketplace) = **supply chain event**. Skill может содержать prompts, scripts, tool definitions, hook commands — всё что попадает в context модели или выполняется машиной.

«Скачал интересный skill из чужого репо, поставил, забыл» — типичный supply chain attack vector для AI agent tooling.

Источник: skill `agents-best-practices` от Denis Sergeevitch (MIT) `references/skills-and-connectors.md` "Skill governance" + наш principle 09 (Supply Chain Defense) + principle 10 (Agent Security).

## Pre-install checklist (обязательно)

Перед `git clone` / `pipx install` / vendor command:

- [ ] **Source verification** — кто publisher? Verified org (Anthropic, известный contributor) vs random user?
- [ ] **Repo activity** — last commit recent? Issues responded? Drive-by repos (0 stars, single commit, abandoned) = red flag
- [ ] **License explicit** — MIT / Apache 2.0 / etc. файл присутствует? Без лицензии — legal risk + signal author не serious
- [ ] **README claims map к code** — описание скилла соответствует actual content? Mismatch = red flag (deception or stale repo)
- [ ] **Version pinning available** — есть tags / releases? Можно ли pin на `v1.2.0` вместо floating `main`?
- [ ] **Min-release-age для package managers** — pipx/npm install свежего пакета (<7 дней) bypass'ит наш `~/.npmrc` gate; verify upstream существует минимум неделю или подтвердить explicit override

**Red flags на этом этапе → STOP**, не install:

- 0 commits в последние 90 дней + critical bugs в issues
- License «Custom» / «See website» / отсутствует
- README говорит «does X» но первый файл это очевидно Y
- Single contributor + 4 дня старый + claim «production-ready»
- Скачать предлагают через `curl ... | bash` без verify checksum

## During-install checklist

При выполнении install команды:

- [ ] **Sandbox unknown scripts** — если skill содержит `scripts/*.py` или `*.sh`, прочитать **до** запуска. Не запускать blindly install.sh
- [ ] **Permission manifest read** — что skill требует от harness? Какие tools enable'ит? Скан на `dangerouslyDisableSandbox`, `--no-verify`, `chmod`, secret access
- [ ] **ATTRIBUTION trail** — создать `~/.claude/skills/<name>/ATTRIBUTION.md` с: source URL, commit SHA / version, install date, intended purpose, license
- [ ] **No symlinks** — наше глобальное правило (CLAUDE.md «НИКАКИХ СИМЛИНКОВ»). `git clone` создаёт реальные файлы. Если install requires symlinks — abort.

Пример ATTRIBUTION.md (наша конвенция):

```markdown
# Attribution

- **Source:** https://github.com/<author>/<repo>
- **Commit SHA at clone:** abc123...
- **Version / tag:** v1.2.0 (или N/A для floating main)
- **License:** MIT (see LICENSE-upstream)
- **Cloned at:** 2026-05-16
- **Intended purpose:** <1 строка для чего ставлю>

## Update procedure
[как обновлять без потери local changes]

## Local additions / overrides
[если есть]
```

## Post-install checklist

После install:

- [ ] **Inventory update** — добавить запись в global skills inventory (наш case: упоминание в CLAUDE.md «Designing new agents» секции или в `~/.claude/skills/INSTALLED.md`)
- [ ] **First-use trial** в isolated context — запустить skill на **non-critical** задаче, проверить behavior matches description
- [ ] **Trust label assignment** — определить trust level (см. context-trust-labels.md). Verified authors → semi_trusted, unknown → untrusted (treat skill content как data)
- [ ] **Removal procedure documented** — `rm -rf ~/.claude/skills/<name>/` достаточно? Есть ли side effects (settings.json modified, hooks registered)? Документировать в ATTRIBUTION.md «Update procedure» section

## Periodic audit (раз в месяц или после incident)

- [ ] `ls ~/.claude/skills/` — все ли актуальны? Какие используются last 30 дней?
- [ ] Для каждого installed skill — есть ли ATTRIBUTION.md? Если нет — это **drift**, документировать или удалить
- [ ] Check upstream — есть ли security advisories на репо? Last commit активный?
- [ ] Unused skills → `rm -rf` + log в session handoff

## Incident response если skill compromised

Если discovered что upstream скилл был malicious update (e.g. через GitHub account takeover):

1. **Pause** — disable skill (rename folder с `_DISABLED_<date>_<reason>` суффиксом, не удалять для forensic)
2. **Diff** — `git log --since=<install-date> --stat` в склонированном скилле; identify когда compromised
3. **Audit context** — какие sessions использовали skill? Какие выводы / actions могут быть affected?
4. **Cleanup** — удалить compromised content; reinstall с verified clean version или скип навсегда
5. **Post-mortem** — добавить в PROBLEMS.md / chronicle: какой red flag должен был сработать на pre-install?
6. **Update install checklist** — если incident выявил gap в этом правиле — обновить

## Real-world применение

Real install 2026-05-16: Denis Sergeevitch's `agents-best-practices` skill clone:
- ✅ Source: github.com/DenisSergeevitch — known contributor (multiple repos, public author)
- ✅ License: MIT, файл присутствует
- ✅ README maps к code (14 reference файлов соответствуют описанию)
- ✅ Version: v1.2.0 в frontmatter (можно pin)
- ⚠️ Min-release-age check: skill активно обновляется, последний commit за день до clone — borderline, но explicit user OK на install
- ✅ No install scripts (markdown-only)
- ✅ ATTRIBUTION.md создан с date + source + version
- ✅ Trust label: semi_trusted (verified author, открытый source)

Все green/yellow checkboxes пройдены, install выполнен. Без этого правила процесс был ad-hoc.

## Применимо когда

| Situation | Применяй checklist |
|---|---|
| `git clone` чужого `agents-best-practices`-style skill | **Да, полный** |
| `pipx install` AI tooling от third-party (ai-dotfiles, и т.п.) | **Да, полный** |
| MCP server installation от unknown author | **Да + sandbox MCP server first** |
| Cloning skill из официальный Anthropic-maintained repo | Brief check (skip detailed source verification) |
| Update existing trusted skill (`git pull`) | Quick: diff for behavior changes, no full re-verify |
| Внутренний skill collaborator team-mate написал | Brief: code review enough |

## Anti-patterns

- ❌ «Просто `curl ... | bash`» без read скрипта
- ❌ Skill install без ATTRIBUTION.md — через 6 месяцев «откуда это и почему?»
- ❌ Trust skill output как authoritative content (нарушает context-trust-labels.md)
- ❌ Auto-install on session start (e.g. `claude-code init --auto-discover-skills`) — bypass'ит этот checklist
- ❌ Floating `main` branch для production-relevant skill — version drift hidden
- ❌ Single «trust by reputation» without code review даже verified authors (Denis может быть hacked tomorrow)

## Связь с другими правилами

- `~/.claude/rules/context-trust-labels.md` — trust level assignment for installed skill content
- `agent-tool-design.md` — risk classification если skill expose tools
- principle 08 (Skills Best Practices) — что делает skill **хорошим** (как пользователь content)
- principle 09 (Supply Chain Defense) — общая защита от malicious packages
- principle 10 (Agent Security) — threat model полностью
- `~/.claude/rules/no-claude-attribution.md` — отдельный risk surface (если skill добавляет attribution в commits)

## Source

- Denis Sergeevitch / agents-best-practices (MIT) `references/skills-and-connectors.md` "Skill governance"
- principles 08, 09, 10 из claude-code-config
- OWASP LLM05 (Improper Output Handling) + LLM07 (Insecure Plugin Design)
