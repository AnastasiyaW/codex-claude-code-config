#!/usr/bin/env python3
"""PreToolUse(Task): validate a rendered skill and evidence contract.

The semantic loader can select a skill for a parent request, but a child task
starts with a separate prompt.  A coordinator therefore renders this compact,
task-bound contract before delegation.  The hook validates the exact schema
and binding at Claude Code's ``Task`` boundary.

It intentionally does *not* apply keyword matching to arbitrary child prose:
quoted data and translations can contain a trigger phrase.  The CLI performs
the curated routing before dispatch; the hook proves that the resulting,
task-bound contract was carried across the boundary.  Every child task gets a
contract, including an explicit ``no-high-confidence-match`` result.

Codex desktop does not expose Claude's ``Task`` event.  Its coordinator must
call ``--task`` and include the rendered output in the native child prompt.
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


def _load_router():
    router_path = Path(__file__).resolve().with_name("keyword-skill-router.py")
    spec = importlib.util.spec_from_file_location("keyword_skill_router", router_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load skill router from {router_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


detect_keywords = _load_router().detect_keywords


CONTRACT_VERSION = "2"
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


@dataclass(frozen=True)
class TaskContract:
    skills: list[str]
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


def route_for_task(task_text: str, skills: list[str]) -> str:
    if skill_routing_opted_out(task_text):
        return "user-opt-out"
    return "curated" if skills else "no-high-confidence-match"


def selected_skills(task_text: str) -> list[str]:
    """Return the smallest curated skill set selected before dispatch."""
    if skill_routing_opted_out(task_text):
        return []
    # Claude Code is the only client that enforces this Task-bound contract;
    # select against its capability profile, not the safe shared default for
    # old global UserPromptSubmit registrations.
    matches = [item for item in detect_keywords(task_text, profile="claude") if "skill" in item]
    required = [str(item["skill"]) for item in matches if item.get("required")]
    if required:
        return list(dict.fromkeys(required))
    if matches:
        return [str(matches[0]["skill"])]
    return []


def task_digest(task_text: str) -> str:
    """Bind the contract to the exact child prompt, ignoring outer whitespace."""
    return hashlib.sha256(task_text.strip().encode("utf-8")).hexdigest()


def render_contract(task_text: str, skills: list[str]) -> str:
    route = route_for_task(task_text, skills)
    required_lines = ["required-skills:", *[f"- {skill}" for skill in skills]]
    if not skills:
        required_lines = ["required-skills: []"]
    lines = [
        CONTRACT_OPEN,
        f"route: {route}",
        f"routing-source: {ROUTING_SOURCE}",
        f"task-sha256: {task_digest(task_text)}",
        *required_lines,
        f"read-before-action: {'true' if skills else 'false'}",
        "decision-basis: source-required",
        "no-source-result: INCONCLUSIVE",
        "unavailable-skill-result: SEARCH_REVIEW_OR_CREATE_AND_CONTINUE",
        f"skill-gap-checklist: {SKILL_GAP_CHECKLIST}",
        "task-instructions-precede-skill-methodology: true",
        "skill-caused-pause: cite-readable-skill-line-and-exact-instruction",
        CONTRACT_CLOSE,
    ]
    return "\n".join(lines)


def _parse_contract_body(body: str, body_digest: str) -> tuple[TaskContract | None, str]:
    lines = body.strip().splitlines()
    if len(lines) < 11:
        return None, "contract is incomplete"
    expected_prefix = [
        ("route: ", None),
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
    digest = lines[2].removeprefix("task-sha256: ")
    if route not in {"curated", "no-high-confidence-match", "user-opt-out"}:
        return None, "contract route is invalid"
    if not SHA256_RE.fullmatch(digest) or digest != body_digest:
        return None, "contract is not bound to this task prompt"

    index = 3
    skills: list[str] = []
    if lines[index] == "required-skills: []":
        index += 1
    elif lines[index] == "required-skills:":
        index += 1
        while index < len(lines):
            skill_match = SKILL_LINE_RE.fullmatch(lines[index])
            if not skill_match:
                break
            skills.append(skill_match.group(1))
            index += 1
        if not skills:
            return None, "contract skill list is empty"
    else:
        return None, "contract required-skills field is invalid"
    if len(skills) != len(set(skills)):
        return None, "contract skill list has duplicates"
    if (route == "curated") != bool(skills):
        return None, "contract route and skill list disagree"

    expected_suffix = [
        f"read-before-action: {'true' if skills else 'false'}",
        "decision-basis: source-required",
        "no-source-result: INCONCLUSIVE",
        "unavailable-skill-result: SEARCH_REVIEW_OR_CREATE_AND_CONTINUE",
        f"skill-gap-checklist: {SKILL_GAP_CHECKLIST}",
        "task-instructions-precede-skill-methodology: true",
        "skill-caused-pause: cite-readable-skill-line-and-exact-instruction",
    ]
    if lines[index:] != expected_suffix:
        return None, "contract safety fields are incomplete or reordered"
    return TaskContract(skills=skills, route=route), ""


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


def decision(task_text: str) -> tuple[bool, str]:
    contract, problem = parse_contract(task_text)
    if contract is not None:
        task_body = task_body_without_contract(task_text)
        assert task_body is not None  # established by parse_contract above
        expected = selected_skills(task_body)
        expected_route = route_for_task(task_body, expected)
        if contract.skills == expected and contract.route == expected_route:
            return True, ""
        return False, (
            "Contract skill selection does not match the curated router for this "
            "task. Re-render it from the exact child prompt:\n"
            + render_contract(task_body, expected)
        )
    clean_task = task_body_without_contract(task_text)
    if clean_task is None:
        clean_task = task_text
    skills = selected_skills(clean_task)
    repair = render_contract(clean_task, skills)
    return False, (
        "Every delegated task needs one complete task-bound skill/evidence contract "
        f"({problem}). Render it before dispatch; append it when missing or replace "
        f"the stale/invalid contract:\n{repair}"
    )


def cli(task_text: str, as_json: bool) -> int:
    skills = selected_skills(task_text)
    payload = {
        "task": task_text,
        "selected_skills": skills,
        "contract": render_contract(task_text, skills),
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
    args = parser.parse_args(argv)
    if args.task is not None:
        return cli(args.task, args.json)

    event = read_event()
    if event.get("tool_name") != "Task":
        allow()
    task_text = task_text_from_event(event)
    permitted, reason = decision(task_text)
    if permitted:
        log("INFO", "agent-skill-contract", "allow", "valid-task-contract", task_text)
        allow()
    log("WARN", "agent-skill-contract", "block", "missing-or-invalid-contract", task_text)
    block(reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
