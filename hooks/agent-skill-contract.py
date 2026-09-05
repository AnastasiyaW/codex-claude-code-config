#!/usr/bin/env python3
"""Pre/PostToolUse delegation: bind a skill/evidence contract to each child.

The semantic loader can select a skill for a parent request, but a child task
starts with a separate prompt.  A coordinator therefore renders this compact,
task-bound contract before delegation.  The hook validates the exact schema
and binding at Claude Code's ``Task`` boundary.

It intentionally does *not* apply keyword matching to arbitrary child prose:
quoted data and translations can contain a trigger phrase.  The CLI performs
the curated routing before dispatch; the hook proves that the resulting,
task-bound contract was carried across the boundary.  Every child task gets a
contract, including an explicit ``no-high-confidence-match`` result.

Codex exposes ``spawn_agent`` through the local-function hook path (matcher
alias ``Agent``).  The pre-hook adds or validates the exact contract, then the
post-hook binds that route to the returned ``agent_id`` for SubagentStop.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from dataclasses import dataclass
from pathlib import Path

from safety_common import allow, block, log, read_event
from skill_contract_state import bind_agent, save_pending


def _load_router():
    router_path = Path(__file__).resolve().with_name("keyword-skill-router.py")
    spec = importlib.util.spec_from_file_location("keyword_skill_router", router_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load skill router from {router_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


detect_keywords = _load_router().detect_keywords


CONTRACT_VERSION = "4"
CONTRACT_OPEN = f'<agent-skill-contract version="{CONTRACT_VERSION}">'
CONTRACT_CLOSE = "</agent-skill-contract>"
CONTRACT_RE = re.compile(
    r'<agent-skill-contract version="(?P<version>[0-9]+)">'
    r"(?P<body>.*?)" + re.escape(CONTRACT_CLOSE),
    re.DOTALL,
)
SKILL_LINE_RE = re.compile(r"^- ([a-z0-9][a-z0-9:_-]*)$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ROUTING_SOURCE = "keyword-skill-router-v1"
SKILL_GAP_CHECKLIST = "skills/agent-harness-design/references/agent-skill-install-checklist.md"
SKILL_OPT_OUT_RE = re.compile(
    r"(?i)^(?:"
    r"(?:do\s+not|don't)\s+(?:use|load|invoke)\s+(?:any\s+)?skills?"
    r"|(?:не\s+используй(?:те)?|не\s+использовать)\s+"
    r"(?:никакие\s+)?(?:скилл\w*|навык\w*)"
    r"|без\s+(?:никаких\s+)?(?:скилл\w*|навык\w*)"
    r")\b"
)

# Machine-readable parity contract.  The runtime branches below intentionally
# differ because Claude calls the boundary ``Task`` while Codex exposes several
# aliases for ``spawn_agent``.  Keep the complete accepted set literal so the
# wiring audit does not have to guess control flow from the first comparison.
HARNESS_ACCEPTED_TOOLS = {
    "Task",
    "spawn_agent",
    "Agent",
    "collaboration.spawn_agent",
    "collaboration__spawn_agent",
}
CODEX_AGENT_TOOLS = HARNESS_ACCEPTED_TOOLS - {"Task"}


@dataclass(frozen=True)
class TaskContract:
    profile: str
    skills: list[str]
    missing_skills: list[str]
    route: str


@dataclass(frozen=True)
class TaskSelection:
    profile: str
    skills: list[str]
    missing_skills: list[str]
    route: str


def skill_routing_opted_out(task_text: str) -> bool:
    """Honor only a leading top-level directive, never quoted/literal payload."""
    for raw_line in task_text.splitlines():
        if not raw_line.strip():
            continue
        # The plain Task payload has no provenance metadata. Restricting this
        # authority-changing switch to its leading, unindented line makes the
        # boundary deterministic: blockquotes, fenced code, indented literals,
        # and later quoted examples cannot disable routing.
        if raw_line[:1].isspace() or raw_line.lstrip().startswith((">", "`", "~", "'", '"')):
            return False
        return bool(SKILL_OPT_OUT_RE.match(raw_line.strip()))
    return False


def route_for_task(task_text: str, skills: list[str], missing_skills: list[str] | None = None) -> str:
    if skill_routing_opted_out(task_text):
        return "user-opt-out"
    if missing_skills:
        return "skill-gap"
    return "curated" if skills else "no-high-confidence-match"


def select_task(task_text: str, profile: str = "claude") -> TaskSelection:
    """Select only routes the receiving client can load and expose real gaps."""
    profile = str(profile).strip().lower()
    if profile not in {"claude", "codex"}:
        raise ValueError(f"unsupported client profile: {profile}")
    if skill_routing_opted_out(task_text):
        return TaskSelection(profile, [], [], "user-opt-out")
    matches = detect_keywords(task_text, profile=profile)
    usable = [item for item in matches if "skill" in item]
    unavailable = [item for item in matches if "unavailable_skill" in item]
    required_usable = [str(item["skill"]) for item in usable if item.get("required")]
    required_missing = [
        str(item["unavailable_skill"]) for item in unavailable if item.get("required")
    ]
    if required_missing:
        # A required unavailable route is not usable context. Resolve that gap
        # first; do not dilute it by also claiming a different skill was used.
        skills, missing = [], list(dict.fromkeys(required_missing))
    elif required_usable:
        skills, missing = list(dict.fromkeys(required_usable)), []
    elif usable:
        skills, missing = [str(usable[0]["skill"])], []
    elif unavailable:
        skills, missing = [], [str(unavailable[0]["unavailable_skill"])]
    else:
        skills, missing = [], []
    return TaskSelection(profile, skills, missing, route_for_task(task_text, skills, missing))


def selected_skills(task_text: str, profile: str = "claude") -> list[str]:
    """Compatibility helper returning usable routes for one concrete client."""
    return select_task(task_text, profile).skills


def task_digest(task_text: str) -> str:
    """Bind the contract to the exact child prompt, ignoring outer whitespace."""
    return hashlib.sha256(task_text.strip().encode("utf-8")).hexdigest()


def render_contract(
    task_text: str,
    skills: list[str] | None = None,
    *,
    profile: str = "claude",
    missing_skills: list[str] | None = None,
) -> str:
    selection = select_task(task_text, profile)
    if skills is None:
        skills = selection.skills
    if missing_skills is None:
        missing_skills = selection.missing_skills
    route = route_for_task(task_text, skills, missing_skills)
    required_lines = ["required-skills:", *[f"- {skill}" for skill in skills]]
    if not skills:
        required_lines = ["required-skills: []"]
    missing_lines = ["missing-skills:", *[f"- {skill}" for skill in missing_skills]]
    if not missing_skills:
        missing_lines = ["missing-skills: []"]
    lines = [
        CONTRACT_OPEN,
        f"route: {route}",
        f"client-profile: {profile}",
        f"routing-source: {ROUTING_SOURCE}",
        f"task-sha256: {task_digest(task_text)}",
        *required_lines,
        *missing_lines,
        f"read-before-action: {'true' if skills else 'false'}",
        "decision-basis: source-required",
        "no-source-result: INCONCLUSIVE",
        "unavailable-skill-result: SEARCH_REVIEW_OR_RESEARCH_BUILD_AND_CONTINUE",
        f"skill-gap-checklist: {SKILL_GAP_CHECKLIST}",
        "task-instructions-precede-skill-methodology: true",
        "skill-caused-pause: cite-readable-skill-line-and-exact-instruction",
        CONTRACT_CLOSE,
    ]
    return "\n".join(lines)


def _parse_skill_list(lines: list[str], index: int, field: str) -> tuple[list[str] | None, int, str]:
    if index >= len(lines):
        return None, index, f"contract {field} field is missing"
    if lines[index] == f"{field}: []":
        return [], index + 1, ""
    if lines[index] != f"{field}:":
        return None, index, f"contract {field} field is invalid"
    index += 1
    values: list[str] = []
    while index < len(lines):
        match = SKILL_LINE_RE.fullmatch(lines[index])
        if not match:
            break
        values.append(match.group(1))
        index += 1
    if not values:
        return None, index, f"contract {field} list is empty"
    if len(values) != len(set(values)):
        return None, index, f"contract {field} list has duplicates"
    return values, index, ""


def _parse_contract_body(body: str, body_digest: str) -> tuple[TaskContract | None, str]:
    lines = body.strip().splitlines()
    if len(lines) < 11:
        return None, "contract is incomplete"
    expected_prefix = [
        ("route: ", None),
        ("client-profile: ", None),
        (f"routing-source: {ROUTING_SOURCE}", ROUTING_SOURCE),
        ("task-sha256: ", None),
    ]
    for index, (prefix, exact) in enumerate(expected_prefix):
        line = lines[index]
        if exact is not None and line != prefix:
            return None, f"contract field {index + 1} is invalid"
        if exact is None and not line.startswith(prefix):
            return None, f"contract field {index + 1} is invalid"
    route = lines[0].removeprefix("route: ")
    profile = lines[1].removeprefix("client-profile: ")
    digest = lines[3].removeprefix("task-sha256: ")
    if route not in {"curated", "skill-gap", "no-high-confidence-match", "user-opt-out"}:
        return None, "contract route is invalid"
    if profile not in {"claude", "codex"}:
        return None, "contract client profile is invalid"
    if not SHA256_RE.fullmatch(digest) or digest != body_digest:
        return None, "contract is not bound to this task prompt"

    index = 4
    skills, index, problem = _parse_skill_list(lines, index, "required-skills")
    if problem:
        return None, problem
    missing, index, problem = _parse_skill_list(lines, index, "missing-skills")
    if problem:
        return None, problem
    assert skills is not None and missing is not None
    if set(skills) & set(missing):
        return None, "contract required and missing skill lists overlap"
    if route == "curated" and (not skills or missing):
        return None, "contract curated route and skill lists disagree"
    if route == "skill-gap" and (skills or not missing):
        return None, "contract skill-gap route needs only missing skills"
    if route in {"no-high-confidence-match", "user-opt-out"} and (skills or missing):
        return None, "contract empty route and skill lists disagree"

    expected_suffix = [
        f"read-before-action: {'true' if skills else 'false'}",
        "decision-basis: source-required",
        "no-source-result: INCONCLUSIVE",
        "unavailable-skill-result: SEARCH_REVIEW_OR_RESEARCH_BUILD_AND_CONTINUE",
        f"skill-gap-checklist: {SKILL_GAP_CHECKLIST}",
        "task-instructions-precede-skill-methodology: true",
        "skill-caused-pause: cite-readable-skill-line-and-exact-instruction",
    ]
    if lines[index:] != expected_suffix:
        return None, "contract safety fields are incomplete or reordered"
    return TaskContract(profile=profile, skills=skills, missing_skills=missing, route=route), ""


def parse_contract(task_text: str) -> tuple[TaskContract | None, str]:
    """Parse one complete task-bound contract, rejecting look-alikes."""
    matches = list(CONTRACT_RE.finditer(task_text))
    if not matches:
        return None, "contract is missing"
    if len(matches) != 1:
        return None, "task must contain exactly one contract"
    match = matches[0]
    if match.group("version") != CONTRACT_VERSION:
        return None, f"contract version {match.group('version')} is obsolete"
    outside = (task_text[:match.start()] + task_text[match.end():]).strip()
    return _parse_contract_body(match.group("body"), task_digest(outside))


def task_body_without_contract(task_text: str) -> str | None:
    """Return the bound child prompt when it has exactly one contract."""
    matches = list(CONTRACT_RE.finditer(task_text))
    if len(matches) != 1:
        return None
    match = matches[0]
    return (task_text[:match.start()] + task_text[match.end():]).strip()


def task_text_from_event(event: dict) -> str:
    tool_input = event.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return ""
    for name in ("prompt", "task", "message", "description"):
        value = tool_input.get(name)
        if value:
            return str(value)
    return ""


def _nested_response_items(value):
    """Yield nested response objects and decode JSON-shaped text blocks."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _nested_response_items(child)
    elif isinstance(value, list):
        for child in value:
            yield from _nested_response_items(child)
    elif isinstance(value, str):
        stripped = value.strip()
        yield stripped
        if stripped.startswith(("{", "[")):
            try:
                decoded = json.loads(stripped)
            except json.JSONDecodeError:
                return
            yield from _nested_response_items(decoded)


def agent_id_from_response(response) -> str:
    for item in _nested_response_items(response):
        if isinstance(item, dict):
            for key in ("agent_id", "agentId"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            if any(key in item for key in ("task_name", "taskName")):
                value = item.get("id")
                if isinstance(value, str) and value.strip():
                    return value.strip()
        elif isinstance(item, str):
            match = re.search(
                r"(?i)\bagent[_ -]?id\b\s*[:=]\s*[\"']?([A-Za-z0-9._:/-]{3,})",
                item,
            )
            if match:
                return match.group(1)
    return ""


def _state_identity(event: dict) -> tuple[str, str]:
    return str(event.get("session_id") or "").strip(), str(event.get("tool_use_id") or "").strip()


def save_codex_pending(event: dict, task_text: str) -> str | None:
    session_id, tool_use_id = _state_identity(event)
    if not session_id or not tool_use_id:
        return "Codex delegation event is missing session_id or tool_use_id"
    contract, problem = parse_contract(task_text)
    if contract is None:
        return f"cannot persist an invalid task contract: {problem}"
    body = task_body_without_contract(task_text)
    assert body is not None
    try:
        save_pending(
            session_id,
            tool_use_id,
            {
                "task_sha256": task_digest(body),
                "route": contract.route,
                "client_profile": contract.profile,
                "required_skills": contract.skills,
                "missing_skills": contract.missing_skills,
                "turn_id": str(event.get("turn_id") or ""),
                "task_name": str((event.get("tool_input") or {}).get("task_name") or ""),
            },
        )
    except OSError as exc:
        return f"cannot persist the task-bound Codex route: {exc}"
    return None


def _codex_updated_input(event: dict, repaired_task: str) -> dict:
    updated = dict(event.get("tool_input") or {})
    field = next((name for name in ("message", "prompt", "task", "description") if updated.get(name)), "message")
    updated[field] = repaired_task
    return updated


def handle_codex_pre(event: dict) -> int:
    task_text = task_text_from_event(event)
    contract, _ = parse_contract(task_text)
    if contract is not None:
        permitted, reason = decision(task_text, profile="codex")
        if not permitted:
            block(reason)
        problem = save_codex_pending(event, task_text)
        if problem:
            block(problem)
        allow()

    clean_task = task_body_without_contract(task_text)
    if clean_task is None and "<agent-skill-contract" in task_text:
        block("Malformed or duplicate agent-skill-contract cannot be repaired safely")
    if clean_task is None:
        clean_task = task_text
    repaired_task = clean_task + "\n\n" + render_contract(clean_task, profile="codex")
    problem = save_codex_pending(event, repaired_task)
    if problem:
        block(problem)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "Added the task-bound skill contract before delegation.",
            "updatedInput": _codex_updated_input(event, repaired_task),
            "additionalContext": "A task-bound skill contract was added to the delegated brief.",
        }
    }, ensure_ascii=False))
    return 0


def handle_codex_post(event: dict) -> int:
    session_id, tool_use_id = _state_identity(event)
    if not session_id or not tool_use_id:
        return 0
    agent_id = agent_id_from_response(event.get("tool_response"))
    if not agent_id:
        log("WARN", "agent-skill-contract", "observe", "spawn-response-without-agent-id", "")
        return 0
    try:
        bound = bind_agent(session_id, tool_use_id, agent_id)
    except OSError:
        bound = False
    if not bound:
        log("WARN", "agent-skill-contract", "observe", "missing-pending-route", agent_id)
    return 0


def decision(task_text: str, profile: str = "claude") -> tuple[bool, str]:
    contract, problem = parse_contract(task_text)
    if contract is not None:
        task_body = task_body_without_contract(task_text)
        assert task_body is not None  # established by parse_contract above
        expected = select_task(task_body, profile)
        if (
            contract.profile == expected.profile
            and contract.skills == expected.skills
            and contract.missing_skills == expected.missing_skills
            and contract.route == expected.route
        ):
            return True, ""
        return False, (
            "Contract skill selection does not match the curated router for this "
            "task. Re-render it from the exact child prompt:\n"
            + render_contract(task_body, profile=profile)
        )
    clean_task = task_body_without_contract(task_text)
    if clean_task is None:
        clean_task = task_text
    repair = render_contract(clean_task, profile=profile)
    return False, (
        "Every delegated task needs one complete task-bound skill/evidence contract "
        f"({problem}). Render it before dispatch; append it when missing or replace "
        f"the stale/invalid contract:\n{repair}"
    )


def cli(task_text: str, as_json: bool, profile: str) -> int:
    selection = select_task(task_text, profile)
    payload = {
        "task": task_text,
        "client_profile": profile,
        "selected_skills": selection.skills,
        "missing_skills": selection.missing_skills,
        "route": selection.route,
        "contract": render_contract(task_text, profile=profile),
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(payload["contract"])
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--task", help="render a contract for this subagent task")
    parser.add_argument("--json", action="store_true", help="use JSON with --task")
    parser.add_argument("--profile", choices=("claude", "codex"), default="claude")
    args = parser.parse_args(argv)
    if args.task is not None:
        return cli(args.task, args.json, args.profile)

    event = read_event()
    tool_name = str(event.get("tool_name") or "")
    hook_event = str(event.get("hook_event_name") or "")
    if tool_name in CODEX_AGENT_TOOLS:
        if hook_event == "PostToolUse":
            return handle_codex_post(event)
        return handle_codex_pre(event)
    if tool_name != "Task":
        allow()
    task_text = task_text_from_event(event)
    permitted, reason = decision(task_text, profile="claude")
    if permitted:
        log("INFO", "agent-skill-contract", "allow", "valid-task-contract", task_text)
        allow()
    log("WARN", "agent-skill-contract", "block", "missing-or-invalid-contract", task_text)
    block(reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
