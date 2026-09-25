#!/usr/bin/env python3
"""Agent policy gates: the Claude-side half of a repo's `.github/agent-policy.json`.

Adopted 2026-09-25 from «блекпилл недели» (a CTO's rules for teams where agents
write most of the code): rules that live in a prompt are not followed, so every
rule that can be a check becomes one. The repo's local CI checks the finished
branch (`scripts/quality_gates.py`); this hook stops the three things an agent
does *during* the work that CI sees too late or not at all:

  * editing a human-owned document (AGENTS.md, the incident log, the policy);
  * opening a PR that is too big to review or has no template description;
  * running the widget test suites bare, so their Tk windows flash on the
    owner's screen (25.09: «окна чата открываются и закрываются по кругу»).

Only repos that declare a policy are affected; elsewhere the hook is silent.

Human-owned documents. The hook cannot verify a human's approval (same limit as
human-confirmation-guard), but UserPromptSubmit carries the human's own words: a
prompt that names a protected file (path or file name) unlocks exactly that file
for that turn. Text inside <pasted_content> does not count — pasted material is
data, not the owner's instruction — and the next prompt resets the unlock.

Fail-open on the hook's own errors (a broken hook must not wedge every session);
fail-closed on a match.
"""

from __future__ import annotations

import fnmatch
import json
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from safety_common import allow, bash_command, block, file_path, log, read_event  # noqa: E402

HOOK = "agent_policy_gates"
POLICY = Path(".github") / "agent-policy.json"
UNLOCKS = Path.home() / ".claude" / "state" / "human-owned-unlocks"
PASTED = re.compile(r"<pasted_content\b[^>]*>.*?</pasted_content\b[^>]*>", re.S | re.I)
CD_PREFIX = re.compile(r"""^\s*(?:cd|Set-Location)\s+("[^"]+"|'[^']+'|[^\s;&|]+)\s*(?:&&|;)""", re.I)
WRITES = re.compile(
    r"(>>?|\btee\b|\bsed\s+-i|Set-Content|Add-Content|Out-File|Copy-Item|Move-Item|"
    r"Rename-Item|Remove-Item|\bcp\b|\bmv\b|\brm\b|write_text|WriteAllText|"
    r"git\s+(?:checkout|restore)\b)", re.I)
TEST_RUN = re.compile(r"-m\s+(?:unittest|pytest)\b|\bpytest\b")
FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


# ---------- repo and policy ----------

def windows_path(text: str) -> Path:
    """`/d/x` (Git Bash) -> `D:/x`; quotes stripped."""
    text = text.strip("\"'")
    match = re.match(r"^/([a-zA-Z])/(.*)$", text)
    return Path(f"{match.group(1).upper()}:/{match.group(2)}") if match else Path(text)


def repo_root(start: Path) -> Path | None:
    probe = start if start.is_dir() else start.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        out = subprocess.run(["git", "-C", str(probe), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    top = out.stdout.strip()
    return Path(top).resolve() if out.returncode == 0 and top else None


def load_policy(root: Path | None) -> dict | None:
    if root is None or not (root / POLICY).is_file():
        return None
    return json.loads((root / POLICY).read_text(encoding="utf-8"))


def relative(root: Path, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(root).as_posix().lower()
    except ValueError:
        return None


def protected(policy: dict) -> list[str]:
    return [p.replace("\\", "/").lower() for p in policy.get("human_owned", [])]


def named_in(text: str, paths: list[str]) -> list[str]:
    """Protected paths the text names, by full path or by file name."""
    low = text.lower().replace("\\", "/")
    return [p for p in paths
            if p in low or re.search(rf"(?<![\w.-]){re.escape(p.rsplit('/', 1)[-1])}(?![\w-])", low)]


# ---------- human-owned documents ----------

def unlock_file(session: str) -> Path:
    return UNLOCKS / (re.sub(r"[^\w.-]", "_", session or "unknown") + ".json")


def on_prompt(event: dict) -> None:
    """Every prompt rewrites the session's unlock: what this prompt names, nothing more."""
    root = repo_root(Path(event.get("cwd") or "."))
    policy = load_policy(root)
    if policy is None:
        return
    words = PASTED.sub(" ", str(event.get("prompt", "")))
    record = {"root": str(root), "paths": named_in(words, protected(policy)), "at": time.time()}
    UNLOCKS.mkdir(parents=True, exist_ok=True)
    unlock_file(event.get("session_id", "")).write_text(json.dumps(record), encoding="utf-8")


def unlocked(event: dict, root: Path, rel: str) -> bool:
    path = unlock_file(event.get("session_id", ""))
    if not path.is_file():
        return False
    record = json.loads(path.read_text(encoding="utf-8"))
    return record.get("root") == str(root) and rel in record.get("paths", [])


def refuse_owned(rel: str, how: str) -> None:
    log("BLOCK", HOOK, "human-owned", rel, how)
    block(f"`{rel}` is a human-owned document (.github/agent-policy.json → human_owned). "
          "Agents do not edit it. Write the proposed text in the chat or in a "
          "`docs/*-proposed.md` file for a human to apply; if the owner asks for this "
          "exact edit, her message names the file and this turn is unlocked for it.")


def guard_file_tool(event: dict) -> None:
    tool_input = event.get("tool_input", {})
    raw = file_path(tool_input) or str(tool_input.get("notebook_path", ""))
    if not raw:
        return
    target = windows_path(raw)
    if UNLOCKS.resolve() in target.resolve().parents:
        block("Unlock records are written only by the prompt hook, from the owner's own words.")
    root = repo_root(target)
    policy = load_policy(root)
    if policy is None:
        return
    rel = relative(root, target)
    if rel in protected(policy) and not unlocked(event, root, rel):
        refuse_owned(rel, event.get("tool_name", ""))


def guard_command_writes(event: dict, command: str, root: Path, policy: dict) -> None:
    if "human-owned-unlocks" in command.lower():
        block("Unlock records are written only by the prompt hook, from the owner's own words.")
    for rel in named_in(command, protected(policy)):
        name = re.escape(rel.rsplit("/", 1)[-1])
        near = re.search(rf"{WRITES.pattern}[^\n|;&]*{name}|{name}[^\n|;&]*(>>?)", command, re.I)
        if near and not unlocked(event, root, rel):
            refuse_owned(rel, command[:200])


# ---------- gh pr create ----------

def added_lines(root: Path, base: str, ignore: list[str]) -> int | None:
    out = subprocess.run(["git", "-C", str(root), "diff", "--numstat", f"origin/{base}...HEAD"],
                         capture_output=True, text=True, timeout=30)
    if out.returncode:
        return None
    total = 0
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].isdigit():
            name = parts[2].split(" => ")[-1].rstrip("}")
            if not any(fnmatch.fnmatch(Path(name).name, pat) for pat in ignore):
                total += int(parts[0])
    return total


def pr_body(args: list[str], root: Path) -> str | None:
    for i, arg in enumerate(args):
        if arg in ("--body-file", "-F") and i + 1 < len(args):
            path = windows_path(args[i + 1])
            path = path if path.is_absolute() else root / path
            return path.read_text(encoding="utf-8") if path.is_file() else ""
        if arg in ("--body", "-b") and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith(("--body=", "--body-file=")):
            key, value = arg.split("=", 1)
            if key == "--body":
                return value
            path = windows_path(value)
            path = path if path.is_absolute() else root / path
            return path.read_text(encoding="utf-8") if path.is_file() else ""
    return None


def pr_gate(command: str, root: Path, policy: dict) -> None:
    found = re.search(r"\bgh\s+pr\s+create\b(.*)", command, re.S)
    if not found:
        return
    try:
        args = shlex.split(found.group(1).split("&&")[0], posix=True)
    except ValueError:
        args = found.group(1).split()
    problems = []
    base = next((args[i + 1] for i, a in enumerate(args[:-1]) if a in ("--base", "-B")),
                policy.get("base_branch", "master"))
    cap = int(policy.get("pr_max_added_lines", 2000))
    size = added_lines(root, base, policy.get("pr_size_ignore", []))
    if size is not None and size > cap:
        problems.append(f"it adds {size} lines, the cap is {cap}: split it into reviewable PRs")
    body = pr_body(args, root)
    required = policy.get("pr_required_sections", [])
    if body is None:
        problems.append("no description: pass --body-file written from "
                        ".github/pull_request_template.md")
    else:
        lines = {line.strip() for line in body.splitlines()}
        missing = [s for s in required if not any(line.startswith(s) for line in lines)]
        if missing:
            problems.append("the description lacks " + ", ".join(missing))
    if problems:
        log("BLOCK", HOOK, "pr-create", "; ".join(problems), command[:200])
        block("This PR does not meet .github/agent-policy.json: " + "; ".join(problems) + ".")


# ---------- widget tests ----------

def widget_test_gate(command: str, cwd: Path, root: Path, policy: dict) -> None:
    paths = [p.replace("\\", "/").lower() for p in policy.get("widget_test_paths", [])]
    if not paths or not TEST_RUN.search(command):
        return
    low = command.lower().replace("\\", "/")
    if "ci_local.py" in low or "hidden_run.py" in low:
        return
    inside = relative(root, cwd) or ""
    hit = next((p for p in paths if p.rsplit("/", 1)[-1] in low
                or inside == p or inside.startswith(p + "/")), None)
    if hit:
        log("BLOCK", HOOK, "widget-tests-visible", hit, command[:200])
        block(f"Widget tests run bare open real windows on the owner's screen. Run them on "
              f"the hidden desktop: `python scripts/ci_local.py --job widgets`, or one test: "
              f"`python scripts/hidden_run.py --cwd {hit} -- <python> -m unittest <test>`.")


# ---------- entry ----------

def on_tool(event: dict) -> None:
    tool = event.get("tool_name")
    if tool in FILE_TOOLS:
        guard_file_tool(event)
        return
    if tool not in {"Bash", "PowerShell"}:
        return
    command = bash_command(event.get("tool_input", {}))
    cwd = Path(event.get("cwd") or ".")
    prefix = CD_PREFIX.match(command)
    if prefix:
        target = windows_path(prefix.group(1))
        cwd = target if target.is_absolute() else cwd / target
    root = repo_root(cwd)
    policy = load_policy(root)
    if policy is None:
        return
    pr_gate(command, root, policy)
    widget_test_gate(command, cwd, root, policy)
    guard_command_writes(event, command, root, policy)


def main() -> None:
    event = read_event()
    try:
        if event.get("hook_event_name") == "UserPromptSubmit":
            on_prompt(event)
        else:
            on_tool(event)
    except (OSError, ValueError, subprocess.SubprocessError) as err:
        log("ERROR", HOOK, "fail-open", type(err).__name__, str(err)[:300])
    allow()


if __name__ == "__main__":
    main()
