#!/usr/bin/env python3
"""Stop hook: block task completion until selected tests are green.

Behavioural enforcement layer for the "fix or ticket" pattern. CLAUDE.md
rules can be ignored under context pressure. This hook works at the structural
layer: it runs a fast/default suite only when Git-visible source or test files
changed, and adds an integration command for high-risk changes when the project
declares one. The agent cannot say "done" while selected tests fail.

Candidate-state contract: focused checks may repeat during iteration; an independent
review is required for high-risk boundaries; the full/candidate matrix and any
specialized environment proof are explicit candidate steps, not automatic tests
after every edit. Candidate-bound evidence must target an immutable commit or
artifact identity; a changed candidate invalidates it.

Companion to stop-phrase-guard.py (phrase-level detection) and
problems-md-validator.py (PROBLEMS.md ticket discipline). Together they
implement Layer 2-4 of the no-pre-existing-evasion stack.

## Detection order

1. Project override file `.claude/test-command` (literal command, one line)
2. JS/TS via `package.json` "test" script (pnpm > yarn > bun > npm)
3. Python via `pytest.ini` / `pyproject.toml` / `tests/`
4. Rust via `Cargo.toml`
5. Go via `go.mod`

If `.claude/test-policy.json` exists, its tokenized `fast` command is preferred;
`integration` is added for high-risk changes. `release` is intentionally not
automatic, so a large candidate matrix does not become a per-edit tax. A
project workflow owns the one full-matrix run at its candidate boundary and any
specialized environment proof that its acceptance criteria actually require.

If none detected → silent pass (graceful for non-code dirs).

## Behaviour

- Returncode 0 from test command → silent pass
- Returncode != 0 → emit JSON `{"decision": "block", "reason": "..."}` with
  the tail of the test output. The agent must fix or explicitly bypass.
- `stop_hook_active=true` → silent pass (anti-loop guard, REQUIRED)
- Timeout reached → block with an explicit unproven-evidence reason. Scope the
  automatic command in `.claude/test-policy.json` instead of silently claiming
  completion.

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
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
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
TEST_TIMEOUT_MIN_SEC = 30
TEST_TIMEOUT_MAX_SEC = 1800
MAX_OUTPUT_BYTES = 4000
MIN_SESSION_MINUTES = 2
# Gate name for the shared Stop-hook rejection budget (safety_common).
BUDGET_NAME = "test-gate"

CODE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cxx", ".cs", ".go", ".h", ".hpp", ".java",
    ".js", ".jsx", ".json", ".kt", ".m", ".mm", ".mjs", ".py", ".pyi",
    ".ps1", ".rs", ".sh", ".sql", ".swift", ".ts", ".tsx", ".vue",
}
TEST_MARKERS = ("test", "tests", "spec", "specs", "__tests__")
HIGH_RISK_MARKERS = (
    "auth", "credential", "permission", "security", "migration", "migrate",
    "schema", "database", "db", "transaction", "concurr", "thread", "async",
    "lock", "deploy", "release", "workflow", "api", "contract",
)
IGNORED_PATH_PARTS = {".git", "node_modules", "dist", "build", ".venv", "__pycache__"}
IGNORED_CONFIG_PATHS = {".claude/test-policy.json", ".claude/test-command"}

# Verification depth, on the scope this hook already computes.
#
# `high-risk` used to mean only "also run the integration suite". More tests of the same
# kind is not a deeper check -- a suite that never exercised the boundary you moved
# passes just as green after you move it. DevRails-26 tiers verification depth T0..T3 and
# demands an independent pass at the top; the idea is right and the part we lacked is the
# INDEPENDENCE, not more of our own tests.
#
# So a high-risk change must also carry one recorded independent review. Evidence is keyed
# to a hash of the changed paths, so it cannot be earned once and coasted on: move a
# different boundary and the old evidence stops counting. Same reason a repeat that never
# pins its input proves nothing about the run you are actually in.
#
# Deliberately NOT a second classifier. An earlier draft of this derived its own T0..T3
# from the same paths, which would have put two competing definitions of "risky here" in
# one repo -- the duplication class this codebase spent a day removing.
EVIDENCE_PATH = Path(os.environ.get(
    "CLAUDE_REVIEW_EVIDENCE",
    str(Path.home() / ".claude" / "state" / "review-evidence.jsonl")))


def surface_key(paths: list[str]) -> str:
    import hashlib
    normalized = sorted(p.replace("\\", "/") for p in paths)
    return hashlib.sha1("\n".join(normalized).encode()).hexdigest()[:12]


def record_review(note: str, paths: list[str]) -> str:
    key = surface_key(paths)
    try:
        EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with EVIDENCE_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.time(), "surface": key, "note": note},
                                ensure_ascii=False) + "\n")
    except OSError:
        pass
    return key


def reviews_for(paths: list[str]) -> list[str]:
    key = surface_key(paths)
    try:
        rows = [json.loads(l) for l in
                EVIDENCE_PATH.read_text(encoding="utf-8-sig").splitlines() if l.strip()]
    except (OSError, ValueError):
        return []
    return [r.get("note", "") for r in rows if r.get("surface") == key]


@dataclass(frozen=True)
class ChangeScope:
    name: str
    reason: str
    should_run: bool


def _is_test_path(path: str) -> bool:
    parts = {part.lower() for part in Path(path).parts}
    lowered = path.lower()
    return bool(parts & set(TEST_MARKERS)) or any(
        lowered.endswith(suffix)
        for suffix in ("_test.py", ".test.js", ".test.ts", ".spec.js", ".spec.ts")
    )


def _is_ignored_path(path: str) -> bool:
    return bool(set(Path(path).parts) & IGNORED_PATH_PARTS)


def classify_paths(paths: list[str]) -> ChangeScope:
    """Classify a Git-visible change set without running repository code."""
    relevant = [
        path.replace("\\", "/")
        for path in paths
        if not _is_ignored_path(path)
        and path.replace("\\", "/").lower() not in IGNORED_CONFIG_PATHS
    ]
    if not relevant:
        return ChangeScope("docs-only", "no relevant source or test files changed", False)
    code = [path for path in relevant if Path(path).suffix.lower() in CODE_SUFFIXES]
    tests = [path for path in code if _is_test_path(path)]
    source = [path for path in code if path not in tests]
    if not code:
        return ChangeScope("docs-only", "only documentation or non-code files changed", False)
    if not source:
        return ChangeScope("tests-only", "test files changed", True)
    risk_segments = [
        segment
        for path in source
        for segment in re.split(r"[/\\_.-]+", path.lower())
        if segment
    ]
    if any(
        segment == marker or segment.startswith(marker)
        for segment in risk_segments
        for marker in HIGH_RISK_MARKERS
    ):
        return ChangeScope(
            "high-risk",
            "boundary or operational code changed; focused plus integration evidence is recommended",
            True,
        )
    return ChangeScope("source", "source code changed; fast and focused evidence is required", True)


def changed_paths(cwd: Path) -> list[str] | None:
    """Return working-tree paths, or None when cwd is not a Git checkout."""
    try:
        root_result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        )
        if root_result.returncode != 0:
            return None
        root = Path(root_result.stdout.strip())
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
        )
        if result.returncode != 0:
            return None
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    paths: list[str] = []
    for line in result.stdout.splitlines():
        raw = line[3:] if len(line) >= 4 else ""
        if " -> " in raw:
            raw = raw.rsplit(" -> ", 1)[-1]
        if raw:
            paths.append(raw.strip('"'))
    return paths


def load_policy_commands(cwd: Path) -> dict[str, list[str]]:
    """Load optional tokenized commands; invalid policy falls back safely.

    ``release`` is retained as a compatibility key for existing projects. It
    denotes the complete candidate matrix and is intentionally not an automatic
    per-edit lane; it does not imply that a VM or a release-signing step exists.
    """
    policy = cwd / ".claude" / "test-policy.json"
    if not policy.is_file():
        return {}
    try:
        data = json.loads(policy.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    commands: dict[str, list[str]] = {}
    for name in ("fast", "integration", "release"):
        value = data.get(name)
        if isinstance(value, list) and value and all(isinstance(item, str) and item for item in value):
            commands[name] = value
    return commands


def portable_argv(cmd: list[str], cwd: Path) -> list[str]:
    """Make a POSIX-authored test command runnable on Windows.

    A project's `.claude/test-command` is written for the repository, not for
    the machine that happens to read it: `./init.sh --fast` is correct on Linux
    and macOS and raises WinError 193 on Windows, because CreateProcess only
    runs real executables. The gate then reports "unavailable ... no green
    evidence", which reads exactly like a red suite while nothing ever ran —
    the failure mode we keep tightening these hooks against.

    So route shell scripts through bash when the platform cannot exec them
    directly. If bash is missing we return the command untouched: an honest
    "cannot run" beats a rewritten command that fails for a second reason.

    Scope, measured rather than assumed: `.sh` fails, and so does `.ps1`; `.cmd`
    and `.bat` run fine as-is, so they are deliberately left alone. `.ps1` is not
    covered because routing it would mean a different interpreter and a different
    argument form -- worth doing when a project actually declares one, not before.

    The suffix is matched case-insensitively: Windows filenames are, so `INIT.SH`
    is a real file that fails exactly like `init.sh`. Matching only the lowercase
    form would leave the hole open for the spelling nobody thinks to test.
    """
    if os.name != "nt" or not cmd:
        return cmd
    exe = cmd[0]
    if not exe.lower().endswith(".sh"):
        return cmd
    bash = shutil.which("bash")
    if not bash:
        return cmd
    # Forward slashes: bash reads its argument as a POSIX path, and cwd is
    # already the working directory of the subprocess.
    return [bash, exe.replace("\\", "/"), *cmd[1:]]


def resolve_timeout(cwd: Path) -> int:
    """How long the suite may run before we call it hung.

    The module docstring has advertised `TEST_TIMEOUT_SEC` as a knob while the code held a
    constant, so the documented control did not exist. It does now, and a project can also state
    its own budget in `.claude/test-command` as a `# timeout: <seconds>` comment line - the honest
    place for it, next to the command whose runtime it describes.

    A suite that finishes green in 139 seconds must not be reported as a timeout at 180: that reads
    exactly like a red suite while nothing was wrong, the failure mode these hooks exist to prevent.
    Precedence: project directive, then environment, then the default. Malformed values are
    announced on stderr rather than silently ignored.
    """
    def clamp(value: int) -> int:
        return max(TEST_TIMEOUT_MIN_SEC, min(TEST_TIMEOUT_MAX_SEC, value))

    override = cwd / ".claude" / "test-command"
    if override.exists() and override.is_file():
        try:
            for raw_line in override.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line.startswith("#"):
                    if line:
                        break  # the command line; directives live above it
                    continue
                body = line.lstrip("#").strip()
                if body.lower().startswith("timeout:"):
                    text = body.split(":", 1)[1].strip()
                    if text.isdecimal():
                        try:
                            return clamp(int(text))
                        except ValueError:
                            pass
                    print("[test-gate] ignoring malformed '# timeout: " + text
                          + "' in .claude/test-command", file=sys.stderr)
        except OSError as exc:
            print("[test-gate] cannot read .claude/test-command for its timeout: "
                  + str(exc), file=sys.stderr)

    env = os.environ.get("TEST_TIMEOUT_SEC", "").strip()
    if env:
        if env.isdecimal():
            try:
                return clamp(int(env))
            except ValueError:
                pass
        print("[test-gate] ignoring malformed TEST_TIMEOUT_SEC=" + repr(env), file=sys.stderr)
    return TEST_TIMEOUT_SEC


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


def detect_test_commands(cwd: Path, scope: ChangeScope) -> list[tuple[list[str], str]]:
    """Choose the smallest configured suite that matches the change risk."""
    if not scope.should_run:
        return []
    policy = load_policy_commands(cwd)
    if policy:
        selected: list[tuple[list[str], str]] = []
        if "fast" in policy:
            selected.append((policy["fast"], "policy.fast"))
        if scope.name == "high-risk" and "integration" in policy:
            selected.append((policy["integration"], "policy.integration"))
        if selected:
            return selected

    detected = detect_test_command(cwd)
    return [detected] if detected else []


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

    paths = changed_paths(cwd)
    scope = (
        classify_paths(paths)
        if paths is not None
        else ChangeScope("unknown", "Git status unavailable; using the legacy project test detector", True)
    )
    if paths is not None and not scope.should_run:
        return 0

    commands = detect_test_commands(cwd, scope)
    if not commands:
        return 0

    print(
        f"[test-gate] scope={scope.name}; {scope.reason}; "
        f"running {len(commands)} selected suite(s)",
        file=sys.stderr,
    )

    failures: list[str] = []
    # Resolved ONCE: the number enforced and the number reported must be the same number, even if
    # a suite rewrites its own .claude/test-command while running.
    timeout_sec = resolve_timeout(cwd)
    for cmd, label in commands:
        cmd = portable_argv(cmd, cwd)
        try:
            # CI=1 forces watch-capable runners into run-once non-interactive
            # mode. FORCE_COLOR=0 keeps evidence compact and comparable.
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                timeout=timeout_sec,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, "CI": "1", "FORCE_COLOR": "0"},
            )
        except subprocess.TimeoutExpired:
            failures.append(
                f"{label}: timeout after {timeout_sec}s; no green evidence was produced"
            )
            continue
        except (FileNotFoundError, OSError) as e:
            failures.append(f"{label} unavailable: {e}; no green evidence was produced")
            continue

        if result.returncode == 0:
            continue

        # pytest exit 5 = no tests collected: a scaffold is not a red suite.
        is_pytest = label.startswith("pytest") or "pytest" in label
        if is_pytest and result.returncode == 5:
            continue

        output = (result.stdout or "") + "\n" + (result.stderr or "")
        if len(output) > MAX_OUTPUT_BYTES:
            output = output[-MAX_OUTPUT_BYTES:]
        payload = f"$ {' '.join(cmd)}\n\n{output}"
        if untrusted_block is not None:
            framed = untrusted_block(
                payload,
                f"{label} command + stdout/stderr, tail {MAX_OUTPUT_BYTES} bytes",
            )
        else:
            framed = f"Output (tail {MAX_OUTPUT_BYTES} bytes):\n{payload}"
        failures.append(f"{label} exit {result.returncode}:\n{framed}")

    if not failures:
        # Green tests close a `source` change. A high-risk one also needs a pass that is
        # not ours: our own suite did not cover the boundary before it moved, so it will
        # not notice that it moved.
        if scope.name == "high-risk" and paths and not reviews_for(paths):
            if stop_budget_consume is not None:
                stop_budget_consume(BUDGET_NAME, cwd)
            print(json.dumps({"decision": "block", "reason": (
                f"Tests are green, and this change is high-risk: {scope.reason} "
                f"No independent review is recorded for these {len(paths)} path(s). "
                f"More of our own tests is not a deeper check — run one independent pass "
                f"(/deep-review, or a fresh-context verifier returning PROCEED / HOLD / "
                f"REJECT per rules/no-guessing.md), then record what actually ran:\n"
                f'  python "{Path(__file__).as_posix()}" --record "<what ran, and its verdict>"\n'
                f"Evidence is keyed to this exact set of paths, so it will not carry over "
                f"to a different change. Deliberate override: CLAUDE_SKIP_TEST_GATE=1."
            )}))
            return 0
        return 0

    if stop_budget_consume is not None:
        stop_budget_consume(BUDGET_NAME, cwd)

    reason = (
        f"Test gate failed for change scope '{scope.name}'. "
        f"Cannot complete task while selected tests are red or unproven. "
        f"Per no-pre-existing-evasion rule: tests must be green before 'done'.\n\n"
        + "\n\n".join(failures)
        + "\n\nOptions:\n"
        "1. Fix the failures (preferred)\n"
        "2. If failures are genuinely unfixable: record a valid exception in "
        "PROBLEMS.md and use .claude/.skip-test-gate for this session\n"
        "3. Bypass: CLAUDE_SKIP_TEST_GATE=1 (emergency only)"
    )

    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


def _record_cli(argv: list[str]) -> int:
    """`--record "<note>"` — satisfy the high-risk review requirement for this change."""
    note = argv[argv.index("--record") + 1] if len(argv) > argv.index("--record") + 1 else ""
    if not note.strip():
        print("--record needs a note saying what actually ran and what it concluded",
              file=sys.stderr)
        return 2
    paths = changed_paths(Path.cwd())
    if not paths:
        print("nothing changed here; there is no surface to record a review against",
              file=sys.stderr)
        return 2
    key = record_review(note.strip(), paths)
    print(f"recorded for surface {key} ({len(paths)} path(s)): {note.strip()}")
    return 0


def _self_test() -> int:
    """`--self-test` - prove the timeout resolution, because nothing else does.

    An independent review found that `isdigit()` accepts characters `int()` refuses ("2" superscript
    is one), so a repository writing `# timeout: <that>` raised a ValueError past the OSError handler,
    killed this hook, and the Stop gate was skipped without a word. A gate that repository text can
    silently switch off is worse than no gate, so the predicate now has a test that fails if anyone
    loosens it again.
    """
    import tempfile

    failures = 0

    def check(label: str, got: object, want: object) -> None:
        nonlocal failures
        if got != want:
            failures += 1
            print(f"  FAIL {label}: got {got!r}, wanted {want!r}")
        else:
            print(f"  ok   {label}: {got!r}")

    saved = os.environ.pop("TEST_TIMEOUT_SEC", None)
    try:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / ".claude").mkdir()
            cmd = root / ".claude" / "test-command"

            cmd.write_text("# no directive\npytest -q\n", encoding="utf-8")
            check("no directive, no env", resolve_timeout(root), TEST_TIMEOUT_SEC)

            os.environ["TEST_TIMEOUT_SEC"] = "420"
            check("env only", resolve_timeout(root), 420)

            cmd.write_text("# timeout: 90\npytest -q\n", encoding="utf-8")
            check("directive beats env", resolve_timeout(root), 90)

            cmd.write_text("# timeout: 99999\npytest -q\n", encoding="utf-8")
            check("clamped to the ceiling", resolve_timeout(root), TEST_TIMEOUT_MAX_SEC)

            cmd.write_text("# timeout: 5\npytest -q\n", encoding="utf-8")
            check("clamped to the floor", resolve_timeout(root), TEST_TIMEOUT_MIN_SEC)

            # the regression that mattered: a value isdigit() accepts and int() refuses must NOT
            # crash the hook, because a crash here skips the whole gate
            cmd.write_text("# timeout: \u00b2\npytest -q\n", encoding="utf-8")
            check("superscript does not kill the gate", resolve_timeout(root), 420)

            cmd.write_text("# timeout: soon\npytest -q\n", encoding="utf-8")
            check("non-numeric falls through to env", resolve_timeout(root), 420)

            os.environ["TEST_TIMEOUT_SEC"] = "\u00b2"
            cmd.write_text("# no directive\npytest -q\n", encoding="utf-8")
            check("superscript in the env is refused too", resolve_timeout(root), TEST_TIMEOUT_SEC)
            os.environ["TEST_TIMEOUT_SEC"] = "420"

            cmd.write_text("pytest -q\n# timeout: 90\n", encoding="utf-8")
            check("a directive below the command is not a directive", resolve_timeout(root), 420)

            os.environ.pop("TEST_TIMEOUT_SEC", None)
            check("no file at all", resolve_timeout(root / "absent"), TEST_TIMEOUT_SEC)
    finally:
        os.environ.pop("TEST_TIMEOUT_SEC", None)
        if saved is not None:
            os.environ["TEST_TIMEOUT_SEC"] = saved

    print(f"SCANNED: cases=10 failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    if "--record" in sys.argv:
        sys.exit(_record_cli(sys.argv))
    sys.exit(main())
