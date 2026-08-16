# -*- coding: utf-8 -*-
"""SessionStart: name the hook file that will be edited but never run.

Why this exists
---------------
Two hook trees live side by side on this machine - `~/.claude/hooks` and
`~/.claude/claude-code-config/hooks` - and 39 scripts share a basename across
them. `settings.json` decides which copy actually runs, and nothing else on the
machine says so. A whole review round was spent hardening the WRONG copy of
`transfer-contract-guard.py`: twelve checks went green describing a file that is
never executed, and the shared module beside it lacked the function the fix
depended on, so the import raised and was swallowed.

No amount of testing the guards surfaces this. It is not a defect in what a hook
matches - it is a defect in WHICH FILE the matcher lives in, and the only place
that fact is written down is the manifest. So this check reads the manifest.

What it reports (advisory, never blocks)
----------------------------------------
  * SHADOW  - a registered hook has a same-named copy elsewhere whose bytes
              DIFFER. Editing the shadow is silent no-op work. This is the one
              that has already cost real time.
  * TWIN    - same name, identical bytes. Harmless today; drifts into SHADOW the
              moment anyone edits either side.
  * DEAD    - `settings.json` names a script that does not exist. The hook is
              registered and does nothing.
  * ORPHAN  - a script in a hook directory that no event registers. Not a fault
              by itself; listed so a "why did nothing fire" question has an
              answer.

Silence is the normal state: it prints only when the picture CHANGES. The stamp
holds a digest of the findings, so a fixed problem goes quiet and a new one
speaks immediately, rather than the usual time-based cooldown that hides a
regression for a week.

Fail-open by construction: any error is swallowed and the session proceeds.
Opt-out: `touch ~/.claude/.skip-hook-tree-check`.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HOME = Path.home() / ".claude"
STAMP = HOME / ".hook-tree-drift-stamp"
SKIP = HOME / ".skip-hook-tree-check"
# Every directory on this machine that holds hook scripts. A tree absent from
# this list is invisible to the check, so keep it wider than today's layout.
TREES = ("hooks", "claude-code-config/hooks", "private-hooks", "claude-code-config/scripts", "scripts")
# Only these hold hooks. The two `scripts` dirs are scanned for shadows - three
# registered entries do live there - but a utility script nobody registers is
# not a finding, and listing 110 of them buries the 19 that matter.
HOOK_TREES = ("hooks", "claude-code-config/hooks", "private-hooks")
SCRIPT_IN_COMMAND = re.compile(r"[A-Za-z0-9_./\\:$~-]+\.py")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _registered(settings: dict) -> dict[str, str]:
    """basename -> the path `settings.json` actually runs, forward-slashed."""
    commands: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "command" and isinstance(value, str):
                    commands.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(settings.get("hooks", {}))
    found: dict[str, str] = {}
    for command in commands:
        for match in SCRIPT_IN_COMMAND.finditer(command):
            path = match.group(0).replace("\\", "/")
            found[path.rsplit("/", 1)[-1]] = path
    return found


def _resolve(path: str, home: Path) -> Path:
    text = path.replace("$CLAUDE_CONFIG_DIR", str(home)).replace("~", str(Path.home()))
    return Path(text)


def survey(home: Path) -> list[tuple[str, str]]:
    """Return (kind, message) findings. Pure, so the self-test can drive it."""
    settings_path = home / "settings.json"
    if not settings_path.exists():
        return []
    registered = _registered(json.loads(settings_path.read_text(encoding="utf-8")))
    present: dict[str, list[Path]] = {}
    for tree in TREES:
        directory = home / tree
        if not directory.is_dir():
            continue
        for script in directory.glob("*.py"):
            present.setdefault(script.name, []).append(script)

    findings: list[tuple[str, str]] = []
    for name, declared in sorted(registered.items()):
        target = _resolve(declared, home)
        if not target.exists():
            findings.append(("DEAD", f"{name}: registered as {declared}, which does not exist"))
            continue
        try:
            live = _digest(target)
        except OSError:
            continue
        for other in present.get(name, []):
            try:
                if other.resolve() == target.resolve():
                    continue
                same = _digest(other) == live
            except OSError:
                continue
            where = str(other).replace("\\", "/")
            findings.append((
                "TWIN" if same else "SHADOW",
                f"{name}: runs from {declared}"
                + (f", identical copy at {where}" if same
                   else f", but a DIFFERENT copy sits at {where}"),
            ))
    hook_dirs = {(home / tree).resolve() for tree in HOOK_TREES}
    for name, copies in sorted(present.items()):
        if name in registered or name.startswith("_") or name == "safety_common.py":
            continue
        if any(part in ("tests", "__pycache__") for copy in copies for part in copy.parts):
            continue
        if not any(copy.parent.resolve() in hook_dirs for copy in copies):
            continue
        findings.append(("ORPHAN", f"{name}: present in {len(copies)} tree(s), registered by no event"))
    return findings


def _report(findings: list[tuple[str, str]]) -> str:
    shadows = [m for kind, m in findings if kind == "SHADOW"]
    dead = [m for kind, m in findings if kind == "DEAD"]
    twins = [m for kind, m in findings if kind == "TWIN"]
    orphans = [m for kind, m in findings if kind == "ORPHAN"]
    lines = ["[hook-tree] the manifest and the files on disk disagree:"]
    if shadows:
        lines.append(f"  {len(shadows)} SHADOW - editing this copy is a silent no-op:")
        lines.extend(f"    {m}" for m in shadows[:6])
        if len(shadows) > 6:
            lines.append(f"    ... and {len(shadows) - 6} more")
    if dead:
        lines.append(f"  {len(dead)} DEAD registration(s):")
        lines.extend(f"    {m}" for m in dead[:4])
    if twins:
        lines.append(f"  {len(twins)} identical twin(s) - harmless until someone edits one side")
    if orphans:
        lines.append(f"  {len(orphans)} script(s) registered by no event")
    lines.append("  Fix the SHADOW ones by editing the path settings.json names, not the basename.")
    return "\n".join(lines)


def main() -> None:
    try:
        sys.stdin.read()
    except Exception:
        pass
    try:
        if SKIP.exists():
            return
        findings = survey(HOME)
        if not findings:
            if STAMP.exists():
                STAMP.unlink(missing_ok=True)
            return
        digest = hashlib.sha256("\n".join(sorted(m for _, m in findings)).encode()).hexdigest()
        if STAMP.exists() and STAMP.read_text(encoding="utf-8").strip() == digest:
            return                       # same picture as last time: stay quiet
        STAMP.write_text(digest, encoding="utf-8")
        print(_report(findings))
    except Exception:
        # Advisory only. A bug here must never cost a session its start.
        return


def _self_test() -> int:
    """Build a real temp tree with a real settings.json and drive `survey`."""
    import tempfile

    fails: list[str] = []
    with tempfile.TemporaryDirectory() as raw:
        home = Path(raw)
        live = home / "claude-code-config" / "hooks"
        old = home / "hooks"
        live.mkdir(parents=True)
        old.mkdir(parents=True)
        (live / "guard.py").write_text("print('new')\n", encoding="utf-8")
        (old / "guard.py").write_text("print('OLD - never runs')\n", encoding="utf-8")
        (live / "same.py").write_text("print('x')\n", encoding="utf-8")
        (old / "same.py").write_text("print('x')\n", encoding="utf-8")
        (old / "nobody-calls-me.py").write_text("print('orphan')\n", encoding="utf-8")
        settings = {"hooks": {"PreToolUse": [{"hooks": [
            {"type": "command", "command": f"python {live / 'guard.py'}"},
            {"type": "command", "command": f"python {live / 'same.py'}"},
            {"type": "command", "command": f"python {live / 'vanished.py'}"},
        ]}]}}
        (home / "settings.json").write_text(json.dumps(settings), encoding="utf-8")

        kinds = {kind for kind, _ in survey(home)}
        for expected in ("SHADOW", "TWIN", "DEAD", "ORPHAN"):
            if expected not in kinds:
                fails.append(f"{expected} not reported")
        shadow = [m for kind, m in survey(home) if kind == "SHADOW"]
        if not any("guard.py" in m for m in shadow):
            fails.append("the differing copy was not the one named as SHADOW")
        if any("same.py" in m for m in shadow):
            fails.append("an identical copy was reported as a SHADOW")

        # A tree with no duplicates and no dead registration must be silent.
        (old / "guard.py").unlink()
        (old / "same.py").unlink()
        (old / "nobody-calls-me.py").unlink()
        (live / "vanished.py").write_text("print('now it exists')\n", encoding="utf-8")
        if survey(home):
            fails.append(f"a clean tree was not silent: {survey(home)}")

    if fails:
        print("hook-tree-drift-check self-test FAILED:")
        for line in fails:
            print(f"  - {line}")
        return 1
    print("hook-tree-drift-check self-test: ok")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(_self_test())
    main()
