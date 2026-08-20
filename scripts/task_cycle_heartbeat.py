#!/usr/bin/env python3
"""Advance explicit task-cycle work orders at every scheduled heartbeat.

This is deliberately a dispatcher, not another evaluator: it scans only the
immediate task directories that already contain a structured ``findings.json``.
For each one it invokes the controller's two required steps, ``reconcile`` and
``next``, and persists the exact decisions. A caller must execute only the
returned ``WORK`` proof or ``RECHECK_EXTERNAL`` action; this script never
guesses an action from prose and never marks a proof complete.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTROLLER = ROOT / "hooks" / "task-cycle-controller.py"
REPORT_NAME = "task-cycle-heartbeat.json"
SCHEMA = "task-cycle-heartbeat/v1"
ACTIONABLE = {"WORK", "RECHECK_EXTERNAL"}


class HeartbeatError(RuntimeError):
    pass


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_controller(controller: Path, command: str, task_dir: Path) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(controller), command, "--task-dir", str(task_dir), "--json"],
        text=True,
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise HeartbeatError(f"{task_dir.name}: controller {command} failed: {detail}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise HeartbeatError(f"{task_dir.name}: controller {command} returned non-JSON output") from exc
    if not isinstance(payload, dict):
        raise HeartbeatError(f"{task_dir.name}: controller {command} returned non-object JSON")
    return payload


def task_directories(tasks_root: Path) -> list[Path]:
    if not tasks_root.is_dir():
        raise HeartbeatError(f"tasks root does not exist: {tasks_root}")
    return sorted(
        (child for child in tasks_root.iterdir()
         if child.is_dir() and not child.is_symlink() and (child / "findings.json").is_file()),
        key=lambda child: child.name,
    )


def write_atomic(path: Path, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    temporary.replace(path)


def heartbeat(tasks_root: Path, controller: Path) -> dict[str, Any]:
    if not controller.is_file():
        raise HeartbeatError(f"controller does not exist: {controller}")

    rows: list[dict[str, Any]] = []
    for task_dir in task_directories(tasks_root):
        reconciled = run_controller(controller, "reconcile", task_dir)
        decision = run_controller(controller, "next", task_dir)
        rows.append({
            "task_dir": task_dir.name,
            "reconciled": reconciled,
            "decision": decision,
        })

    next_row = next((row for row in rows if row["decision"].get("decision") in ACTIONABLE), None)
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "checked_at": now_utc(),
        "tasks": rows,
        "next": None if next_row is None else {
            "task_dir": next_row["task_dir"],
            "decision": next_row["decision"],
        },
    }
    write_atomic(tasks_root / REPORT_NAME, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks-root", type=Path, required=True)
    parser.add_argument("--controller", type=Path, default=DEFAULT_CONTROLLER)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = heartbeat(args.tasks_root.resolve(), args.controller.resolve())
    except HeartbeatError as exc:
        print(f"task-cycle-heartbeat: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    elif report["next"] is None:
        print("DECISION: NO_ACTIONABLE_TASK")
    else:
        next_item = report["next"]
        decision = next_item["decision"]
        print(f"DECISION: {decision['decision']}")
        print(f"task_dir: {next_item['task_dir']}")
        print(f"finding_id: {decision.get('finding_id', '')}")
        print(f"next_action: {decision.get('next_action', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
