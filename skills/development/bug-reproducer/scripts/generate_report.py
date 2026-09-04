#!/usr/bin/env python3
"""Generate a native Markdown Bug Reproducer report from evidence and context JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


STATUS_META = {
    "FIX_PROVEN": ("✅", "Bug reproduced and fix proven"),
    "REPRODUCED": ("🔴", "Bug reproduced"),
    "NOT_REPRODUCED": ("⚪", "Bug not reproduced"),
    "NO_BUG_PROVEN": ("⚪", "No candidate bug was proven"),
    "INCONCLUSIVE": ("⚠️", "Evidence inconclusive"),
    "STILL_FAILING": ("❌", "Bug still failing"),
    "FIX_UNVERIFIED": ("⚠️", "Fix not fully verified"),
    "FIX_REGRESSION": ("❌", "Fix introduced or exposed regressions"),
}


def load_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected an object in {path}")
    return data


def text(value: Any, fallback: str = "Not supplied") -> str:
    rendered = str(value if value not in (None, "") else fallback)
    return rendered.replace("\r", " ").replace("\n", " ").strip()


def cell(value: Any) -> str:
    return text(value).replace("|", "\\|").replace("`", "\\`")


def number(value: Any) -> str:
    try:
        return f"{float(value):,.3f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "—"


def command_string(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(part) for part in value)
    return text(value, "Command unavailable")


def output_excerpt(run: dict[str, Any]) -> str:
    raw = str(run.get("stderr") or run.get("stdout") or "No output captured.")
    return raw.replace("`", "ˋ").strip()[:6000]


def file_link(item: dict[str, Any]) -> str:
    path = text(item.get("path"), "Unknown file")
    try:
        line = max(1, int(item.get("line", 1)))
    except (TypeError, ValueError):
        line = 1
    target = f"{path}:{line}"
    if " " in target:
        target = f"<{target}>"
    return f"- [{Path(path).name}]({target}) — {text(item.get('summary'), 'Changed')}"


def file_lines(value: Any, fallback: str) -> list[str]:
    if not isinstance(value, list):
        return [f"- {fallback}"]
    lines = [file_link(item) for item in value if isinstance(item, dict)]
    return lines or [f"- {fallback}"]


def bullets(value: Any, fallback: str) -> list[str]:
    if not isinstance(value, list) or not value:
        return [f"- {fallback}"]
    return [f"- {text(item)}" for item in value]


def check_rows(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["| Checks | ⚠️ unknown | No checks supplied |"]
    rows = []
    for item in value:
        if not isinstance(item, dict):
            continue
        status = text(item.get("status"), "unknown").lower()
        icon = "✅" if status == "passed" else "❌" if status == "failed" else "⚠️"
        rows.append(
            f"| {cell(item.get('name'))} | {icon} {cell(status)} | {cell(item.get('detail'))} |"
        )
    return rows or ["| Checks | ⚠️ unknown | No checks supplied |"]


def candidate_rows(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    rows = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        rows.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    cell(item.get("candidate")),
                    cell(item.get("contract")),
                    cell(item.get("trigger")),
                    cell(item.get("location")),
                    cell(item.get("confidence")),
                    cell(item.get("outcome")),
                ]
            )
            + " |"
        )
    return rows


def build_report(evidence: dict[str, Any], context: dict[str, Any]) -> str:
    status = text(evidence.get("status"), "INCONCLUSIVE").upper()
    icon, headline = STATUS_META.get(status, ("⚠️", "Evidence status unavailable"))
    before = evidence.get("before") if isinstance(evidence.get("before"), dict) else {}
    after = evidence.get("after") if isinstance(evidence.get("after"), dict) else {}
    reproduce_commands = context.get("reproduce") if isinstance(context.get("reproduce"), list) else []
    command_blocks = [f"```bash\n{text(command)}\n```" for command in reproduce_commands]
    if not command_blocks:
        command_blocks = [f"```bash\n{command_string(before.get('command'))}\n```"]

    candidates = candidate_rows(context.get("candidates"))
    discovery_scope = bullets(context.get("discovery_scope"), "Scope not supplied.")
    discovery_section = []
    if candidates or context.get("mode") == "hunt-and-prove":
        discovery_section = [
            "## Discovery scope",
            "",
            *discovery_scope,
            "",
            "## Ranked and tested candidates",
            "",
            "| # | Candidate | Contract evidence | Trigger | Location | Confidence | Outcome |",
            "|---:|---|---|---|---|---|---|",
            *(candidates or ["| — | No testable candidate | — | — | — | — | NO_BUG_PROVEN |"]),
            "",
        ]

    lines = [
        "# Bug Reproducer",
        "",
        f"## {icon} {status} — {headline}",
        "",
        f"> {text(evidence.get('reason'))}",
        "",
        f"**Project:** {text(context.get('project'))}  ",
        f"**Bug:** {text(context.get('title'))}  ",
        f"**Environment:** {text(context.get('environment'))}  ",
        f"**Generated:** {text(context.get('generated_at'))}",
        "",
        *discovery_section,
        "## Original report",
        "",
        text(context.get("original_report")),
        "",
        "| Contract | Expected | Actual |",
        "|---|---|---|",
        f"| Observed behavior | {cell(context.get('expected'))} | {cell(context.get('actual'))} |",
        "",
        "## Minimal reproduction",
        "",
        text(context.get("reproduction")),
        "",
        f"**Confirming signal:** {text(context.get('failure_signal'))}",
        "",
        "### Reproduction files approved at Gate 1",
        "",
        *file_lines(context.get("reproduction_files"), "No reproduction files listed."),
        "",
        "## Red to green evidence",
        "",
        "| Evidence | Before fix | After fix |",
        "|---|---:|---:|",
        f"| Exit code | {cell(before.get('exit_code'))} | {cell(after.get('exit_code'))} |",
        f"| Timed out | {cell(before.get('timed_out'))} | {cell(after.get('timed_out'))} |",
        f"| Duration | {number(before.get('duration_ms'))} ms | {number(after.get('duration_ms'))} ms |",
        f"| Same command | — | {cell(evidence.get('same_command'))} |",
        f"| Broader suite | — | {cell(evidence.get('full_suite'))} |",
        "",
        "### Before — failing evidence",
        "",
        "```text",
        output_excerpt(before),
        "```",
        "",
        "### After — fixed evidence",
        "",
        "```text",
        output_excerpt(after),
        "```",
        "",
        "## Root cause",
        "",
        text(context.get("root_cause")),
        "",
        "## Approved fix",
        "",
        text(context.get("fix_summary")),
        "",
        f"**Why this is causal:** {text(context.get('why_causal'))}",
        "",
        "### Production files approved at Gate 2",
        "",
        *file_lines(context.get("fix_files"), "No production files listed."),
        "",
        "## Verification",
        "",
        "| Check | Status | Evidence |",
        "|---|---|---|",
        *check_rows(context.get("checks")),
        "",
        "## Reproduce",
        "",
        *command_blocks,
        "",
        "## Limitations",
        "",
        *bullets(context.get("limitations"), "No limitations supplied."),
        "",
        "## Residual risks",
        "",
        *bullets(context.get("residual_risks"), "No residual risks supplied."),
        "",
        "## Notes",
        "",
        *bullets(context.get("notes"), "No additional notes."),
        "",
        "---",
        "",
        "Generated by `$bug-reproducer`. A fix is proven only by the same red-to-green reproducer plus relevant broader checks.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("context", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    evidence = load_object(args.evidence)
    context = load_object(args.context)
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_report(evidence, context), encoding="utf-8")
    print(f"Created report: {output}")


if __name__ == "__main__":
    main()
