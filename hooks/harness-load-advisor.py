#!/usr/bin/env python3
"""Stop hook: surface an over-constrained or mis-scoped agent harness.

This is a feedback guard, not a release bypass. It detects when the final
assistant message says that a high-cost or specialized gate (for example
production signing, a VM/GPU/OS compatibility run, or a stress matrix) is
blocking a lower-risk smoke. The hook then requires a user-visible diagnosis
and a profile split before the turn closes.

The signal is intentionally narrow. It does not infer overload from elapsed
time alone and it never disables security or release evidence. Short event
records are written outside the repository for later harness tuning.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from safety_common import stop_budget_consume, stop_budget_exhausted
except ImportError:  # fail-open if a standalone copy is executed
    stop_budget_consume = stop_budget_exhausted = None  # type: ignore[assignment]


BUDGET_NAME = "harness-overload"
FEEDBACK_DIR = Path(
    os.environ.get("HARNESS_FEEDBACK_DIR", str(Path.home() / ".claude" / "harness-feedback"))
)
FEEDBACK_PATH = FEEDBACK_DIR / "events.jsonl"

# These patterns require both a harness/gate signal and a consequence. A mere
# mention of a specialized or release check in a design note is not an overload
# event.
SIGNALS: list[tuple[str, list[str]]] = [
    (
        "declared-overload",
        [
            r"\b(harness|test system|system of tests|vm[- ]harness|харнесс|система тест\w*)\b"
            r"[^.?!\n]{0,120}\b(overload\w*|over[- ]constrain\w*|too (strict|restrictive|heavy)|"
            r"перегруж\w*|слишком (жестк\w*|зажат\w*|тяжел\w*))\b",
            r"\b(block\w*|не (да[её]т|позволя\w*|пропуска\w*)|блокир\w*)\b"
            r"[^.?!\n]{0,120}\b(staging|staging smoke|smoke test|стейдж\w*|смоук\w*)\b",
            r"\b(production[- ]signing|release[- ]only|authenticode|vm[- ](?:run|test|harness)|"
            r"virtual machine|gpu[- ](?:run|test|runner)|os[- ]matrix|abi|browser[- ]matrix|"
            r"compatibility|hardware|performance|stress|load[- ]test|nightly|подпис\w* production|"
            r"релиз\w* подпис\w*|совместим\w*|аппаратн\w*|нагрузочн\w*)\b"
            r"[^.?!\n]{0,120}\b(staging|smoke|обычн\w* тест|стейдж\w*|быстр\w* тест)\b",
        ],
    ),
    (
        "explicit-feedback",
        [
            r"\b(too (strict|restrictive|much|heavy)|overkill|over[- ]engineer\w*|"
            r"blocks? (the )?(staging|smoke)|false positive|false-positive)\b",
            r"\b(слишком (строг\w*|жестк\w*|зажат\w*|много|тяжел\w*)|"
            r"перегруж\w*|избыточн\w*|ложн\w* срабатыван\w*|блокир\w* smoke)\b",
        ],
    ),
]

META_MARKERS = (
    "[harness_overload]",
    "harness-load-advisor.py",
    "harness overload guard",
    "feedback guard",
)


def last_assistant_message(transcript_path: str | None) -> str:
    if not transcript_path:
        return ""
    path = Path(transcript_path)
    if not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = item.get("message", item)
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
    return ""


def detect(message: str) -> list[str]:
    lowered = message.lower()
    if any(marker in lowered for marker in META_MARKERS):
        return []
    hits: list[str] = []
    for name, patterns in SIGNALS:
        if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in patterns):
            hits.append(name)
    return hits


def _profile(message: str) -> str:
    lowered = message.lower()
    if re.search(r"staging|smoke|стейдж|смоук", lowered):
        return "staging-smoke"
    if re.search(r"security|proof|hostile|fresh evaluator|безопасн|провер\w* границ", lowered):
        return "security-proof"
    if re.search(r"release|signing|authenticode|production|релиз|подпис", lowered):
        return "release-attestation"
    if re.search(r"vm|virtual machine|gpu|os[- ]matrix|abi|browser|compatibility|hardware|performance|stress|load[- ]test|nightly|совместим|аппаратн|нагрузоч", lowered):
        return "compatibility-proof"
    return "unknown"


def policy_mismatch(cwd: Path) -> list[str]:
    """Return profile-contract violations without executing repository commands."""
    policy_path = cwd / ".claude" / "test-policy.json"
    if not policy_path.is_file():
        return []
    try:
        data = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    profiles = data.get("profiles")
    staging = profiles.get("staging-smoke") if isinstance(profiles, dict) else None
    if not isinstance(staging, dict):
        return []
    commands = staging.get("commands", [])
    forbidden = staging.get("forbidden_tokens", [])
    if not isinstance(commands, list) or not isinstance(forbidden, list):
        return []
    command_text = " ".join(
        item
        for command in commands
        if isinstance(command, list)
        for item in command
        if isinstance(item, str)
    ).lower()
    return [
        "policy-staging-smoke-forbidden"
        for token in forbidden
        if isinstance(token, str) and token and token.lower() in command_text
    ][:1]


def record(event: dict, hits: list[str], message: str) -> None:
    """Persist metadata only; never copy the transcript into the feedback log."""
    try:
        FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
        lowered = message.lower()
        record = {
            "ts": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "event": "harness-overload",
            "categories": hits,
            "profile": _profile(message),
            "session_id": str(event.get("session_id") or event.get("sessionId") or ""),
            "cwd": str(event.get("cwd") or Path.cwd()),
            "mentions_release_gate": bool(re.search(r"signing|release|authenticode|подпис|релиз", lowered)),
            "mentions_specialized_gate": bool(re.search(
                r"vm|virtual machine|gpu|os[- ]matrix|abi|browser|compatibility|hardware|performance|stress|load[- ]test|nightly|совместим|аппаратн|нагрузоч",
                lowered,
            )),
            "mentions_staging_smoke": bool(re.search(r"staging|smoke|стейдж|смоук", lowered)),
        }
        with FEEDBACK_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    if os.environ.get("CLAUDE_SKIP_HARNESS_FEEDBACK", "").lower() in {"1", "true", "yes", "on"}:
        return 0

    message = last_assistant_message(
        event.get("transcript_path")
        or event.get("transcriptPath")
        or event.get("transcript")
        or os.environ.get("CLAUDE_CODE_TRANSCRIPT_PATH")
    )
    hits = detect(message)
    configured_hits = policy_mismatch(Path.cwd())
    if configured_hits:
        hits.extend(configured_hits)
    if not hits:
        return 0
    observed = message or "staging-smoke policy contains a forbidden costly/specialized token"
    record(event, hits, observed)

    if stop_budget_exhausted is not None and stop_budget_exhausted(BUDGET_NAME, Path.cwd()):
        return 0
    if stop_budget_consume is not None:
        stop_budget_consume(BUDGET_NAME, Path.cwd())

    profile = "staging-smoke" if configured_hits else _profile(message)
    reason = (
        "[HARNESS_OVERLOAD] The final report identified a harness/profile overload "
        f"({', '.join(hits)}; apparent profile: {profile}). Before ending, tell the user: "
        "which requested profile was blocked, which gate caused it, the command or "
        "evidence proving the mismatch, and the smallest profile split that fixes it. "
        "Keep the gate when the requested profile needs it; move unrelated costly "
        "or specialized checks (VM/GPU/OS/ABI/browser/hardware/performance/signing) "
        "out of lower-risk smoke. Run the reduced smoke and record the result. "
        "Do not call the harness fixed by merely bypassing a gate."
    )
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
