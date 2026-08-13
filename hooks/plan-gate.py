#!/usr/bin/env python3
"""UserPromptSubmit hook: gentle plan/spec-freeze reminder for substantive work.

Non-blocking. When the user's message asks for a substantive build/feature/refactor
AND the current project has no concrete plan artifact, emit a one-line suggestion to
freeze acceptance criteria first (Sprint Contract / Proof Loop, principles 01-02).
For multi-stage/release/external-prerequisite work without a stage ledger, emit a
separate reminder to seal prior stages before downstream work. Each fires at most
once per project per day.

Rationale: CLAUDE.md richly describes plan-validate-execute, but nothing nudges it.
This is a nudge, not a gate — it never blocks, never forces. Companion to the
no-pre-existing-evasion / finish-the-task stack.

Register in settings.json:
{ "hooks": { "UserPromptSubmit": [{ "hooks": [{ "type": "command",
  "command": "python path/to/plan-gate.py" }] }] } }
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

# Substantive-build intent (RU/EN). Deliberately specific to avoid chatter.
BUILD_PATTERNS = [
    r"\b(построй|собери|сделай|напиши|реализуй|создай|разработай)\b.*\b(сервис|приложение|систем|бэкенд|backend|фронтенд|frontend|api|пайплайн|pipeline|фич|модуль|бот|воркер|worker)\b",
    r"\b(build|implement|create|develop|scaffold|write)\b.*\b(service|app|application|backend|frontend|api|pipeline|feature|module|bot|worker|system)\b",
    r"\b(рефактор|refactor|перепиши|rewrite|мигрируй|migrate)\b",
    r"\b(новый проект|new project|с нуля|from scratch|greenfield)\b",
]

STAGE_PATTERNS = [
    r"\b(release|релиз|stage|staged|phase|фаз\w*|pipeline|конвейер|promot\w*|продвиж\w*)\b",
    r"\b(signer|подпис\w*|cms|msvc|staging|production|prod|внешн\w* зависим\w*|external (?:dependency|service)|инфраструктур\w*)\b",
]

PLAN_ARTIFACTS = ["PLAN.md", "TODO.md", "feature_list.json"]
SPEC_GLOBS = ["PLAN*.md", "SPEC*.md", "*.spec.md", "DESIGN.md", "RFC*.md"]
STAGE_LEDGER = Path(".proof") / "stage-ledger.json"


def has_plan_artifact(cwd: Path) -> bool:
    for name in PLAN_ARTIFACTS:
        if (cwd / name).exists():
            return True
    for pat in SPEC_GLOBS:
        if any(cwd.glob(pat)):
            return True
    return False


def already_reminded_today(cwd: Path, kind: str) -> bool:
    key = hashlib.sha1(str(cwd).encode("utf-8", "ignore")).hexdigest()[:12]
    marker = Path(os.environ.get("TEMP", "/tmp")) / f".plan-gate-{kind}-{key}"
    if marker.exists() and (time.time() - marker.stat().st_mtime) < 86400:
        return True
    try:
        marker.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass
    return False


def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        return 0

    prompt = str(event.get("prompt") or event.get("user_prompt") or "")
    if not prompt:
        return 0

    if not any(re.search(p, prompt, re.IGNORECASE) for p in BUILD_PATTERNS):
        return 0

    cwd = Path.cwd()
    if any(re.search(p, prompt, re.IGNORECASE) for p in STAGE_PATTERNS) and not (cwd / STAGE_LEDGER).is_file():
        if already_reminded_today(cwd, "stage"):
            return 0
        print(
            "[plan-gate] Multi-stage work has no .proof/stage-ledger.json. Before downstream edits, "
            "freeze the stage contract and seal accepted inputs with commit/tree, input/output hashes, "
            "and a fresh verdict. Record unavailable external prerequisites as BLOCKED. Non-blocking; shown once/day."
        )
        return 0

    if has_plan_artifact(cwd):
        return 0
    if already_reminded_today(cwd, "plan"):
        return 0

    print(
        "[plan-gate] Substantive build with no PLAN.md / SPEC / feature_list.json in "
        f"'{cwd.name}'. Consider freezing acceptance criteria first (Sprint Contract / "
        "Proof Loop, principles 01-02) before mass edits. Non-blocking; shown once/day."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
