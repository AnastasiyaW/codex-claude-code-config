#!/usr/bin/env python3
"""SessionStart: report reclaimable development artifacts when a disk is tight,
and expired entries of the shared temp registry (``temp_registry.py``) at most daily.

This is advisory, never deletes anything, and fails open.  Claude and Codex use
the same project stamp so opening both clients does not produce duplicate nags.

Disable with ``AGENT_SKIP_DISK_ADVISOR=1`` (the older client-specific aliases
remain accepted) or ``.claude/.skip-disk-advisor`` in the project.  Verify with
``python disk-pressure-advisor.py --self-test``.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


FREE_PCT_THRESHOLD = float(
    os.environ.get("AGENT_DISK_FREE_PCT", os.environ.get("CLAUDE_DISK_FREE_PCT", "15"))
)
NAG_COOLDOWN_SEC = 3 * 24 * 3600
# The hook can run from an isolated Git worktree during review, while the shared
# safety-backed sweeper remains a machine-global executable.
SWEEPER = Path.home() / ".claude" / "scripts" / "dev_artifact_sweep.py"
SKIP_ENV_VARS = (
    "AGENT_SKIP_DISK_ADVISOR",
    "CLAUDE_SKIP_DISK_ADVISOR",
    "CODEX_SKIP_DISK_ADVISOR",
)


def free_pct(path: Path) -> float | None:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    if not usage.total:
        return None
    return 100.0 * usage.free / usage.total


def reclaimable_gb(root: Path) -> float | None:
    """Run the shared sweeper in dry-run mode and parse its observed total."""
    if not SWEEPER.is_file():
        return None
    try:
        proc = subprocess.run(
            [sys.executable, str(SWEEPER), str(root), "--min-age-days", "7"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    for line in reversed((proc.stdout or "").splitlines()):
        if "GB" in line and "объектов" in line:
            try:
                return float(line.rsplit(",", 1)[1].strip().split()[0])
            except (IndexError, ValueError):
                return None
    return None


def nagged_recently(stamp: Path, cooldown: float = NAG_COOLDOWN_SEC) -> bool:
    try:
        return (time.time() - stamp.stat().st_mtime) < cooldown
    except OSError:
        return False


def advise(cwd: Path) -> str | None:
    if any(os.environ.get(name, "").strip() for name in SKIP_ENV_VARS):
        return None
    stamp = cwd / ".claude" / ".skip-disk-advisor"
    if stamp.exists():
        return None
    nag = cwd / ".claude" / ".disk-advised"
    if nagged_recently(nag):
        return None

    pct = free_pct(cwd)
    if pct is None or pct >= FREE_PCT_THRESHOLD:
        return None

    gb = reclaimable_gb(cwd)
    lines = [f"[disk] свободно {pct:.1f}% на диске этого проекта."]
    if gb and gb >= 0.5:
        lines.append(
            f"[disk] регенерируемого мусора здесь на {gb:.2f} GB "
            "(__pycache__, build, dist, *.pyc, старше 7 дней)."
        )
        lines.append(
            "[disk] показать: python ~/.claude/scripts/dev_artifact_sweep.py . "
            "| удалить: тот же вызов с --apply | канон: ~/.claude/scripts/DISK-HYGIENE.md"
        )
    else:
        lines.append(
            "[disk] артефакты разработки тут ни при чём — место занято чем-то другим "
            "(датасеты, веса, docker). Уборщик его не тронет."
        )
    try:
        nag.parent.mkdir(parents=True, exist_ok=True)
        nag.touch()
    except OSError:
        pass
    return "\n".join(lines)


REGISTRY_TOOL = Path.home() / ".claude" / "scripts" / "temp_registry.py"
REGISTRY_STAMP = Path.home() / ".claude" / "state" / ".temp-registry-advised"
REGISTRY_COOLDOWN_SEC = 24 * 3600


def registry_notice() -> str | None:
    """Expired entries of the shared temp registry, independent of disk pressure."""
    if not REGISTRY_TOOL.is_file() or nagged_recently(REGISTRY_STAMP, REGISTRY_COOLDOWN_SEC):
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("temp_registry", REGISTRY_TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    count = module.expired_count()
    if not count:
        return None
    try:
        REGISTRY_STAMP.parent.mkdir(parents=True, exist_ok=True)
        REGISTRY_STAMP.touch()
    except OSError:
        pass
    return (f"[temp-registry] просрочено временного: {count}. Показать список и id пачки: "
            "python ~/.claude/scripts/temp_registry.py clean | канон: ~/.claude/scripts/DISK-HYGIENE.md")


def self_test() -> int:
    import tempfile

    failures: list[str] = []
    if not SWEEPER.is_file():
        failures.append(f"shared sweeper not found at {SWEEPER}")
    with tempfile.TemporaryDirectory(prefix="disk-pressure-advisor-") as tmp:
        root = Path(tmp)
        (root / ".claude").mkdir()
        (root / ".claude" / ".skip-disk-advisor").touch()
        if advise(root) is not None:
            failures.append("project skip marker did not silence the advisor")
        (root / ".claude" / ".skip-disk-advisor").unlink()

        global FREE_PCT_THRESHOLD
        saved = FREE_PCT_THRESHOLD
        FREE_PCT_THRESHOLD = 0.0
        if advise(root) is not None:
            failures.append("advisor fired with a zero-percent threshold")
        FREE_PCT_THRESHOLD = 100.0
        (root / ".claude" / ".disk-advised").unlink(missing_ok=True)
        if advise(root) is None:
            failures.append("advisor did not fire with a 100-percent threshold")
        if advise(root) is not None:
            failures.append("cooldown did not suppress an immediate second advisory")
        FREE_PCT_THRESHOLD = saved

    if failures:
        for failure in failures:
            print("self-test:", failure)
        return 1
    print("self-test passed: sweeper path, skip, threshold, live gate, cooldown")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
        cwd = Path(event.get("cwd") or os.getcwd())
        message = advise(cwd)
        if message:
            print(message)
    except Exception:
        # A broken advisory must never block the actual session.
        pass
    try:
        if not any(os.environ.get(name, "").strip() for name in SKIP_ENV_VARS):
            notice = registry_notice()
            if notice:
                print(notice)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
