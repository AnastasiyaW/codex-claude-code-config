#!/usr/bin/env python3
"""UserPromptSubmit: detect natural-language keywords and suggest matching skills.

Inspired by oh-my-claudecode's keyword detection hook. Instead of requiring
users to know skill names, this hook scans the user's message for trigger
phrases and outputs a suggestion that the agent can act on.

Non-blocking: outputs a suggestion, does not force skill invocation.
The agent decides whether the suggestion is relevant.

Setup in settings.json:
{
  "hooks": {
    "UserPromptSubmit": [{
      "hooks": [{
        "type": "command",
        "command": "python hooks/keyword-skill-router.py"
      }]
    }]
  }
}
"""
from __future__ import annotations

import json
import re
import sys

# Routes whose skill is provided locally and is NOT shipped in this repository:
# product-specific or private. The route stays because it is correct on a machine
# that has the skill; the wiring audit reads this set so a checkout without them
# is not reported as broken. Anything not listed here MUST exist in the repo --
# that is what keeps the audit meaningful.
LOCAL_ONLY_SKILLS = {
    "native-cpp-memory",
    "retouch-security-audit",
    "investigate",
    # Claude-only by content, not by policy: it references ~/.claude paths and tools
    # Codex does not have, so copying it there would look installed and could not work.
    # Declaring it is the honest version of the same statement.
    "harness-audit",
}

# ─── Keyword → Skill mapping ───
# Each entry: pattern (regex, case-insensitive) → skill name + description
# Patterns should be specific enough to avoid false positives on normal conversation
ROUTES = [
    # Provider-neutral remote compute: RunPod, Massed Compute, and owned servers.
    # Keep provider names in the trigger set, but route all of them to the
    # canonical skill so the transport/reconciliation policy is shared.
    {
        "patterns": [
            r"\b(runpod|run pod|massed[ -]?compute|massedcompute|мас+ед[ -]?компьют|мас+копьют|массед[ -]?компьют)\b",
            r"\b(remote|удал\w*|облач\w*)\b.{0,80}\b(gpu|гпу|видеокарт\w*|server|сервер\w*|vm|виртуал\w* машин\w*|compute|инфраструктур\w*|ssh|scp|bridge|мост\w*|tunnel|туннел\w*|bastion|tailscale|cloudflared)\b",
            r"\b(ssh|scp|tailscale|cloudflared|bridge|мост\w*|tunnel|туннел\w*)\b.{0,100}\b(remote|удал\w*|server|сервер\w*|gpu|гпу|vm|машин\w*|compute|runpod|massed)\b",
            r"\b(api|mcp|429|rate[ -]?limit|поллинг|polling|подключ\w*)\b.{0,100}\b(runpod|massed|remote|удал\w*|bridge|мост\w*|ssh|server|сервер\w*)\b",
        ],
        "skill": "remote-compute-ops",
        "description": "REQUIRED for RunPod, Massed Compute, and owned-server GPU lifecycle, bridge reuse, bounded API/SSH usage, and spend control",
        "refs": ["references/transport-safety.md", "references/provider-matrix.md"],
        "required": True,
    },
    # Retouch native variant experiments / measured implementation selection
    {
        "patterns": [
            r"\b(retouch|ретуш|photoshop|uxp|plugin|плагин|native|c\+\+)\b.*\b(вариант|variants?|scorecard|benchmark|бенчмарк|сравн|лучший|winner|experiment|эксперимент)\b",
            r"\b(вариант|variants?|scorecard|benchmark|бенчмарк|сравн|лучший|winner|experiment|эксперимент)\b.*\b(retouch|ретуш|photoshop|uxp|plugin|плагин|native|c\+\+)\b",
        ],
        "skill": "native-cpp-memory",
        "description": "REQUIRED for measured C++ implementation-variant experiments and retouch plugin scorecards",
        "refs": [
            "references/variant-experiments.md",
            "references/retouch-native.md",
        ],
        "required": True,
    },
    # Retouch security / ethical hacking / release hardening
    {
        "patterns": [
            r"\b(ретуш|retouch|photoshop|uxp|плагин|plugin|нейро\w*|trustmark|watermark)\b.*\b(взлом|хак|этичн\w*.*хак|pentest|penetration|уязвим|exploit|security audit|security review|безопасн|crack|license bypass|tamper|reverse)\b",
            r"\b(взлом|хак|pentest|penetration|уязвим|exploit|security|безопасн|crack|tamper|reverse)\b.*\b(retouch|ретуш|photoshop|uxp|plugin|плагин|native addon|trustmark|watermark)\b",
            r"\b(test|тест|qa|smoke|ctest|build)\b.*\b(retouch|ретуш|photoshop|uxp|plugin|плагин)\b.*\b(security|безопасн|уязвим|взлом)\b",
        ],
        "skill": "retouch-security-audit",
        "description": "REQUIRED for defensive ethical hacking, vulnerability testing, and release hardening of the retouch plugin",
        "refs": [
            "references/release-checklist.md",
            "references/sources.md",
        ],
        "required": True,
    },
    # ComfyUI driven through MCP / comfy-cli (agent-orchestrated graphs)
    {
        "patterns": [
            r"\bcomfy[- ]?mcp\b",
            r"\b(comfy-cli|comfy cli)\b",
            r"\b(comfy ?ui|comfyui|комфи\w*)\b.*\b(mcp|api|workflow|воркфлоу|граф|node|узл\w*|queue|очеред\w*|автоматиз\w*|automat\w*|агент|agent)\b",
            r"\b(mcp|workflow|воркфлоу|граф|автоматиз\w*|automat\w*)\b.*\b(comfy ?ui|comfyui|комфи\w*)\b",
        ],
        "suggest": "Use the Comfy MCP/comfy-cli workflow guidance if this task drives ComfyUI from an agent.",
    },
    # Claude/Codex continuation: preserve an accepted implementation and decisions.
    {
        "patterns": [
            r"\b(claude|кодекс|codex)\b.{0,80}\b(codex|claude|handoff|хенд[ао]ф|продолж|перенос)\b",
            r"\b(продолж\w*|додел\w*|перенест\w*|синерг\w*|не передел\w*|не перепис\w*)\b.{0,100}\b(код|работ\w*|агент\w*|сесс\w*|кодекс|codex|claude|клавд)\b",
            r"\b(cross[- ]harness|continuity contract|continuation contract|replan mode)\b",
        ],
        "skill": "cross-harness-continuation",
        "description": "REQUIRED when continuing work across Claude/Codex: load CONTINUITY.json, preserve decisions, and verify scope before edits",
        "required": True,
    },
    # Retouch native / low-level memory
    {
        "patterns": [
            r"\b(retouch plugin|photoshop plugin|uxp hybrid|uxp.*native|native addon|neural plugin|нейро\w*.*плагин|плагин.*нейро\w*)\b",
            r"\b(плагин|plugin)\b.*\b(ретуш|retouch|photoshop|uxp)\b.*\b(c\+\+|native|натив|memory|памят|abi|onnx|directml|coreml|metal|gpu|buffer|tensor)\b",
            r"\b(ретуш|retouch)\b.*\b(плагин|plugin|нейро\w*|onnx|directml|coreml|metal)\b.*\b(memory|памят|c\+\+|native|натив|buffer|tensor)\b",
        ],
        "skill": "native-cpp-memory",
        "description": "REQUIRED for retouch/native/neural plugin memory, ABI, tensor, GPU, and C++ ownership work",
        "refs": [
            "references/retouch-native.md",
            "references/low-level-retouch-memory.md",
            "references/windows-memory-abi.md",
            "references/macos-memory-abi.md",
            "references/advanced-cpp.md",
        ],
        "required": True,
    },
    # Clean architecture guardrails — keep this as an advisory rule, not a
    # skill route. The old target (clean-architecture) is not installed in the
    # active skill catalog, so emitting it produced an unusable suggestion.
    {
        "patterns": [
            r"\b(напиши|запили|добавь|сделай|создай|почини|исправь|перепиши|спроектируй|отрефактор\w*|refactor\w*|implement|write|add|create|fix|build|design|rewrite)\b.{0,80}\b(код|функци\w*|класс\w*|модул\w*|сервис\w*|фич\w*|скрипт\w*|приложени\w*|проект\w*|endpoint|api|бэкенд|backend|frontend|парсер\w*|бот\w*|code|function|class|module|service|feature|script|app\b|application|component|library|parser|bot)\b",
            r"\b(код|функци\w*|класс\w*|модул\w*|сервис\w*|фич\w*|скрипт\w*|code|function|class|module|service|feature)\b.{0,80}\b(напиши|добавь|сделай|создай|почини|исправь|refactor\w*|implement|write|add|create|fix)\b",
            r"\b(архитектур\w*|architecture|структур\w* проект\w*|project structure|clean architecture|чист\w* архитектур\w*|solid|dependency rule|слои|layers?)\b",
            r"\b(новый проект|new project|с нуля|from scratch|scaffold|каркас)\b",
        ],
        "suggest": "Apply the quality-code rule and keep dependency boundaries explicit while implementing this change.",
    },
    # Planning & Architecture (plan mode is built-in, not a skill)
    {
        "patterns": [
            r"\b(спланируй|составь план|plan this|make a plan|design the approach)\b",
            r"\b(архитектур|architect)\b.*\b(реши|спроектируй|design|plan)\b",
        ],
        "suggest": "Enter plan mode (built-in) - structured planning with acceptance criteria",
    },
    # Code Review
    {
        "patterns": [
            r"\b(сделай ревью|code review|review this|проверь код|review the pr)\b",
            r"\b(pr review|pull request review)\b",
        ],
        "skill": "deep-review",
        "description": "Parallel competency-based code review (security, perf, arch)",
    },
    # Monitoring and observability
    {
        "patterns": [
            r"\b(monitoring|observability|alerts?|prometheus|grafana|opentelemetry|otel|tracing|telemetry|uptime|health check|service health|sli|slo|sla|error budget|burn[- ]rate|incident evidence)\b",
            r"\b(мониторинг|наблюдаемост\w*|алерт\w*|прометеус|графан\w*|трассиров\w*|телеметр\w*|здоровь\w* сервиса|доступност\w* сервиса|бюджет ошибок|доказательств\w* инцидент\w*)\b",
        ],
        "skill": "observability-monitoring",
        "description": "Evidence-backed monitoring, alerting, SLI/SLO, telemetry, and incident workflows",
    },
    # Harness/configuration audit
    {
        "patterns": [
            r"\b(audit|auditing|проверь|аудит)\b.{0,80}\b(skills?|скилл\w*|hooks?|хуки|router|роутер|harness|харнесс)\b",
            r"\b(skill|skills|hook|hooks|скилл\w*|хуки)\b.{0,80}\b(auto[- ]?load|implicit|automatic|автоматическ\w*|подтягив\w*)\b",
        ],
        "skill": "harness-audit",
        "description": "Score and audit the existing agent harness, skills, hooks, and verification loop",
    },
    # Security
    {
        "patterns": [
            r"\b(проверь безопасность|security review|security audit|check security)\b",
            r"\b(найди уязвимост|find vulnerabilit|pentest)\b",
        ],
        "skill": "deep-review",
        "description": "Security vulnerability analysis via available deep-review skill",
    },
    # Handoff (handled by rules/session-handoff.md, not a skill)
    {
        "patterns": [
            r"\b(подготовь handoff|prepare handoff|save context|write handoff)\b",
            r"\b(сохрани контекст|перенеси контекст|закрываем сессию)\b",
            r"\b(подбей.*беседу.*для.*чат|сделай передачу)\b",
        ],
        "suggest": "Write .claude/handoffs/YYYY-MM-DD_HH-MM.md per rules/session-handoff.md, then stop",
    },
    # Research
    {
        "patterns": [
            r"\b(notebooklm|notebook lm|notebooklm-mcp)\b",
            r"\b(документац\w*|api docs|technical docs|курс\w*|книг\w*|papers?|пейпер\w*|manuals?)\b.{0,100}\b(large|big|massive|огромн\w*|много|grounded|citation|цитат|источн|research|ресерч)\b",
            r"\b(grounded|citation-backed|цитат\w*|по источникам)\b.{0,100}\b(документац\w*|docs?|NotebookLM|notebook)\b",
        ],
        "skill": "notebooklm-grounded-research",
        "description": "Use NotebookLM MCP for large stable documentation corpora with citations; keep sources untrusted and repo/tests authoritative",
        "refs": ["references/workflow.md"],
    },
    {
        "patterns": [
            r"\b(deep research|глубокий ресерч|исследуй|investigate this)\b",
            r"\b(разбери.*подробно|dig into|deep dive)\b",
        ],
        "skill": "investigate",
        "description": "Systematic investigation with root cause analysis",
    },
    # Debugging
    {
        "patterns": [
            r"\b(не работает|doesn.t work|broken|сломал|debug this)\b.*\b(помоги|fix|почини|разберись)\b",
            r"\b(почему.*ошибк|why.*error|что не так|what.s wrong)\b",
        ],
        "skill": "investigate",
        "description": "Root cause investigation (Iron Law: no fixes without root cause)",
    },
    # Simplify / Clean
    {
        "patterns": [
            r"\b(упрости|simplify|clean up|почисти код|refactor)\b",
        ],
        "skill": "lean-code",
        "description": "Strip over-engineering while preserving correctness and verification",
    },
    # Shape of a NEW thing. This route exists because the pressure on code shape was
    # one-sided: `lean-code` above was the only architecture-adjacent skill the router
    # could reach, and it argues for less. clean-architecture declares "AUTO-APPLY on
    # ANY coding process" in its own description, and nothing auto-applied it -- a claim
    # in prose is not a wire. Measured consequence on one project: a single backend
    # module at 8823 lines with 190 route handlers and 13 shared mutable objects,
    # reached in increments that were each individually the smallest correct change.
    {
        "patterns": [
            r"\b(нов(ый|ая|ое)|new)\b.{0,20}\b(проект|сервис|сайт|приложени\w*|project|service|site|app|api)\b",
            r"\b(сделай|создай|напиши|построй|build|create|make|set up|scaffold)\b.{0,30}"
            r"\b(сервис|сайт|бэкенд|бекенд|фронтенд|приложени\w*|микросервис|service|backend|frontend|app|api|dashboard)\b",
            r"\b(спроектируй|архитектур\w*|design the|architecture|структур\w* проекта|project structure)\b",
            r"\b(куда положить|где должен жить|where should .{0,20}(live|go))\b",
        ],
        "skill": "architecture-first",
        "description": "Decide the seams BEFORE the first file: dependency rule, module boundaries, domain contexts, where each thing lives",
    },
    # Will it hold, and where does the data live. Kept separate from the layout question
    # on purpose: capacity and storage are a different decision moment, and merging them
    # into the layout route made both answers vaguer.
    {
        "patterns": [
            r"\b(выдержит|нагрузк\w*|масштаб\w*|will it (hold|scale)|scal(e|ing)|throughput|capacity)\b",
            r"\b(как(ую|ой)|выбрать|choose|which)\b.{0,24}\b(баз\w* данных|бд|database|db|кеш|cache|очеред\w*|queue)\b",
            r"\b(шард\w*|sharding|партиционир\w*|partition\w*|реплик\w*|replica\w*|consistency|консистентн\w*)\b",
            r"\b(медленн\w*|slow)\b.{0,30}\b(запрос\w*|quer(y|ies)|под нагрузкой|at scale|in production)\b",
        ],
        "skill": "system-and-data-design",
        "description": "Estimate before drawing: load numbers, then storage engine, replication, partitioning, consistency",
    },
    # Unit-level comprehensibility while the code is being written.
    {
        "patterns": [
            r"\b(отревьюй|проверь|review)\b.{0,20}\b(код|code|функци\w*|класс\w*|модул\w*)\b",
            r"\b(тяжело читать|не понятно|hard to (read|follow)|unreadable|convoluted)\b",
            r"\b(имен\w*|назв\w*|naming|name this)\b.{0,20}\b(функци\w*|переменн\w*|метод\w*|function|variable|method)\b",
            r"\b(дубл\w*|duplicat\w*|too many (parameters|arguments)|pass-through|god (function|method))\b",
        ],
        "skill": "code-complexity",
        "description": "Deep modules, information hiding, honest names, error paths that do not swallow",
    },
    # Shape of an EXISTING thing that has grown. Distinct from the route above: that one
    # is about starting, this one is about a module that already outgrew its shape.
    {
        "patterns": [
            r"\b(разбей|раздели|вынеси|split|extract|break up|decompose)\b.{0,30}"
            r"\b(модул\w*|файл\w*|класс\w*|module|file|class|monolith|монолит)\b",
            r"\b(слишком (большой|длинный)|too (big|long|large)|god (object|class|module)|ball of mud)\b",
            r"\b(связност\w*|связи|coupling|cohesion|circular (import|dependency))\b",
        ],
        "skill": "refactoring-safely",
        "description": "Characterization tests first, then one named transformation at a time: constants, then owned state, then whole slices",
    },
    # Site review / SEO. Target is plugin-namespaced: it resolves only where the
    # plugin is installed, which is why the audit does not require it to exist.
    {
        "patterns": [
            r"\b(seo|сео)\b",
            r"\b(ревью|аудит|обзор|проверь|проверить|review|audit)\b.{0,40}\b(сайт\w*|страниц\w*|site|page|landing|лендинг)\b",
            r"\b(сайт\w*|страниц\w*|site|page)\b.{0,40}\b(ревью|аудит|review|audit)\b",
            r"\b(sitemap|robots\.txt|hreflang|canonical|structured data|микроразметк\w*|meta description|мета[- ]?описан\w*|core web vitals|индексац\w*|indexab\w*|crawlab\w*)\b",
            r"\bschema\.org\b",
        ],
        "skill": "claude-seo:seo",
        "description": "site review / SEO audit - technical SEO, schema, sitemaps, hreflang, Core Web Vitals, GEO/AEO. Use claude-seo:seo-page for one page, claude-seo:seo-audit for a full crawl",
    },
    # Init new project
    {
        "patterns": [
            r"\b(настрой проект|init|initialize|set up claude)\b.*\b(claude|project)\b",
            r"\b(создай claude\.md|create claude\.md)\b",
        ],
        "suggest": "Initialize CLAUDE.md with codebase documentation and run the config validation checks.",
    },
]


def detect_keywords(user_message: str) -> list[dict]:
    """Return matching skills for the user's message."""
    matches = []
    by_skill = {}
    for route in ROUTES:
        for pattern in route["patterns"]:
            if re.search(pattern, user_message, re.IGNORECASE):
                if "suggest" in route:
                    # Advisory route (built-in feature or rule, not a skill)
                    matches.append({"suggest": route["suggest"]})
                    break
                item = {
                    "skill": route["skill"],
                    "description": route["description"],
                    "refs": route.get("refs", []),
                    "required": route.get("required", False),
                }
                existing = by_skill.get(item["skill"])
                if existing:
                    existing["required"] = existing.get("required", False) or item.get("required", False)
                    existing_refs = list(existing.get("refs", []))
                    for ref in item.get("refs", []):
                        if ref not in existing_refs:
                            existing_refs.append(ref)
                    existing["refs"] = existing_refs
                else:
                    matches.append(item)
                    by_skill[item["skill"]] = item
                break  # one match per route is enough
    return matches


def main() -> int:
    # Read the hook event from stdin
    try:
        raw_input = sys.stdin.read().lstrip("\ufeff")
        event = json.loads(raw_input)
    except (json.JSONDecodeError, EOFError):
        return 0

    # Extract user message
    # UserPromptSubmit event structure may vary - try common paths
    message = ""
    if isinstance(event, dict):
        message = event.get("message", "")
        if not message and "content" in event:
            message = event["content"]
        if not message and "prompt" in event:
            message = event["prompt"]
        if not message and "user_prompt" in event:
            message = event["user_prompt"]

    if not message or len(message) < 5:
        return 0

    matches = detect_keywords(message)
    if not matches:
        return 0

    # Output suggestions (agent sees this in context)
    suggestions = []
    for m in matches:
        if "suggest" in m:
            suggestions.append(f"  {m['suggest']}")
            continue
        if m.get("required"):
            suggestions.append(f"  REQUIRED: Use skill {m['skill']} - {m['description']}")
        else:
            suggestions.append(f"  /{m['skill']} - {m['description']}")
        if m.get("refs"):
            suggestions.append(f"    refs: {', '.join(m['refs'])}")

    print(f"[skill-router] Detected {len(matches)} matching skill(s):")
    for s in suggestions:
        print(s)
    print("[skill-router] Consider invoking the suggested skill if relevant.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
