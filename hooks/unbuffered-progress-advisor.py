#!/usr/bin/env python3
"""A long run whose progress is invisible reads as slow, not as stuck.

The failure, twice measured:

  - an rclone driver whose progress went into a captured buffer: "zero files" read as
    "just slow" for half an hour before anyone looked at the process itself;
  - a replay script launched in the background with redirected stdout, 33 minutes,
    output file empty the whole time. It was alive and quadratic. The only signal that
    told the truth was CPU seconds in the process list.

Both were Python launched with buffered stdout into a pipe or a file. Python line-buffers
to a terminal and block-buffers to anything else, so the first flush can be minutes in --
by which time the useful question ("is it progressing or wedged?") has no data behind it.

This is advisory, never a block: sometimes buffered output is exactly what is wanted. It
fires only on the narrow shape that produced both incidents -- a Python script sent to the
background or redirected, with no unbuffered flag and no PYTHONUNBUFFERED.

Bypass:    `# claude-bypass: unbuffered` in the command, or CLAUDE_ALLOW_BUFFERED=1
Self-test: python unbuffered-progress-advisor.py --self-test
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from safety_common import log  # noqa: E402

# Only the FIRST command matters, after an optional `cd ...&&` and env assignments. An
# earlier version searched the whole string for `python`, and measured against 14 days of
# real commands it fired 459 times, essentially all false: it matched a python invocation
# quoted inside `tailscale ssh ...`, inside a heredoc body, and inside a commit message.
# That is the same mistake as reading intent out of a shell string anywhere else -- so the
# trigger is the harness's own structured `run_in_background`, and the parsing is confined
# to the head of the command.
_HEAD = re.compile(
    r"^\s*(?:#[^\n]*\n\s*)*"                      # leading comment lines
    r"(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*"          # env assignments
    r"(?:cd\s+(?:\"[^\"]*\"|'[^']*'|\S+)\s*&&\s*)*"  # cd prefixes
    r"(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*"
    r"(?P<cmd>[\w:./\\-]*(?:python|python3|py)(?:\.exe)?)\s+(?P<rest>[^|;&\n]*)")
_UNBUFFERED = re.compile(r"(?:^|\s)-{1,2}u\b|PYTHONUNBUFFERED\s*=\s*[^0\s]")
_INLINE = re.compile(r"(?:^|\s)-[cm](?:\s|$)")
_SCRIPT = re.compile(r"\S+\.py\b")


def needs_advice(command: str, background: bool) -> bool:
    """True when a backgrounded Python script's progress would be invisible.

    Gated on `background` because that is structured input from the harness rather
    than something inferred from text -- and it is the shape both incidents had.
    """
    if not background or "claude-bypass: unbuffered" in command:
        return False
    if _UNBUFFERED.search(command):
        return False
    match = _HEAD.match(command)
    if not match:
        return False
    rest = match.group("rest")
    return bool(_SCRIPT.search(rest)) and not _INLINE.search(rest)


def main() -> int:
    if os.environ.get("CLAUDE_ALLOW_BUFFERED") == "1":
        return 0
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0  # fail open: an advisor must never be the reason work stops
    tool_input = event.get("tool_input") or {}
    command = str(tool_input.get("command") or "")
    if not command:
        return 0
    background = bool(tool_input.get("run_in_background"))
    if needs_advice(command, background):
        log("INFO", "unbuffered_progress", "advise", "background_no_-u", command[:200])
        print("[progress] This Python run sends its output to a pipe, a file or the "
              "background, so stdout is block-buffered and nothing appears until it "
              "ends or the buffer fills. A stall will read as slowness -- that has "
              "cost half an hour twice. Add -u, and have the loop print a count as it "
              "goes, so 'still working' and 'wedged' look different.", file=sys.stderr)
    return 0


def self_test() -> int:
    failures = []

    def check(label, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")
        print(f"  [{'ok ' if got == want else 'FAIL'}] {label}")

    check("background script with no -u is advised",
          needs_advice("python replay.py .", True), True)
    check("the cd prefix real commands carry still matches",
          needs_advice('cd "D:/work/scratch" && python replay.py . > out.txt', True), True)
    check("-u clears it", needs_advice("python -u replay.py", True), False)
    check("PYTHONUNBUFFERED clears it",
          needs_advice("PYTHONUNBUFFERED=1 python replay.py", True), False)
    check("bypass marker clears it",
          needs_advice("# claude-bypass: unbuffered\npython r.py", True), False)
    check("foreground is left alone -- output is line-buffered to a terminal",
          needs_advice("python replay.py .", False), False)
    check("python -c one-liner is not a long run",
          needs_advice('python -c "print(1)"', True), False)
    check("python -m module has its own reporting",
          needs_advice("python -m pytest tests", True), False)
    check("a non-python command is not our business",
          needs_advice("rclone copy a b", True), False)
    check("interpreter given by full path still matches",
          needs_advice("C:/Python/python.exe replay.py", True), True)

    # The shapes that produced 459 false fires when this searched the whole string.
    check("python quoted inside a remote command is not ours",
          needs_advice('tailscale ssh ws@vm "docker exec app bash -c \'python run.py\'"', True), False)
    check("python named in a heredoc body is not ours",
          needs_advice("git commit -m \"$(cat <<'EOF'\nfix: python replay.py was slow\nEOF\n)\"", True), False)
    check("python after a pipe is not the head command",
          needs_advice("cat data.txt | python filter.py", True), False)

    print("\nSELF-TEST:", "PASS" if not failures else "FAIL")
    for f in failures:
        print("  -", f)
    return 0 if not failures else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
