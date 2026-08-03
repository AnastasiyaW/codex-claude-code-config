#!/usr/bin/env python3
"""Audit skill metadata, live hook wiring, and curated route targets.

The semantic skill loader is owned by the agent client. This audit verifies the
boundary around it: skills are discoverable and have usable frontmatter, every
configured hook command resolves, the UserPromptSubmit router is wired, and its
curated skill routes point at skills that are actually available.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path

from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
# One parser for this format -- see skill_frontmatter for why two modes exist.
from skill_frontmatter import value as frontmatter_value  # noqa: E402


FRONTMATTER_RE = re.compile(
    r"\A\ufeff?---[ \t]*\r?\n(?P<body>.*?)\r?\n---[ \t]*\r?\n",
    re.DOTALL,
)
# A hook command may run any interpreter, not only Python. Matching .py alone
# reported a real, wired .js hook as a missing target and failed the whole audit
# on a false positive -- the loud-gate failure, in a validator.
HOOK_EXTENSIONS = r"(?:py|js|mjs|cjs|ts|ps1|sh|cmd|bat|exe)"
HOOK_PATH_RE = re.compile(
    rf"(?:[\"']([^\"']+\.{HOOK_EXTENSIONS})[\"']|((?:[A-Za-z]:[\\/]|/)[^\s\"']+\.{HOOK_EXTENSIONS}))",
    re.IGNORECASE,
)



def skill_metadata(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = FRONTMATTER_RE.match(text)
    if not match:
        return "", ""
    body = match.group("body")
    return frontmatter_value(body, "name"), frontmatter_value(body, "description")


def implicit_enabled(skill_md: Path) -> bool:
    """Return the Codex default: true unless openai.yaml explicitly disables it."""
    config = skill_md.parent / "agents" / "openai.yaml"
    if not config.is_file():
        return True
    text = config.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"(?m)^\s*allow_implicit_invocation:\s*(true|false)\s*$", text, re.I)
    return not match or match.group(1).lower() == "true"


def scan_skills(root: Path) -> dict[str, Any]:
    files = sorted(root.rglob("SKILL.md")) if root.is_dir() else []
    invalid: list[str] = []
    names: dict[str, list[str]] = {}
    implicit_disabled: list[str] = []
    for path in files:
        name, description = skill_metadata(path)
        relative = path.relative_to(root).as_posix()
        if not name or not description:
            invalid.append(relative)
        if name:
            names.setdefault(name, []).append(relative)
        if not implicit_enabled(path):
            implicit_disabled.append(relative)
    duplicates = {
        name: paths for name, paths in sorted(names.items()) if len(paths) > 1
    }
    return {
        "root": str(root),
        "root_exists": root.is_dir(),
        "files": len(files),
        "names": sorted(names),
        "invalid_metadata": invalid,
        "duplicate_names": duplicates,
        "implicit_disabled": implicit_disabled,
    }


def hook_rows(config_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not config_path.is_file():
        return [], [f"missing hook config: {config_path}"]
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], [f"invalid hook config {config_path}: {exc}"]

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    hooks = config.get("hooks", {})
    if not isinstance(hooks, dict):
        return [], ["hook config has no object-valued 'hooks' field"]
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            errors.append(f"{event}: groups are not a list")
            continue
        for group_index, group in enumerate(groups, start=1):
            if not isinstance(group, dict):
                errors.append(f"{event}[{group_index}]: group is not an object")
                continue
            for hook_index, hook in enumerate(group.get("hooks", []), start=1):
                if not isinstance(hook, dict):
                    errors.append(f"{event}[{group_index}][{hook_index}]: hook is not an object")
                    continue
                command = str(hook.get("command") or "")
                match = HOOK_PATH_RE.search(command)
                target_raw = (match.group(1) or match.group(2)) if match else None
                target = Path(target_raw) if target_raw else None
                if target is not None and not target.is_absolute():
                    target = config_path.parent / target
                if target is None:
                    errors.append(f"{event}[{group_index}][{hook_index}]: no supported hook target")
                elif not target.is_file():
                    errors.append(f"{event}[{group_index}][{hook_index}]: missing target {target}")
                rows.append(
                    {
                        "event": event,
                        "command": command,
                        "target": str(target) if target else None,
                        "exists": bool(target and target.is_file()),
                    }
                )
    return rows, errors


def load_router_targets(router_path: Path) -> tuple[int, list[str], list[str], set[str]]:
    if not router_path.is_file():
        return 0, [], [f"missing skill router: {router_path}"], set()
    spec = importlib.util.spec_from_file_location("skill_router_under_audit", router_path)
    if spec is None or spec.loader is None:
        return 0, [], [f"cannot import skill router: {router_path}"], set()
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - reports the live import failure
        return 0, [], [f"skill router import failed: {exc}"], set()
    routes = getattr(module, "ROUTES", [])
    if not isinstance(routes, list):
        return 0, [], ["skill router ROUTES is not a list"], set()
    targets = sorted({route["skill"] for route in routes if isinstance(route, dict) and route.get("skill")})
    local_only = getattr(module, "LOCAL_ONLY_SKILLS", set())
    if not isinstance(local_only, (set, frozenset, list, tuple)):
        local_only = set()
    return len(routes), targets, [], set(local_only)


def audit(
    *,
    active_skills_root: Path,
    source_skills_root: Path,
    hooks_config: Path,
    router_path: Path,
) -> dict[str, Any]:
    active = scan_skills(active_skills_root)
    source = scan_skills(source_skills_root)
    rows, hook_errors = hook_rows(hooks_config)
    route_count, route_targets, router_errors, local_only = load_router_targets(router_path)
    available = set(active["names"]) | set(source["names"])
    # A "plugin:skill" target is provided by an installed plugin, not by this
    # repository, so its absence is a local install choice rather than broken
    # wiring. Report it separately instead of failing the audit for everyone who
    # has not installed that plugin.
    unresolved = set(route_targets) - available
    plugin_routes = sorted(t for t in unresolved if ":" in t or t in local_only)
    missing_routes = sorted(t for t in unresolved if ":" not in t and t not in local_only)
    user_prompt_router = [
        row for row in rows if row["event"] == "UserPromptSubmit" and "keyword-skill-router" in row["command"]
    ]
    checks = {
        "active_skill_root_exists": active["root_exists"],
        "source_skill_metadata_valid": bool(source["root_exists"] and not source["invalid_metadata"]),
        "active_skill_metadata_valid": bool(active["root_exists"] and not active["invalid_metadata"]),
        "all_hook_targets_exist": not hook_errors,
        "skill_router_wired": len(user_prompt_router) == 1 and user_prompt_router[0]["exists"],
        "curated_route_targets_available": not missing_routes and not router_errors,
    }
    return {
        "skills": {"active": active, "source": source},
        "hooks": {
            "config": str(hooks_config),
            "configured": len(rows),
            "events": dict(Counter(row["event"] for row in rows)),
            "user_prompt_skill_router_count": len(user_prompt_router),
            "errors": hook_errors,
        },
        "router": {
            "path": str(router_path),
            "routes": route_count,
            "skill_targets": route_targets,
            "missing_skill_targets": missing_routes,
            "plugin_provided_targets_not_installed": plugin_routes,
            "errors": router_errors,
        },
        "checks": checks,
        "failures": [name for name, passed in checks.items() if not passed],
        "warnings": {
            "active_duplicate_skill_names": active["duplicate_names"],
            "implicit_disabled_active_skills": active["implicit_disabled"],
        },
    }


def print_human(report: dict[str, Any]) -> None:
    active = report["skills"]["active"]
    source = report["skills"]["source"]
    hooks = report["hooks"]
    router = report["router"]
    print(f"[skill-hook-audit] active skills: {active['files']} · source skills: {source['files']}")
    print(f"[skill-hook-audit] hooks: {hooks['configured']} · UserPromptSubmit routers: {hooks['user_prompt_skill_router_count']}")
    print(f"[skill-hook-audit] curated routes: {router['routes']} · skill targets: {len(router['skill_targets'])}")
    for failure in report["failures"]:
        print(f"[skill-hook-audit] FAIL: {failure}")
    for error in hooks["errors"] + router["errors"]:
        print(f"[skill-hook-audit] ERROR: {error}")
    if router["missing_skill_targets"]:
        print(f"[skill-hook-audit] ERROR: unavailable route targets: {', '.join(router['missing_skill_targets'])}")
    duplicate_count = len(report["warnings"]["active_duplicate_skill_names"])
    if duplicate_count:
        print(f"[skill-hook-audit] WARN: {duplicate_count} duplicate active skill names (nested plugin copies)")
    print(
        "[skill-hook-audit] " + ("PASS" if not report["failures"] else "FAIL")
    )


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # This audit is Codex-oriented -- see --hooks-config below. Its skills root must be
    # the Codex skills root, or the pair describes two different harnesses and the report
    # is about neither. It defaulted to ~/.agents/skills, which Codex does not read at all,
    # so "active skills: 0" was reported as a finding rather than as a wrong root.
    # Point it at a Claude tree explicitly to audit Claude Code instead.
    parser.add_argument("--active-skills-root", type=Path, default=Path.home() / ".codex" / "skills")
    parser.add_argument("--source-skills-root", type=Path, default=repo_root / "skills")
    parser.add_argument("--hooks-config", type=Path, default=Path.home() / ".codex" / "hooks.json")
    parser.add_argument("--router", type=Path, default=repo_root / "hooks" / "keyword-skill-router.py")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--strict", action="store_true", help="return 1 when a hard check fails")
    args = parser.parse_args(argv)
    report = audit(
        active_skills_root=args.active_skills_root,
        source_skills_root=args.source_skills_root,
        hooks_config=args.hooks_config,
        router_path=args.router,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_human(report)
    return 1 if args.strict and report["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
