---
paths:
  - "**/MEMORY.md"
  - "**/memory/*.md"
  - "**/CLAUDE.md"
  - "**/.claude/rules/*.md"
---

# Memory & Rules Maintenance — cross-links, provenance, delta-merge

How durable memory/rules stay navigable, honest, and self-improving without rot. Three concerns:
(1) a cross-link graph, (2) provenance honesty per claim, (3) delta-merge updates (no rewrite).

## 1. Cross-links — wiki-links graph

Memory/rule files reference each other with wiki-links `[[filename]]` (without `.md`). A navigable knowledge graph, no database.

**Where:** inline (`Trains on [[reference_gpu_servers]] using [[docker_production]].`) and a `## Related` section at the end (`- [[reference_gpu_servers]] - trains here`).

**When:** on **create** — link to existing related entries immediately; on **update** — check if new connections emerged. Only **meaningful** links (test: "would navigating this help understand the current entry?").

**Common clusters:** Infrastructure (servers → docker → access) · Projects (project → server → methodology) · Methodology (practice → article → project) · Tools (A ↔ B alternatives) · Feedback (correction → context).

**Benefits:** navigation, context, discovery, and the graph survives any tool change (plain markdown).

## 2. Provenance tags — mark verified vs inferred

A memory must be honest about *how sure* each load-bearing claim is, so a future session knows what to trust vs re-verify. This is `no-guessing.md` extended into memory — the recall caveat ("verify a named file/flag still exists before recommending") made explicit at write time.

Tag **load-bearing** claims (facts that drive a decision), not every sentence — over-tagging is noise:
- `(extracted)` — directly from a verifiable source: code, probe/command output, docs, or a user quote. Strongest. Name the source inline where useful: `port 5877 (extracted: ssh config)`.
- `(inferred)` — my own conclusion/deduction, not stated by any single source. Next session treats it as a hypothesis.
- `(ambiguous)` — sources disagree, or the claim is unverified/uncertain. Flags "check before acting".

Notation: a short inline marker after the claim, or one provenance note per section. An untagged claim reads as ordinary durable fact — reserve tags for where verified-vs-guessed matters (infra values, "X works/exists", capacities, anything a future session would act on).

```markdown
The GPU host has NO fail2ban (extracted: /etc/fail2ban absent, checked on host).
The flaky link is probably a snap-packaged daemon (inferred - not root-caused).
Upload ceiling ~0.5 MB/s (ambiguous - measured once, may vary by time of day).
```

## 3. Delta-merge — self-improve rules/memory without context collapse (ACE)

Источник: [Agentic Context Engineering, arXiv 2510.04618](https://arxiv.org/abs/2510.04618) (Generator → Reflector → Curator). Когда CLAUDE.md / rules / memory обновляются «уроками сессии» — обновлять **структурированными ДЕЛЬТАМИ (диффами), а не переписывать файл целиком**. Полное переписывание агентом ведёт к **context collapse**: каждый проход размывает накопленные нюансы, файл деградирует к более общей и короткой версии. Delta-мёрж сохраняет накопленное и правит точечно. Это принципиальная версия Session Learning Extraction и апгрейд `revise-claude-md`.

**Три роли (разделять, не совмещать):**
1. **Generator** — делает работу сессии; производит траекторию (что сработало, коррекции user, решения).
2. **Reflector** — читает траекторию + **текущий** целевой файл; выдаёт кандидатов-**дельт**: `ADD` (новый пункт), `EDIT` (уточнить существующий, с цитатой старого), `DELETE` (устарело/неверно, с обоснованием). НЕ переписывает файл.
3. **Curator** — детерминированно **применяет** дельты (ADD дописывает, EDIT — точечный search/replace, DELETE — удаляет именованный блок), дедуп против существующего. Результат = **дифф**, верифицируемый глазами/свежим агентом, а не свеже-сгенерённый файл.

**Правила:** никогда не «перепиши весь файл» — только адресные дельты · каждая дельта самодостаточна (что/почему/где) · **dedup обязателен** перед ADD (иначе файл пухнет дублями) · Curator ≠ Reflector (Generator-Evaluator: предложивший дельту не подтверждает её применение) · **сохранять, не сжимать** — правка ценой потери нюанса = context collapse, отклонить.

**Когда:** конец сессии (Session Learning Extraction) вместо «перепиши CLAUDE.md» · `revise-claude-md` / `/remember` · обновление любого долгоживущего rule/principle/memory по итогам инцидента. **НЕ нужно** для создания НОВОГО файла с нуля (нечего терять — пиши целиком). Реализация-скелет — `scripts/ace_context_merge.workflow.js` (Reflector на дорогой модели = «что менять», Curator детерминированный JS = «как применить»).

**Anti-patterns:** ❌ «перепиши с учётом сессии» → collapse · ❌ ADD без dedup → дубли · ❌ Reflector сам же применяет (нет независимой проверки) · ❌ «почистил, стало короче» как успех — короче ≠ лучше для накопленного контекста · ❌ применять delta-мёрж к новому файлу.

## Related
- `no-guessing.md` — provenance = его расширение в память; Reflector/Curator = Generator-Evaluator на правках.
- `quality-over-tokens-independent-verify.md` — Reflector/Curator = независимая проверка применения.
- `edit-formats-and-tiering.md` — дельты = search/replace; модель-тиринг Reflector(дорогая)/Curator(дешёвая/код).
- `finish-the-task.md` — канон; обновления правил по урокам сессии идут через delta-merge, не rewrite.
