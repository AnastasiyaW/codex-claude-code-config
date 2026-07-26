#!/usr/bin/env python3
"""Stop hook: block task completion until tests are green.

Behavioural enforcement layer for the "fix or ticket" pattern. CLAUDE.md
rules can be ignored under context pressure (compliance decay; Jaroslawicz
et al. 2025). This hook works at the structural layer: it runs the project
test suite at every Stop event and blocks if anything is red. The agent
cannot say "done" while tests fail — that claim is now physically false.

Companion to stop-phrase-guard.py (phrase-level detection) and
problems-md-validator.py (PROBLEMS.md ticket discipline). Together they
implement Layer 2-4 of the no-pre-existing-evasion stack.

## Detection order

1. Project override file `.claude/test-command` (literal command, one line)
2. JS/TS via `package.json` "test" script (pnpm > yarn > bun > npm)
3. Python via `pytest.ini` / `pyproject.toml` / `tests/`
4. Rust via `Cargo.toml`
5. Go via `go.mod`

If none detected → silent pass (graceful for non-code dirs).

## Behaviour

- Returncode 0 from test command → silent pass
- Returncode != 0 → emit JSON `{"decision": "block", "reason": "..."}` with
  the tail of the test output. The agent must fix or explicitly bypass.
- `stop_hook_active=true` → silent pass (anti-loop guard, REQUIRED)
- Timeout reached → log + silent pass (don't trap user in long suites)

## Bypass

- env var `CLAUDE_SKIP_TEST_GATE=1` → silent pass
- file `.claude/.skip-test-gate` (project-level) → silent pass
- delete the marker / unset the env var to re-enable

## Register

```json
{
  "hooks": {
    "Stop": [{
      "hooks": [{
        "type": "command",
        "command": "python path/to/test-gate-stop-hook.py",
        "statusMessage": "Test gate (no-pre-existing-evasion Layer 2)..."
      }]
    }]
  }
}
```

## Tunables

- `TEST_TIMEOUT_SEC` - kill long suites (default 180s)
- `MAX_OUTPUT_BYTES` - cap injected output to keep agent context clean
- `MIN_SESSION_MINUTES` - skip on very short sessions (just opened)

## Reference

- Principle 26: docs/principles/26-no-pre-existing-evasion.md
- bradfeld "fix or ticket" pattern (5 valid exceptions)
- GitHub issue anthropics/claude-code#42796 (origin investigation)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from safety_common import (  # noqa: E402
        stop_budget_consume,
        stop_budget_exhausted,
        untrusted_block,
    )
except ImportError:  # fail-open: keep the original one-shot behaviour
    stop_budget_consume = stop_budget_exhausted = untrusted_block = None  # type: ignore[assignment]

TEST_TIMEOUT_SEC = 180
MAX_OUTPUT_BYTES = 4000
MIN_SESSION_MINUTES = 2
# Gate name for the shared Stop-hook rejection budget (safety_common).
BUDGET_NAME = "test-gate"


def detect_test_command(cwd: Path) -> tuple[list[str], str] | None:
    """Detect what test command to run. Returns (cmd_list, label) or None."""

    # Project override supports leading #-comment lines for documentation.
    # First non-comment non-empty line wins.
    override = cwd / ".claude" / "test-command"
    if override.exists() and override.is_file():
        for raw_line in override.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            # Label must NOT embed the file's contents: it is repository text
            # and the label goes into the block reason outside the untrusted
            # frame. The command itself is echoed inside that frame instead.
            return (line.split(), "override(.claude/test-command)")

    pkg_json = cwd / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
            if "test" in pkg.get("scripts", {}):
                if (cwd / "pnpm-lock.yaml").exists() and shutil.which("pnpm"):
                    return (["pnpm", "test"], "pnpm test")
                if (cwd / "yarn.lock").exists() and shutil.which("yarn"):
                    return (["yarn", "test"], "yarn test")
                if (cwd / "bun.lockb").exists() and shutil.which("bun"):
                    return (["bun", "test"], "bun test")
                if shutil.which("npm"):
                    return (["npm", "test", "--silent"], "npm test")
        except (json.JSONDecodeError, OSError):
            pass

    # Python: only conventional locations, NEVER rglob from cwd. rglob from an
    # umbrella directory (workspace with many subprojects) sweeps too widely and
    # catches CLI scripts named test_*.py that sys.exit at module load. Real bug
    # case 2026-05-04: workspace dir found face-relax-lora/scripts/test_single.py
    # and pytest exited code 3 (internal error) at collection.
    has_pytest_ini = (cwd / "pytest.ini").exists()

    pyproject = cwd / "pyproject.toml"
    has_pyproject_pytest = False
    if pyproject.exists():
        try:
            txt = pyproject.read_text(encoding="utf-8", errors="ignore")
            has_pyproject_pytest = "[tool.pytest" in txt or "pytest" in txt
        except OSError:
            pass

    def _dir_has_test_files(d: Path) -> bool:
        if not d.is_dir():
            return False
        try:
            return any(
                p.is_file() and p.suffix == ".py" and
                (p.name.startswith("test_") or p.name.endswith("_test.py"))
                for p in d.iterdir()
            )
        except OSError:
            return False

    has_tests_dir = _dir_has_test_files(cwd / "tests") or _dir_has_test_files(cwd / "test")

    if (has_pytest_ini or has_pyproject_pytest or has_tests_dir) and shutil.which("pytest"):
        return (["pytest", "--tb=short", "-q"], "pytest")

    if (cwd / "Cargo.toml").exists() and shutil.which("cargo"):
        return (["cargo", "test", "--quiet"], "cargo test")

    if (cwd / "go.mod").exists() and shutil.which("go"):
        return (["go", "test", "./..."], "go test")

    return None


def session_age_minutes(claude_dir: Path) -> float:
    marker = claude_dir / ".session-start"
    if marker.exists():
        return (time.time() - marker.stat().st_mtime) / 60
    return 999


def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        return 0

    cwd = Path.cwd()

    # Anti-loop with a budget, not a one-shot surrender: keep enforcing while
    # the gate still has rejections left, then yield so a stuck gate cannot
    # deadlock the session. See safety_common.stop_budget_*.
    if event.get("stop_hook_active"):
        if stop_budget_exhausted is None or stop_budget_exhausted(BUDGET_NAME, cwd):
            return 0

    if os.environ.get("CLAUDE_SKIP_TEST_GATE"):
        return 0

    if (cwd / ".claude" / ".skip-test-gate").exists():
        return 0

    claude_dir = cwd / ".claude"
    if claude_dir.exists() and session_age_minutes(claude_dir) < MIN_SESSION_MINUTES:
        return 0

    detected = detect_test_command(cwd)
    if detected is None:
        return 0

    cmd, label = detected

    try:
        # CI=1 forces watch-capable runners (vitest, jest, playwright) into
        # run-once non-interactive mode, preventing a watch-mode hang that would
        # otherwise sit until TEST_TIMEOUT_SEC. FORCE_COLOR=0 keeps output clean.
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            timeout=TEST_TIMEOUT_SEC,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "CI": "1", "FORCE_COLOR": "0"},
        )
    except subprocess.TimeoutExpired:
        print(f"[test-gate] {label} timeout after {TEST_TIMEOUT_SEC}s - skipping",
              file=sys.stderr)
        return 0
    except (FileNotFoundError, OSError) as e:
        print(f"[test-gate] {label} unavailable: {e}", file=sys.stderr)
        return 0

    if result.returncode == 0:
        return 0

    # pytest exit 5 = "no tests collected" - silent pass (project has scaffold but
    # no tests yet; gate auto-activates when first real test exists).
    is_pytest = label.startswith("pytest") or "pytest" in label
    if is_pytest and result.returncode == 5:
        return 0

    output = (result.stdout or "") + "\n" + (result.stderr or "")
    if len(output) > MAX_OUTPUT_BYTES:
        output = output[-MAX_OUTPUT_BYTES:]

    # The runner's stdout goes into the model's context. Frame it as data so a
    # repository cannot smuggle instructions in through a failing test.
    # The command line is repository-controlled too (.claude/test-command,
    # package.json scripts), so it goes inside the frame with the output.
    payload = f"$ {' '.join(cmd)}\n\n{output}"
    if untrusted_block is not None:
        framed = untrusted_block(payload, f"{label} command + stdout/stderr, tail {MAX_OUTPUT_BYTES} bytes")
    else:
        framed = f"Output (tail {MAX_OUTPUT_BYTES} bytes):\n{payload}"

    if stop_budget_consume is not None:
        stop_budget_consume(BUDGET_NAME, cwd)

    reason = (
        f"Test gate failed ({label}, exit {result.returncode}). "
        f"Cannot complete task while tests are red. "
        f"Per no-pre-existing-evasion rule: tests must be green before 'done'.\n\n"
        f"{framed}\n\n"
        f"Options:\n"
        f"1. Fix the failures (preferred)\n"
        f"2. If failures are in genuinely unfixable area: add to PROBLEMS.md "
        f"with one of 5-exception reasons (missing-data, missing-dep, "
        f"arch-decision, scope-explosion, inaccessible-repo) and create "
        f".claude/.skip-test-gate for this session\n"
        f"3. Bypass: CLAUDE_SKIP_TEST_GATE=1 (only for emergency)"
    )

    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
