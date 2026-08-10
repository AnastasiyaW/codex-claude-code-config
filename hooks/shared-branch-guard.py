#!/usr/bin/env python3
"""A shared checkout loses work to two git commands. Block both.

Both happened on 2026-08-07 in one of our repositories, hours apart, with several agents
and sessions working one tree:

  1. `git commit` with no pathspec committed whatever ANOTHER worker had staged.
     A half-finished JSX edit rode into a release commit, the admin rendered blank
     at HTTP 200, and production was down until it was traced.
  2. `git reset --mixed origin/<branch>` rewound FOUR commits off the shared branch,
     including one that had already been re-landed once after the first reset.
     The work survived only as unreachable objects; a `gc` would have ended it.

Neither is a mistake about git. Both are correct commands whose blast radius is the
whole tree rather than the caller's own work, which is precisely what a shared
checkout makes dangerous. Prose does not survive task pressure; this does.

Opt-in by marker, deliberately: a guard that fires in every repository on the machine
gets switched off, and then it protects nothing. Drop `.claude/shared-branch` in the
root of a repo that several workers share.

  blocked : git reset (any form) on a shared repo
            git commit with no pathspec and no --only/-o
  allowed : git commit -- <paths>, git commit --only <path>, git commit --amend
            with an explicit pathspec, and everything outside a marked repo

Bypass: CLAUDE_ALLOW_SHARED_BRANCH=1, or `# claude-bypass: shared-branch` in the command.
Self-test: python shared-branch-guard.py --self-test
"""
from __future__ import annotations

import os
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import safety_common as sc  # noqa: E402

HOOK = "shared-branch-guard"
MARKER = ".claude/shared-branch"

# `git` possibly behind a wrapper (sudo, timeout, env VAR=1), then the subcommand.
_GIT_CALL = re.compile(r"(?:^|[;&|]\s*)(?:\w+=\S+\s+|sudo\s+|timeout\s+\S+\s+)*git\b", re.I)


def repo_root(start: Path) -> Path | None:
    """The marked shared repo containing `start`, if any."""
    try:
        current = start.resolve()
    except OSError:
        return None
    for parent in (current, *current.parents):
        if (parent / MARKER).exists():
            return parent
    return None


def _segments(command: str) -> list[list[str]]:
    """Split a shell line into argv lists, one per `;`/`&&`/`||`-separated command."""
    out: list[list[str]] = []
    for raw in re.split(r"(?:&&|\|\||;)", command):
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(shlex.split(raw))
        except ValueError:
            out.append(raw.split())
    return out


def _git_args(argv: list[str]) -> list[str] | None:
    """The arguments after `git`, skipping wrappers and `-C <dir>` style options."""
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in ("sudo", "timeout") or "=" in token and not token.startswith("-"):
            index += 1
            if token == "timeout":
                index += 1
            continue
        break
    if index >= len(argv) or Path(argv[index]).name not in ("git", "git.exe"):
        return None
    rest = argv[index + 1:]
    # Strip git's own pre-subcommand options so `git -C x commit` is seen as `commit`.
    while rest:
        if rest[0] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace"):
            rest = rest[2:]
        elif rest[0].startswith("-"):
            rest = rest[1:]
        else:
            break
    return rest


def verdict(command: str) -> tuple[str, str] | None:
    """(kind, detail) when the command must be blocked; None when it may pass."""
    if not _GIT_CALL.search(command or ""):
        return None
    for argv in _segments(command):
        args = _git_args(argv)
        if not args:
            continue
        sub, rest = args[0], args[1:]

        if sub == "reset":
            return ("reset", " ".join(args))

        if sub == "commit":
            if "--only" in rest or "-o" in rest:
                continue
            # An explicit pathspec: after `--`, or a bare path-looking argument.
            if "--" in rest and rest.index("--") < len(rest) - 1:
                continue
            flags_with_value = {"-m", "--message", "-F", "--file", "-C", "--reuse-message",
                                "-c", "--reedit-message", "--author", "--date", "-S",
                                "--gpg-sign", "--cleanup", "--fixup", "--squash"}
            # Short flags bundle: `-am 'x'` is `-a -m 'x'`, so the message is a
            # separate token and must not be mistaken for a pathspec.
            value_letters = "mFCcS"
            index = 0
            has_path = False
            while index < len(rest):
                token = rest[index]
                if token in flags_with_value:
                    index += 2
                    continue
                if (token.startswith("-") and not token.startswith("--")
                        and len(token) > 1 and token[-1] in value_letters):
                    index += 2
                    continue
                if token.startswith("-"):
                    index += 1
                    continue
                has_path = True
                break
            if has_path:
                continue
            return ("commit", " ".join(args))
    return None


_REASONS = {
    "reset": (
        "`git reset` в ОБЩЕМ чекауте.\n\n"
        "07.08.2026 это сняло с ветки ЧЕТЫРЕ коммита, включая тот, что уже один раз\n"
        "перезаливали после предыдущего reset. Работа осталась жива только как\n"
        "недостижимые объекты — до ближайшего gc.\n\n"
        "Здесь ветку двигают несколько работников, и reset двигает её всем сразу.\n\n"
        "Что делать вместо:\n"
        "  свои правки убрать   -> git stash push -- <свои пути>\n"
        "  свой коммит отменить -> git revert <sha>  (добавляет, а не переписывает)\n"
        "  чужое сбросить       -> не сбрасывать; спросить владельца\n"
    ),
    "commit": (
        "`git commit` БЕЗ явных путей в общем чекауте.\n\n"
        "Коммитится ИНДЕКС, а не то, что перечислено в вашем `git add`. 07.08.2026\n"
        "так в релизный коммит уехала чужая недоделанная правка страницы: админка\n"
        "отдавала HTTP 200 и рисовала пустой экран, прод лежал, пока не нашли.\n\n"
        "Что делать вместо:\n"
        "  git commit --only <путь> -m '...'\n"
        "  git commit -m '...' -- <путь> [<путь> ...]\n"
    ),
}


def main() -> None:
    event = sc.read_event()
    command = sc.bash_command(event.get("tool_input") or {})
    if not command:
        sc.allow()
    if sc.bypass(command, "shared-branch", "CLAUDE_ALLOW_SHARED_BRANCH"):
        sc.allow()

    found = verdict(command)
    if found is None:
        sc.allow()

    # Only marked repositories are guarded. Check the session cwd and any -C target.
    cwd = Path(event.get("cwd") or os.getcwd())
    roots = [repo_root(cwd)]
    for match in re.finditer(r"-C\s+(\"[^\"]+\"|'[^']+'|\S+)", command):
        roots.append(repo_root(Path(match.group(1).strip("\"'"))))
    if not any(roots):
        sc.allow()

    kind, detail = found
    sc.block(f"{_REASONS[kind]}\nКоманда: {detail}\n\n"
             "Обход, если точно осознанно: CLAUDE_ALLOW_SHARED_BRANCH=1 "
             "или '# claude-bypass: shared-branch'.")


def _self_test() -> int:
    import tempfile

    failures: list[str] = []

    def check(name: str, got, want) -> None:
        if got != want:
            failures.append(f"{name}: got {got!r}, want {want!r}")

    def kind(command: str):
        found = verdict(command)
        return found[0] if found else None

    # --- blocked ---
    check("plain reset", kind("git reset --mixed origin/main"), "reset")
    check("hard reset", kind("git reset --hard HEAD~1"), "reset")
    check("reset via -C", kind("git -C /repo reset origin/br"), "reset")
    check("commit with no paths", kind("git commit -m 'x'"), "commit")
    check("commit -a", kind("git commit -am 'x'"), "commit")
    check("commit -F file", kind("git commit -F /tmp/msg.txt"), "commit")
    check("second command in a chain",
          kind("echo hi && git commit -m 'x'"), "commit")
    check("wrapped in timeout", kind("timeout 60 git reset --keep"), "reset")

    # --- allowed ---
    check("commit --only", kind("git commit --only app/x.py -m 'x'"), None)
    check("commit -o", kind("git commit -o app/x.py -m 'x'"), None)
    check("commit with pathspec after --",
          kind("git commit -m 'x' -- app/x.py"), None)
    check("commit with bare path", kind("git commit app/x.py -m 'x'"), None)
    check("not git at all", kind("reset the thing"), None)
    check("git status", kind("git status --short"), None)
    check("git add", kind("git add app/x.py"), None)
    check("a word containing reset", kind("git log --grep=reset"), None)

    # --- marker scoping ---
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        (root / ".claude").mkdir(parents=True)
        (root / MARKER).touch()
        nested = root / "app" / "backend"
        nested.mkdir(parents=True)
        check("marker found from a nested dir", repo_root(nested), root)
        outside = Path(tmp) / "elsewhere"
        outside.mkdir()
        check("no marker outside", repo_root(outside), None)

    for line in failures:
        print("FAIL", line)
    print(f"{'FAILED' if failures else 'OK'}: {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(_self_test())
    try:
        main()
    except Exception:  # noqa: BLE001 - a bug here must never block ordinary git use
        sc.allow()
