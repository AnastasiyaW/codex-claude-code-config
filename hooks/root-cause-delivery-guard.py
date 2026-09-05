#!/usr/bin/env python3
"""Keep bug and substantial-change work moving from evidence to delivery.

The hook has three narrow roles:

* ``UserPromptSubmit`` records an active delivery intent for an explicit incident
  or substantive implementation request.
* ``PreToolUse`` keeps source edits behind a repository-local delivery case whose
  analysis and plan are frozen.
* ``Stop`` rejects an unfinished case after source changes.

It intentionally does not try to infer root cause from source text, run a full
release matrix, or classify every shell command.  Those are either project
decisions or are already owned by the test and release gates.  The durable case
is the bridge between them: evidence -> diagnosis -> bounded plan -> repair ->
same reproducer -> candidate proof.

The file also provides a small CLI so the installed hook remains the single
implementation of the case format:

    python root-cause-delivery-guard.py init <case-id> --kind incident --summary "..."
    python root-cause-delivery-guard.py validate <case-id>
    python root-cause-delivery-guard.py freeze <case-id>
    python root-cause-delivery-guard.py begin <case-id>
    python root-cause-delivery-guard.py capture <case-id> --phase before -- <test argv>
    python root-cause-delivery-guard.py capture <case-id> --phase after -- <same test argv>
    python root-cause-delivery-guard.py record-independent-review <case-id> --reviewer <fresh-session> --evidence <receipt.md>
    python root-cause-delivery-guard.py verify <case-id>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from safety_common import (  # noqa: E402
        same_session as _same_session,
        session_alive as _session_alive,
        stop_budget_consume,
        stop_budget_exhausted,
    )
except ImportError:  # fail-open: keep the original one-shot behaviour
    stop_budget_consume = stop_budget_exhausted = None  # type: ignore[assignment]
    # Fail CLOSED on ownership: if the shared helper is unavailable we cannot
    # tell a live foreign owner from a dead one, and guessing "foreign" would
    # silently stop blocking on real cases. Treat every case as ours instead --
    # noisier, never permissive.
    def _same_session(a: str, b: str) -> bool:  # type: ignore[misc]
        return True

    def _session_alive(session_id: str) -> bool:  # type: ignore[misc]
        return False

# Gate name for the shared Stop-hook rejection budget (safety_common).
#
# Without a budget this gate can wedge a session shut with no way out. Its Stop
# check is repository-wide: any changed source file plus any foreign unresolved
# intent blocks, even for a session that never touched the repository. On an
# aggregation hub that is permanent. Measured 2026-08-15 in Claude_code: 22 795
# changed source files, one intent owned by another live session, and no
# delivery cases at all - so every other session was blocked until that intent
# expired eight hours later. Every other Stop gate in this tree already caps its
# refusals; this one did not.
BUDGET_NAME = "root-cause-delivery"

CASE_ROOT = Path(".agent") / "delivery-cases"
SCHEMA_VERSION = 1
MAX_CAPTURE_BYTES = 12_000
# A measured focused proof has taken 159.32 s, leaving too little scheduling
# headroom under the former 180 s ceiling. Proof capture remains bounded, but it
# must not turn a slow passing reproducer into a synthetic rc=124 failure.
CAPTURE_TIMEOUT_SEC = 900
ACTIVE_FOR_EDITS = {"PLAN_FROZEN", "IMPLEMENTING"}
COMPLETE_FOR_STOP = {"VERIFIED", "SEALED", "BLOCKED"}
VALID_STATUS = {
    "INTAKE",
    "ANALYZED",
    "PLAN_FROZEN",
    "IMPLEMENTING",
    "VERIFIED",
    "SEALED",
    "BLOCKED",
}
CODE_SUFFIXES = {
    ".bat", ".c", ".cc", ".cmd", ".cpp", ".cs", ".css", ".cxx", ".go",
    ".h", ".hpp", ".html", ".ini", ".java", ".js", ".json", ".jsx", ".kt",
    ".m", ".mdx", ".mjs", ".mm", ".nsi", ".ps1", ".py", ".pyi", ".rs", ".sh",
    ".sql", ".swift", ".toml", ".ts", ".tsx", ".vue", ".xml", ".yaml", ".yml",
}
SOURCE_BASENAMES = {"cmakelists.txt", "dockerfile", "gemfile", "makefile", "packagefile", "rakefile"}
INCIDENT_PATTERNS = (
    r"\b(bug|error|crash|regression|broken|failure|failing|doesn.t work|fix this)\b",
    r"\b(баг\w*|ошибк\w*|падает|краш\w*|регресси\w*|сломал\w*|не работает|почини\w*)\b",
)
CHANGE_PATTERNS = (
    r"\b(build|implement|create|develop|write|refactor|rewrite|migrate)\b",
    r"\b(сделай|реализуй|создай|разработай|напиши|рефактор|перепиши|мигрируй)\b",
)

# ``focused_argv`` is written by an agent, then later handed directly to
# subprocess.run by ``capture``.  Equality with a frozen plan proves only that
# the agent did not change its mind; it does not make the planned program safe
# to execute.  Keep this intentionally small: the capture runner is for local
# proof, not an escape hatch to a shell, package manager, network client, or
# arbitrary interpreter payload.
_SHELL_EXECUTABLES = frozenset({
    "bash", "sh", "zsh", "fish", "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe",
})
_NETWORK_EXECUTABLES = frozenset({
    "curl", "wget", "ssh", "scp", "sftp", "ftp", "rsync", "git", "gh",
    "npm", "npx", "pnpm", "yarn", "pip", "pip.exe", "uv", "poetry",
    "invoke-webrequest", "iwr",
})
_DESTRUCTIVE_EXECUTABLES = frozenset({
    "rm", "del", "erase", "rmdir", "rd", "remove-item", "move-item", "rename-item",
    "format", "diskpart", "dd", "shred", "unlink", "drop-database",
})
_DYNAMIC_ARGUMENTS = frozenset({
    "-c", "/c", "-command", "--command", "-encodedcommand", "--encodedcommand",
    "-e", "--eval", "--execute", "--shell", "--shell-exec",
})
_MUTATING_ARGUMENTS = frozenset({
    "--fix", "--unsafe-fixes", "--write", "--delete", "--remove", "--update", "--apply",
})
_PYTHON_MODULES = frozenset({"pytest", "unittest", "compileall", "py_compile", "ruff", "mypy"})
_PROOF_SCRIPT_NAME = re.compile(
    r"^(?:test_.+|.+_test|check_.+|.+_check|validate_.+|.+_validate|lint_.+|.+_lint|"
    r"run_.+_(?:checks|tests)|.+_(?:checks|tests))$",
    re.IGNORECASE,
)


def _proof_executable_name(value: str) -> str:
    return Path(value).name.casefold()


def _proof_argv_error(argv: list[str], root: Path | None) -> str | None:
    """Reject agent-authored argv outside the local proof-executor contract."""
    if not nonempty_strings(argv):
        return "must contain non-empty string argv entries"
    executable = _proof_executable_name(argv[0])
    if executable in _SHELL_EXECUTABLES:
        return "must not invoke a shell interpreter"
    if executable in _NETWORK_EXECUTABLES:
        return "must not invoke a network or package-management executable"
    if executable in _DESTRUCTIVE_EXECUTABLES:
        return "must not invoke a destructive executable"
    for argument in argv[1:]:
        lowered = argument.casefold()
        if lowered in _DYNAMIC_ARGUMENTS:
            return f"must not use dynamic execution argument {argument!r}"
        if lowered in _MUTATING_ARGUMENTS:
            return f"must not use mutating argument {argument!r}"

    if re.fullmatch(r"(?:python(?:[0-9]+(?:\.[0-9]+)?)?|py)(?:\.exe)?", executable):
        return _python_proof_argv_error(argv, root)
    if executable in {"pytest", "pytest.exe"}:
        return None
    if executable in {"ruff", "ruff.exe"}:
        if len(argv) >= 2 and argv[1] == "check":
            return None
        if len(argv) >= 2 and argv[1] == "format" and "--check" in argv[2:]:
            return None
        return "ruff proof must use `ruff check` or `ruff format --check`"
    if executable in {"mypy", "mypy.exe", "pyright", "pyright.exe"}:
        return None
    if executable == "go":
        if len(argv) >= 2 and argv[1] in {"test", "vet"}:
            return None
        return "go proof must use `go test` or `go vet`"
    if executable == "cargo":
        if len(argv) >= 2 and argv[1] in {"test", "check", "clippy"}:
            return None
        return "cargo proof must use `cargo test`, `cargo check`, or `cargo clippy`"
    if executable in {"gcc", "gcc.exe", "g++", "g++.exe", "clang", "clang.exe", "clang++", "clang++.exe", "cl", "cl.exe"}:
        if "-fsyntax-only" in argv[1:] or "/zs" in {argument.casefold() for argument in argv[1:]}:
            return None
        return "compiler proof must be syntax-only (`-fsyntax-only` or `/Zs`)"
    return "must use an approved local test, compiler, linter, or validator executable"


def _python_proof_argv_error(argv: list[str], root: Path | None) -> str | None:
    index = 1
    while index < len(argv) and argv[index] in {"-B", "-E", "-I", "-s", "-S"}:
        index += 1
    if index >= len(argv):
        return "python proof must name an approved module or local verification script"
    if argv[index] == "-m":
        if index + 1 < len(argv) and argv[index + 1] in _PYTHON_MODULES:
            return None
        return "python -m proof must name an approved test or validator module"
    if argv[index].startswith("-"):
        return "python proof must not use interpreter options other than -B/-E/-I/-s/-S or approved -m modules"
    script = Path(argv[index])
    if script.suffix.casefold() != ".py" or not _PROOF_SCRIPT_NAME.fullmatch(script.stem):
        return "python proof script must be a local test, check, lint, or validate .py file"
    if root is None:
        return None
    try:
        root_resolved = root.resolve()
        script_resolved = (script if script.is_absolute() else root_resolved / script).resolve()
        script_resolved.relative_to(root_resolved)
    except (OSError, ValueError):
        return "python proof script must stay inside the repository"
    if not script_resolved.is_file():
        return "python proof script must exist inside the repository"
    return None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(_json(value), encoding="utf-8")
    temp.replace(path)


def _normal(path: str | Path) -> str:
    value = str(path).replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value


def repo_root(cwd: Path | None = None) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd or Path.cwd()), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return Path(result.stdout.strip()).resolve()
    except OSError:
        return None


def root_for_path(raw_path: str) -> Path | None:
    path = Path(raw_path).expanduser()
    probe = path if path.is_dir() else path.parent
    return repo_root(probe)


def state_dir() -> Path:
    configured = os.environ.get("AGENT_ROOT_CAUSE_STATE_DIR", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".claude" / "state" / "root-cause-delivery"


def session_id_from_event(event: dict[str, Any] | None = None) -> str:
    for key in ("session_id", "sessionId", "conversation_id", "conversationId", "thread_id", "threadId"):
        value = (event or {}).get(key)
        if value:
            return str(value)
    return os.environ.get("AGENT_SESSION_ID", "unscoped")


def intent_path(root: Path, session_id: str = "unscoped") -> Path:
    key = hashlib.sha256(f"{root}\0{session_id}".encode("utf-8", "ignore")).hexdigest()[:24]
    return state_dir() / f"{key}.json"


def active_intent(root: Path, session_id: str = "unscoped") -> dict[str, Any] | None:
    value = _read_json(intent_path(root, session_id))
    if value is None:
        return None
    expires_at = value.get("expires_at")
    if not isinstance(expires_at, (int, float)) or expires_at <= time.time():
        return None
    return value


def active_intents(root: Path) -> list[dict[str, Any]]:
    intents: list[dict[str, Any]] = []
    try:
        candidates = state_dir().glob("*.json")
    except OSError:
        return intents
    for path in candidates:
        value = _read_json(path)
        if value is None or value.get("root") != str(root):
            continue
        expires_at = value.get("expires_at")
        if isinstance(expires_at, (int, float)) and expires_at > time.time():
            intents.append(value)
    return sorted(intents, key=lambda value: float(value.get("recorded_at", 0)), reverse=True)


def resolve_intent(root: Path, session_id: str, intent_id: str | None = None) -> dict[str, Any] | None:
    intents = unresolved_intents(root)
    if intent_id:
        return next((intent for intent in intents if intent.get("intent_id") == intent_id), None)
    scoped = active_intent(root, session_id)
    if scoped is not None:
        return scoped
    return intents[0] if len(intents) == 1 else None


def record_intent(root: Path, kind: str, prompt: str, session_id: str = "unscoped") -> dict[str, Any]:
    now = time.time()
    prompt_hash = hashlib.sha256(prompt.encode("utf-8", "ignore")).hexdigest()
    value = {
        "schema_version": 1,
        "intent_id": hashlib.sha256(f"{root}\0{prompt_hash}\0{now}".encode()).hexdigest()[:12],
        "kind": kind,
        "root": str(root),
        "session_id": session_id,
        "prompt_sha256": prompt_hash,
        "recorded_at": now,
        "expires_at": now + 8 * 60 * 60,
    }
    _write_json(intent_path(root, session_id), value)
    return value


def classify_prompt(prompt: str) -> str | None:
    if any(re.search(pattern, prompt, re.IGNORECASE) for pattern in INCIDENT_PATTERNS):
        return "incident"
    if any(re.search(pattern, prompt, re.IGNORECASE) for pattern in CHANGE_PATTERNS):
        return "change"
    return None


def event_prompt(event: dict[str, Any]) -> str:
    for key in ("prompt", "user_prompt", "message", "content"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


PATCH_FILE_RE = re.compile(r"(?m)^\*\*\* (?:Add|Update|Delete) File: (?P<path>.+?)\s*$")


def apply_patch_paths(event: dict[str, Any], tool_input: dict[str, Any]) -> list[str] | None:
    """Extract declared files from Codex's canonical ``apply_patch`` command.

    Codex delivers an ``apply_patch`` hook event with a textual ``command``
    rather than Claude-style ``file_path`` arguments.  Section headers are the
    only authoritative path declaration here; do not scrape arbitrary patch
    content, which may itself contain text resembling a path.
    """
    command = tool_input.get("command")
    if not isinstance(command, str):
        return None
    cwd = event.get("cwd")
    base = Path(cwd) if isinstance(cwd, str) and cwd.strip() else None
    paths: list[str] = []
    for match in PATCH_FILE_RE.finditer(command):
        raw = match.group("path").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if not path.is_absolute() and base is not None:
            path = base / path
        paths.append(str(path))
    return list(dict.fromkeys(paths)) or None


def event_paths(event: dict[str, Any]) -> list[str] | None:
    tool = str(event.get("tool_name") or "")
    if tool not in {"Write", "Edit", "MultiEdit", "NotebookEdit", "apply_patch"}:
        return []
    tool_input = event.get("tool_input") or {}
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except json.JSONDecodeError:
            return []
    if not isinstance(tool_input, dict):
        return []
    if tool == "apply_patch":
        return apply_patch_paths(event, tool_input)
    paths: list[str] = []
    for key in ("file_path", "path", "notebook_path"):
        value = tool_input.get(key)
        if value:
            paths.append(str(value))
    for edit in tool_input.get("edits") or []:
        if isinstance(edit, dict):
            value = edit.get("file_path") or edit.get("path")
            if value:
                paths.append(str(value))
    return list(dict.fromkeys(paths))


def relative(root: Path, raw_path: str) -> str | None:
    try:
        return _normal(Path(raw_path).expanduser().resolve().relative_to(root))
    except (OSError, ValueError):
        return None


# Directories the delivery harness WRITES. Its own bookkeeping must not read as
# the source it exists to gate: closing a user-task receipt makes the completion
# guard write .agent/user-tasks/<id>/terminal-receipt.json, whose .json suffix
# then satisfies is_source_path, so the act of finishing one gate manufactured
# the condition that blocks the other. Measured 2026-08-29: fourteen files
# written after an intent, every one of them a terminal-receipt.json.
HARNESS_OUTPUT_ROOTS = (CASE_ROOT, Path(".agent") / "user-tasks")


def is_case_path(rel_path: str) -> bool:
    """True for a path the delivery harness itself owns and writes."""
    normal = _normal(rel_path)
    return any(normal.startswith(_normal(root) + "/") for root in HARNESS_OUTPUT_ROOTS)


def is_source_path(rel_path: str) -> bool:
    path = Path(rel_path)
    return path.suffix.lower() in CODE_SUFFIXES or path.name.lower() in SOURCE_BASENAMES


def case_path(root: Path, case_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", case_id):
        raise ValueError("case id must be kebab-case, 2-63 ASCII characters")
    return root / CASE_ROOT / case_id / "case.json"


def load_case(root: Path, case_id: str) -> tuple[dict[str, Any] | None, Path]:
    path = case_path(root, case_id)
    return _read_json(path), path


def cases_for_intent(root: Path, intent_id: str) -> list[tuple[dict[str, Any], Path]]:
    found: list[tuple[dict[str, Any], Path]] = []
    base = root / CASE_ROOT
    if not base.is_dir():
        return found
    for path in base.glob("*/case.json"):
        case = _read_json(path)
        if case and case.get("intent_id") == intent_id:
            found.append((case, path))
    return sorted(found, key=lambda item: float(item[0].get("updated_at", 0)), reverse=True)


def case_owner(case: dict[str, Any]) -> str:
    """Session that opened this case, however the writer spelled it."""
    for key in ("session_id", "builder", "sessionId", "owner"):
        value = case.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def foreign_and_live(case: dict[str, Any], current_session: str) -> str:
    """Owner id when this case belongs to a DIFFERENT, still-live session.

    Cases live in one shared directory but a Stop gate belongs to one session.
    Without this, session A cannot end its turn until session B closes a case A
    has never touched -- measured 2026-08-18, when two live sessions' in-flight
    cases (PLAN_FROZEN and IMPLEMENTING, both written within the hour) held this
    session's Stop indefinitely. The only ways out were to falsify another
    session's record or to switch the gate off, and both are worse than the gap.

    Deliberately narrow: an ownerless case still blocks everyone, and so does a
    case whose owner has gone quiet past the TTL. A live owner's open case only
    warns. Same contract as transfer-contract-guard, from the same helper rather
    than a second copy -- duplicated guarded logic drifts and only one copy gets
    the fix.
    """
    owner = case_owner(case)
    if not owner or _same_session(owner, current_session):
        return ""
    return owner if _session_alive(owner) else ""


def unfinished_cases(
    root: Path, current_session: str = "",
) -> tuple[list[tuple[dict[str, Any], Path]], list[tuple[dict[str, Any], Path]]]:
    """(cases that block this session, cases owned by another live session)."""
    blocking: list[tuple[dict[str, Any], Path]] = []
    foreign: list[tuple[dict[str, Any], Path]] = []
    base = root / CASE_ROOT
    if not base.is_dir():
        return blocking, foreign
    for path in base.glob("*/case.json"):
        case = _read_json(path)
        if not case or case.get("status") in COMPLETE_FOR_STOP:
            continue
        if foreign_and_live(case, current_session):
            foreign.append((case, path))
        else:
            blocking.append((case, path))
    key = lambda item: float(item[0].get("updated_at", 0))
    return (sorted(blocking, key=key, reverse=True),
            sorted(foreign, key=key, reverse=True))


def unresolved_intents(root: Path) -> list[dict[str, Any]]:
    pending: list[dict[str, Any]] = []
    for intent in active_intents(root):
        cases = cases_for_intent(root, str(intent.get("intent_id") or ""))
        if not cases or any(case.get("status") not in COMPLETE_FOR_STOP for case, _ in cases):
            pending.append(intent)
    return pending


def nonempty_strings(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item.strip() for item in value)


def labeled_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip().lower()] = value.strip()
    return fields


def validation_errors(
    case: dict[str, Any],
    *,
    root: Path | None = None,
    require_terminal: bool = False,
) -> list[str]:
    errors: list[str] = []
    if case.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version must be 1")
    if case.get("kind") not in {"incident", "change"}:
        errors.append("kind must be incident or change")
    status = case.get("status")
    if status not in VALID_STATUS:
        errors.append("status is invalid")
    if not isinstance(case.get("summary"), str) or not case["summary"].strip():
        errors.append("summary is required")

    needs_plan = status in {"ANALYZED", "PLAN_FROZEN", "IMPLEMENTING", "VERIFIED", "SEALED", "BLOCKED"}
    layer = case.get("layer") if isinstance(case.get("layer"), dict) else {}
    if needs_plan:
        for key in ("entrypoints", "owner_paths", "direct_dependents", "state_or_contract", "tests_or_probes"):
            if not nonempty_strings(layer.get(key)):
                errors.append(f"layer.{key} must name at least one observed boundary")
        if not isinstance(layer.get("release_boundary"), str) or not layer["release_boundary"].strip():
            errors.append("layer.release_boundary is required (use not-applicable when appropriate)")
        plan = case.get("plan") if isinstance(case.get("plan"), dict) else {}
        if not isinstance(plan.get("causal_hypothesis"), str) or not plan["causal_hypothesis"].strip():
            errors.append("plan.causal_hypothesis is required")
        if not nonempty_strings(plan.get("fix_steps")):
            errors.append("plan.fix_steps must contain bounded source changes")
        focused_argv = plan.get("focused_argv")
        if not nonempty_strings(focused_argv):
            errors.append("plan.focused_argv must contain the post-fix verifier command")
        else:
            proof_error = _proof_argv_error(focused_argv, root)
            if proof_error:
                errors.append(f"plan.focused_argv {proof_error}")

    observed = case.get("observed") if isinstance(case.get("observed"), dict) else {}
    verification = case.get("verification") if isinstance(case.get("verification"), dict) else {}
    if case.get("kind") == "incident" and status in {"ANALYZED", "PLAN_FROZEN", "IMPLEMENTING", "VERIFIED", "SEALED"}:
        for key in ("expected", "actual"):
            if not isinstance(observed.get(key), str) or not observed[key].strip():
                errors.append(f"observed.{key} is required for an incident")
        before = verification.get("before")
        if not isinstance(before, dict) or before.get("returncode") in (None, 0):
            errors.append("incident needs captured failing before evidence")

    attempts = case.get("attempts") if isinstance(case.get("attempts"), list) else []
    failures = sum(1 for attempt in attempts if isinstance(attempt, dict) and attempt.get("result") == "FAIL")
    if failures >= 2:
        retriage = case.get("retriage") if isinstance(case.get("retriage"), dict) else {}
        if retriage.get("after_failed_attempt") != failures or not nonempty_strings(retriage.get("expanded_owner_paths")):
            errors.append("two failed attempts require retriage.after_failed_attempt and expanded_owner_paths")

    if status in {"VERIFIED", "SEALED"}:
        after = verification.get("after")
        if not isinstance(after, dict) or after.get("returncode") != 0:
            errors.append("VERIFIED needs captured passing after evidence")
        before = verification.get("before")
        if case.get("kind") == "incident" and isinstance(before, dict) and isinstance(after, dict):
            if before.get("argv") != after.get("argv"):
                errors.append("incident before/after evidence must run the same reproducer argv")
        review = verification.get("independent_review")
        if not isinstance(review, dict):
            errors.append("VERIFIED needs an independent-review receipt")
        else:
            for key in ("reviewer", "evidence_path", "sha256"):
                if not isinstance(review.get(key), str) or not review[key].strip():
                    errors.append(f"independent review is missing {key}")
            if review.get("verdict") != "PASS" or review.get("fresh_context") is not True:
                errors.append("independent review must be fresh_context=true with verdict PASS")
            if root is not None and isinstance(review.get("evidence_path"), str):
                receipt = root / review["evidence_path"]
                try:
                    digest = hashlib.sha256(receipt.read_bytes()).hexdigest()
                except OSError:
                    errors.append("independent review receipt is missing on disk")
                else:
                    if digest != review.get("sha256"):
                        errors.append("independent review receipt digest is stale")

    release = case.get("release") if isinstance(case.get("release"), dict) else {}
    if status == "SEALED":
        for key in ("candidate_commit", "candidate_tree", "fresh_verdict_path"):
            if not isinstance(release.get(key), str) or not release[key].strip():
                errors.append(f"release.{key} is required for SEALED")
    if status == "BLOCKED":
        blocker = case.get("blocker")
        if not isinstance(blocker, dict) or not isinstance(blocker.get("external_prerequisite"), str) or not blocker["external_prerequisite"].strip():
            errors.append("BLOCKED needs blocker.external_prerequisite")
        elif root is None:
            errors.append("BLOCKED needs repository-root validation for its measured blocker evidence")
        else:
            evidence_path = blocker.get("evidence_path")
            if not isinstance(evidence_path, str) or not evidence_path.strip():
                errors.append("BLOCKED needs blocker.evidence_path")
            else:
                evidence = root / evidence_path
                try:
                    evidence_bytes = evidence.read_bytes()
                    digest = hashlib.sha256(evidence_bytes).hexdigest()
                except OSError:
                    errors.append("BLOCKED blocker evidence is missing on disk")
                else:
                    if digest != blocker.get("sha256"):
                        errors.append("BLOCKED blocker evidence digest is stale")
                    fields = labeled_fields(evidence_bytes.decode("utf-8", errors="replace"))
                    if fields.get("external prerequisite") != blocker.get("external_prerequisite"):
                        errors.append("BLOCKED blocker evidence must name the exact external prerequisite")
                    if not fields.get("observed"):
                        errors.append("BLOCKED blocker evidence needs an observed external condition")
    if require_terminal and status not in COMPLETE_FOR_STOP:
        errors.append("case is not terminal: need VERIFIED, SEALED, or BLOCKED")
    return errors


def default_case(
    root: Path,
    case_id: str,
    kind: str,
    summary: str,
    session_id: str = "unscoped",
    intent_id: str | None = None,
) -> dict[str, Any]:
    intent = resolve_intent(root, session_id, intent_id)
    now = time.time()
    return {
        "schema_version": SCHEMA_VERSION,
        "id": case_id,
        "intent_id": intent.get("intent_id") if intent else None,
        "session_id": str(intent.get("session_id") if intent else session_id),
        "builder": str(intent.get("session_id") if intent else session_id),
        "kind": kind,
        "status": "INTAKE",
        "summary": summary,
        "created_at": now,
        "updated_at": now,
        "observed": {"expected": "", "actual": ""},
        "layer": {
            "entrypoints": [],
            "owner_paths": [],
            "direct_dependents": [],
            "state_or_contract": [],
            "tests_or_probes": [],
            "release_boundary": "not-applicable",
        },
        "plan": {"causal_hypothesis": "", "fix_steps": [], "focused_argv": []},
        "verification": {},
        "attempts": [],
        "release": {"required": False},
    }


def save_case(path: Path, case: dict[str, Any]) -> None:
    case["updated_at"] = time.time()
    _write_json(path, case)


def record_independent_review(root: Path, case_id: str, reviewer: str, evidence: str) -> tuple[int, str]:
    case, path = load_case(root, case_id)
    if case is None:
        return 2, f"CASE: FAIL - missing {path}"
    builder = str(case.get("builder") or "")
    if not reviewer.strip() or reviewer == builder:
        return 2, "CASE: FAIL - reviewer must be a named fresh context, distinct from the builder"
    receipt = (root / evidence).resolve()
    try:
        relative_receipt = receipt.relative_to(root)
        text = receipt.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return 2, "CASE: FAIL - independent receipt must be a readable file inside the repository"
    fields = labeled_fields(text)
    required = ("case", "verdict", "baseline cause", "owner boundary", "reproducer", "after result")
    missing = [label for label in required if not fields.get(label)]
    if missing:
        return 2, "CASE: FAIL - independent receipt is missing: " + ", ".join(missing)
    if fields["case"] != case_id or fields["verdict"] != "PASS":
        return 2, "CASE: FAIL - independent receipt has the wrong case or verdict"
    layer = case.get("layer") if isinstance(case.get("layer"), dict) else {}
    plan = case.get("plan") if isinstance(case.get("plan"), dict) else {}
    hypothesis = plan.get("causal_hypothesis")
    if not isinstance(hypothesis, str) or fields["baseline cause"] != hypothesis:
        return 2, "CASE: FAIL - independent receipt baseline cause must exactly match the frozen causal hypothesis"
    owner_paths = layer.get("owner_paths") if isinstance(layer.get("owner_paths"), list) else []
    if fields["owner boundary"] not in owner_paths:
        return 2, "CASE: FAIL - independent receipt must name a mapped owner boundary"
    before = (case.get("verification") or {}).get("before")
    expected_argv = before.get("argv") if isinstance(before, dict) else plan.get("focused_argv")
    if expected_argv is None or fields["reproducer"] != json.dumps(expected_argv, ensure_ascii=False):
        return 2, "CASE: FAIL - independent receipt reproducer must match the captured baseline or planned argv"
    verification = case.setdefault("verification", {})
    verification["independent_review"] = {
        "reviewer": reviewer,
        "fresh_context": True,
        "verdict": "PASS",
        "evidence_path": _normal(relative_receipt),
        "sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
    }
    save_case(path, case)
    return 0, f"CASE: independent review recorded from {reviewer}"


def capture(root: Path, case_id: str, phase: str, argv: list[str]) -> tuple[int, str]:
    case, path = load_case(root, case_id)
    if case is None:
        return 2, f"CASE: FAIL - missing {path}"
    if not argv:
        return 2, "CASE: FAIL - capture requires an argv after --"
    if phase not in {"before", "after"}:
        return 2, "CASE: FAIL - phase must be before or after"
    if phase == "before" and case.get("status") not in {"INTAKE", "ANALYZED"}:
        return 2, "CASE: FAIL - before capture requires INTAKE or ANALYZED"
    if phase == "after" and case.get("status") != "IMPLEMENTING":
        return 2, "CASE: FAIL - after capture requires IMPLEMENTING"
    plan = case.get("plan") if isinstance(case.get("plan"), dict) else {}
    focused_argv = plan.get("focused_argv")
    if not nonempty_strings(focused_argv) or argv != focused_argv:
        return 2, "CASE: FAIL - capture argv must exactly match the plan.focused_argv frozen for this case"
    proof_error = _proof_argv_error(argv, root)
    if proof_error:
        return 2, f"CASE: FAIL - unsafe focused_argv: {proof_error}"
    try:
        result = subprocess.run(
            argv,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CAPTURE_TIMEOUT_SEC,
            check=False,
        )
        output = (result.stdout + result.stderr)[-MAX_CAPTURE_BYTES:]
        returncode = result.returncode
    except subprocess.TimeoutExpired as exc:
        output = ((exc.stdout or "") + (exc.stderr or ""))[-MAX_CAPTURE_BYTES:]
        returncode = 124
    except OSError as exc:
        output = f"could not run argv: {exc}"
        returncode = 127
    expected = 0 if phase == "after" else None
    if phase == "before" and case.get("kind") == "incident" and returncode == 0:
        return 1, "CASE: FAIL - incident baseline unexpectedly passed; do not invent a bug case"
    before = (case.get("verification") or {}).get("before")
    if phase == "after" and case.get("kind") == "incident" and isinstance(before, dict) and before.get("argv") != argv:
        return 1, "CASE: FAIL - after must run exactly the captured failing argv"
    evidence_dir = path.parent / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_dir / f"{phase}-{len(case.get('attempts') or []):02d}.txt"
    rendered = "argv: " + json.dumps(argv, ensure_ascii=False) + f"\nreturncode: {returncode}\n\n" + output
    evidence_path.write_text(rendered, encoding="utf-8")
    item = {
        "argv": argv,
        "returncode": returncode,
        "evidence_path": _normal(evidence_path.relative_to(root)),
        "sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
    }
    verification = case.setdefault("verification", {})
    verification[phase] = item
    if phase == "after" and returncode != 0:
        attempts = case.setdefault("attempts", [])
        attempts.append({
            "number": len(attempts) + 1,
            "result": "FAIL",
            "phase": "after",
            "argv": argv,
            "evidence_path": item["evidence_path"],
        })
    save_case(path, case)
    label = "PASS" if (returncode == 0) == (phase == "after") else "FAIL"
    return (0 if label == "PASS" else 1), f"CASE: {label} {phase} returncode={returncode} evidence={item['evidence_path']}"


def record_blocked(root: Path, case_id: str, prerequisite: str, evidence: str) -> tuple[int, str]:
    case, path = load_case(root, case_id)
    if case is None:
        return 2, f"CASE: FAIL - missing {path}"
    if case.get("status") not in {"INTAKE", "ANALYZED", "PLAN_FROZEN", "IMPLEMENTING"}:
        return 2, "CASE: FAIL - block requires an unfinished case"
    receipt = (root / evidence).resolve()
    try:
        relative_receipt = receipt.relative_to(root)
        content = receipt.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return 2, "CASE: FAIL - blocker evidence must be a readable file inside the repository"
    fields = labeled_fields(content)
    if fields.get("external prerequisite") != prerequisite:
        return 2, "CASE: FAIL - blocker evidence must name the exact external prerequisite"
    if not fields.get("observed"):
        return 2, "CASE: FAIL - blocker evidence must record an observed external condition"
    case["status"] = "BLOCKED"
    case["blocker"] = {
        "external_prerequisite": prerequisite,
        "evidence_path": _normal(relative_receipt),
        "sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
    }
    errors = validation_errors(case, root=root)
    if errors:
        case["status"] = "IMPLEMENTING"
        save_case(path, case)
        return 1, "CASE: FAIL\n" + "\n".join(f"- {error}" for error in errors)
    save_case(path, case)
    return 0, f"CASE: BLOCKED evidence={_normal(relative_receipt)}"


def record_failed_attempt(root: Path, case_id: str, hypothesis: str, changed_paths: list[str]) -> tuple[int, str]:
    case, path = load_case(root, case_id)
    if case is None:
        return 2, f"CASE: FAIL - missing {path}"
    attempts = case.setdefault("attempts", [])
    attempts.append({
        "number": len(attempts) + 1,
        "result": "FAIL",
        "hypothesis": hypothesis,
        "changed_paths": changed_paths,
    })
    save_case(path, case)
    return 0, f"CASE: recorded failed attempt {len(attempts)}"


def emit_block(reason: str) -> None:
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))


def pending_intent_needing_case(root: Path, session_id: str) -> dict[str, Any] | None:
    """Return only this session's delivery intent when no valid edit case exists."""
    pending = unresolved_intents(root)
    intent = next((item for item in pending if item.get("session_id") == session_id), None)
    if intent is None:
        return None
    matches = cases_for_intent(root, str(intent["intent_id"]))
    ready = [case for case, _ in matches if case.get("status") in ACTIVE_FOR_EDITS and not validation_errors(case, root=root)]
    return None if ready else intent


def block_missing_case(intent: dict[str, Any], detail: str = "") -> None:
    kind = str(intent.get("kind") or "change")
    emit_block(
        "Source edit blocked: this repository has an active " + kind + " delivery intent, "
        "but no valid PLAN_FROZEN delivery case. " + detail
        + "Create .agent/delivery-cases/<id>/case.json with the affected layer and bounded plan, then freeze it. Use: "
        "python ~/.claude/hooks/root-cause-delivery-guard.py init <case-id> "
        f"--kind {kind} --summary \"...\". Case documents themselves remain writable."
    )


def pretool(event: dict[str, Any]) -> None:
    paths = event_paths(event)
    session_id = session_id_from_event(event)
    if paths is None:
        # Codex sends patch text rather than file_path fields. If section
        # declarations cannot be parsed, it is not proven to be docs-only.
        # Fail closed for the owning intent, never for a foreign session.
        cwd = event.get("cwd")
        root = repo_root(Path(cwd)) if isinstance(cwd, str) and cwd.strip() else None
        if root is not None:
            intent = pending_intent_needing_case(root, session_id)
            if intent is not None:
                block_missing_case(intent, "Codex apply_patch paths could not be identified. ")
        return
    if not paths:
        return
    roots: set[Path] = set()
    for raw_path in paths:
        root = root_for_path(raw_path)
        if root is None:
            continue
        rel_path = relative(root, raw_path)
        if rel_path and is_source_path(rel_path) and not is_case_path(rel_path):
            roots.add(root)
    for root in roots:
        intent = pending_intent_needing_case(root, session_id)
        if intent is None:
            # Somebody else's unfinished delivery is not this session's to answer
            # for. Measured 2026-08-16: two other sessions held open intents in
            # the hub, and this one could neither write a file nor end its turn -
            # while the 1247 changed paths it was blamed for belonged to them.
            # Collateral of that shape is exactly what gets a gate switched off,
            # and the gate is worth keeping. The session that OWNS a delivery is
            # still held to the protocol, immediately below.
            continue
        block_missing_case(intent)
        return


def git_source_changes(root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    changed: list[str] = []
    for line in result.stdout.splitlines():
        raw = line[3:] if len(line) >= 4 else ""
        if " -> " in raw:
            raw = raw.rsplit(" -> ", 1)[-1]
        rel = _normal(raw.strip().strip('"'))
        if rel and is_source_path(rel) and not is_case_path(rel):
            changed.append(rel)
    return changed


def changes_after(root: Path, changed: list[str], since: float) -> list[str]:
    """Keep only changed files last written at or after ``since``.

    A file whose last write predates the intent cannot be that intent's product.
    On a shared repository the tree permanently carries other sessions' work in
    progress, so pairing "this session owns an intent" with "the tree is dirty"
    holds a session for deliveries it never opened — the same collateral the
    foreign-case branch above already refuses to inflict.

    Doubt stays fail-closed: an unreadable mtime counts as attributable.
    """
    attributable: list[str] = []
    for rel in changed:
        try:
            mtime = (root / rel).stat().st_mtime
        except OSError:
            attributable.append(rel)
            continue
        if mtime >= since:
            attributable.append(rel)
    return attributable


def stop(event: dict[str, Any]) -> None:
    root = repo_root()
    if root is None:
        return
    open_cases, foreign_cases = unfinished_cases(root, session_id_from_event(event))
    for case, path in foreign_cases[:3]:
        print(f"[root-cause-delivery] not blocking on {path.relative_to(root)}: "
              f"owned by live session {case_owner(case)[:8]}", file=sys.stderr)
    if open_cases:
        details: list[str] = []
        for case, path in open_cases[:3]:
            errors = validation_errors(case, root=root, require_terminal=True)
            details.append(f"{path.relative_to(root)}")
            details.extend(f"- {error}" for error in errors[:4])
        suffix = "\nMore unfinished delivery cases exist." if len(open_cases) > 3 else ""
        block_stop(
            "Unfinished delivery case(s) cannot be displaced by a newer prompt.\n"
            + "\n".join(details)
            + suffix
            + "\nDo not replace more code cosmetically. Record the causal layer, run the planned proof, "
              "and either verify the candidate or record a measured external blocker."
        )
        return
    changed = git_source_changes(root)
    if not changed:
        return
    pending = unresolved_intents(root)
    if not pending:
        return
    session_id = session_id_from_event(event)
    intent = next((item for item in pending if item.get("session_id") == session_id), None)
    if intent is None:
        # The dirty tree is not evidence that THIS session changed anything: a
        # shared repository carries everyone's work in progress. Holding a
        # session's Stop for a delivery it never opened is collateral, and the
        # usual answer to collateral is that the gate gets disabled. A session
        # that owns an unresolved intent is still held, immediately below.
        return
    attributable = changes_after(root, changed, float(intent.get("recorded_at", 0) or 0))
    if not attributable:
        # Owning an intent is not the same as having changed anything under it.
        print(f"[root-cause-delivery] not blocking: none of {len(changed)} changed source "
              "file(s) was written after this intent was recorded", file=sys.stderr)
        return
    matches = cases_for_intent(root, str(intent["intent_id"]))
    if not matches:
        block_stop(
            "Source changed under an active delivery intent, but no delivery case exists. "
            "Do layer analysis, freeze the repair plan, and capture proof before ending."
        )


def block_stop(reason: str) -> None:
    if stop_budget_consume is not None:
        stop_budget_consume(BUDGET_NAME)
    emit_block(reason)


def handle_hook(event: dict[str, Any]) -> int:
    if event.get("tool_name"):
        pretool(event)
        return 0
    prompt = event_prompt(event)
    if prompt:
        root = repo_root()
        kind = classify_prompt(prompt)
        if root is not None and kind is not None:
            intent = record_intent(root, kind, prompt, session_id_from_event(event))
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": (
                        f"[root-cause-delivery] {kind} intent {intent['intent_id']} recorded. "
                        "Before source edits: map entrypoint, owner, callers, state/contract, tests, and release boundary; "
                        "freeze a bounded plan in .agent/delivery-cases/<id>/case.json. "
                        f"Use --intent-id {intent['intent_id']} if more than one session is active. "
                        "For an incident, capture the same reproducer red then green."
                    ),
                }
            }, ensure_ascii=False))
        return 0
    # Anti-loop with a budget, not a one-shot surrender (safety_common).
    #
    # The budget check used to sit BEHIND `stop_hook_active`, so it only ever ran on
    # a re-entrant Stop. A first-time Stop therefore refused unconditionally, and on
    # a tree where the block is permanent - an aggregation hub with a foreign
    # unresolved intent, which is the case this gate's own header describes - the
    # documented escape was unreachable. Measured 2026-08-16 in Claude_code: four
    # consecutive refusals with the counter standing at 2, i.e. the cap could not be
    # reached, let alone honoured.
    #
    # The gate is unchanged in strength: it still refuses max_fires times. What
    # changes is that the cap now applies on every Stop, which is what makes it a
    # budget rather than a wedge.
    if stop_budget_exhausted is not None and stop_budget_exhausted(BUDGET_NAME):
        return 0
    stop(event)
    return 0


def cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Root-cause delivery case helper")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("case_id")
    init.add_argument("--kind", choices=("incident", "change"), required=True)
    init.add_argument("--summary", required=True)
    init.add_argument("--intent-id", help="bind this case to the recorded UserPromptSubmit intent")
    for name in ("validate", "freeze", "begin", "verify"):
        command = sub.add_parser(name)
        command.add_argument("case_id")
    capture_parser = sub.add_parser("capture")
    capture_parser.add_argument("case_id")
    capture_parser.add_argument("--phase", choices=("before", "after"), required=True)
    review = sub.add_parser("record-independent-review")
    review.add_argument("case_id")
    review.add_argument("--reviewer", required=True)
    review.add_argument("--evidence", required=True)
    attempt = sub.add_parser("record-failed-attempt")
    attempt.add_argument("case_id")
    attempt.add_argument("--hypothesis", required=True)
    attempt.add_argument("--changed-path", action="append", default=[])
    retriage = sub.add_parser("retriage")
    retriage.add_argument("case_id")
    retriage.add_argument("--expanded-owner-path", action="append", required=True)
    retriage.add_argument("--causal-hypothesis", required=True)
    blocked = sub.add_parser("block")
    blocked.add_argument("case_id")
    blocked.add_argument("--external-prerequisite", required=True)
    blocked.add_argument("--evidence", required=True)
    # ``argparse.REMAINDER`` would consume ``--phase`` when users naturally put
    # the case id first. Keep the verifier argv outside the subparser so the
    # documented ``capture <case> --phase before -- <argv>`` contract works.
    args, remaining = parser.parse_known_args(argv)
    root = repo_root()
    if root is None:
        print("CASE: FAIL - run inside a Git repository", file=sys.stderr)
        return 2
    if args.command == "init":
        path = case_path(root, args.case_id)
        if path.exists():
            print(f"CASE: FAIL - already exists: {path}", file=sys.stderr)
            return 2
        session_id = os.environ.get("AGENT_SESSION_ID", "unscoped")
        if args.intent_id and resolve_intent(root, session_id, args.intent_id) is None:
            print("CASE: FAIL - named intent is not active for this repository", file=sys.stderr)
            return 2
        if not args.intent_id and session_id == "unscoped" and len(unresolved_intents(root)) > 1:
            print("CASE: FAIL - multiple active intents; pass --intent-id from the prompt receipt", file=sys.stderr)
            return 2
        case = default_case(
            root,
            args.case_id,
            args.kind,
            args.summary,
            session_id,
            args.intent_id,
        )
        save_case(path, case)
        print(f"CASE: created {path.relative_to(root)}")
        return 0
    case, path = load_case(root, args.case_id)
    if case is None:
        print(f"CASE: FAIL - missing {path}", file=sys.stderr)
        return 2
    if args.command == "validate":
        errors = validation_errors(case, root=root)
        if errors:
            print("CASE: FAIL\n" + "\n".join(f"- {error}" for error in errors))
            return 1
        print("CASE: PASS")
        return 0
    if args.command == "capture":
        capture_argv = remaining[1:] if remaining[:1] == ["--"] else remaining
        code, message = capture(root, args.case_id, args.phase, capture_argv)
        print(message)
        return code
    if args.command == "record-independent-review":
        code, message = record_independent_review(root, args.case_id, args.reviewer, args.evidence)
        print(message)
        return code
    if args.command == "record-failed-attempt":
        code, message = record_failed_attempt(root, args.case_id, args.hypothesis, args.changed_path)
        print(message)
        return code
    if args.command == "retriage":
        failures = sum(1 for item in case.get("attempts", []) if isinstance(item, dict) and item.get("result") == "FAIL")
        if failures < 2:
            print("CASE: FAIL - retriage is required after two failed attempts, not before", file=sys.stderr)
            return 2
        if case.get("status") != "IMPLEMENTING":
            print("CASE: FAIL - retriage requires IMPLEMENTING", file=sys.stderr)
            return 2
        layer = case.get("layer") if isinstance(case.get("layer"), dict) else {}
        known_owners = set(layer.get("owner_paths") or [])
        expanded = [item for item in args.expanded_owner_path if item not in known_owners]
        if not expanded:
            print("CASE: FAIL - retriage must add at least one new owner boundary", file=sys.stderr)
            return 2
        plan = case.get("plan") if isinstance(case.get("plan"), dict) else {}
        previous_hypothesis = plan.get("causal_hypothesis")
        if args.causal_hypothesis == previous_hypothesis:
            print("CASE: FAIL - retriage needs a changed causal hypothesis", file=sys.stderr)
            return 2
        layer["owner_paths"] = [*layer.get("owner_paths", []), *expanded]
        case["layer"] = layer
        plan["causal_hypothesis"] = args.causal_hypothesis
        case["plan"] = plan
        case["retriage"] = {
            "after_failed_attempt": failures,
            "expanded_owner_paths": expanded,
            "previous_hypothesis": previous_hypothesis,
        }
        case["status"] = "ANALYZED"
        save_case(path, case)
        print("CASE: retriage recorded")
        return 0
    if args.command == "block":
        code, message = record_blocked(root, args.case_id, args.external_prerequisite, args.evidence)
        print(message)
        return code
    if args.command == "freeze":
        if case.get("status") not in {"INTAKE", "ANALYZED"}:
            print("CASE: FAIL - freeze requires INTAKE or ANALYZED", file=sys.stderr)
            return 2
        case["status"] = "PLAN_FROZEN"
        errors = validation_errors(case, root=root)
        if errors:
            case["status"] = "ANALYZED"
            save_case(path, case)
            print("CASE: FAIL\n" + "\n".join(f"- {error}" for error in errors))
            return 1
        save_case(path, case)
        print("CASE: PLAN_FROZEN")
        return 0
    if args.command == "begin":
        if case.get("status") != "PLAN_FROZEN":
            print("CASE: FAIL - begin requires PLAN_FROZEN", file=sys.stderr)
            return 2
        case["status"] = "IMPLEMENTING"
        save_case(path, case)
        print("CASE: IMPLEMENTING")
        return 0
    if args.command == "verify":
        if case.get("status") != "IMPLEMENTING":
            print("CASE: FAIL - verify requires IMPLEMENTING", file=sys.stderr)
            return 2
        case["status"] = "VERIFIED"
        errors = validation_errors(case, root=root)
        if errors:
            case["status"] = "IMPLEMENTING"
            save_case(path, case)
            print("CASE: FAIL\n" + "\n".join(f"- {error}" for error in errors))
            return 1
        save_case(path, case)
        print("CASE: VERIFIED")
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


def main() -> int:
    if len(sys.argv) > 1:
        return cli(sys.argv[1:])
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    return handle_hook(event if isinstance(event, dict) else {})


if __name__ == "__main__":
    raise SystemExit(main())
