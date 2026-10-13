"""One Codex hook entry per event that runs every configured handler itself.

Why: Codex on Windows starts every hook handler as `pwsh -NoProfile -Command <command>`. Measured 2026-10-13 on
the owner's PC: pwsh takes 8-25 s to start under load, Codex has 48 PreToolUse handlers (23 for a shell command),
so one shell command waited 3-5 min and Astra abandoned it after 30 s ("command returned no output"). Run through
`cmd` the same handlers take 0.1-0.5 s each (23 in 4.9 s). This dispatcher is the only thing Codex starts through
pwsh; it runs the handlers in parallel through cmd and merges their verdicts in configuration order, so every
guard still runs.

    python codex_hook_dispatch.py <EventName>        (stdin: the Codex hook payload)

Handlers come from ~/.codex/hooks.dispatch.json (same schema as hooks.json; written by
scripts/codex_hook_dispatch_install.py). Matchers: a group's `matcher` is a regex that must fullmatch the payload's
tool_name (tool events); no matcher or "*" = every call. Merge rules (Claude/Codex hook protocol):
  exit 2                                  -> block: its stderr is printed, exit 2 (first blocking handler in list order)
  JSON decision "block" / continue false /
  permissionDecision deny|ask             -> that JSON is printed as is, exit 0
  JSON additionalContext / systemMessage  -> concatenated into one JSON
  plain stdout                            -> added to additionalContext (events that accept context), else echoed
  other exit codes, timeouts              -> non-blocking: noted on stderr, the next handler runs
A handler that cannot be found or crashes is reported, never silently treated as passed.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DISPATCH = Path(os.environ.get("CODEX_HOOK_DISPATCH_FILE", Path.home() / ".codex" / "hooks.dispatch.json"))
# exit 2 blocks only where the protocol says so; elsewhere (SessionStart, PreCompact, SubagentStart) it is a
# reported error, and treating it as a block dropped every other handler's context (measured 2026-10-13)
EXIT2_BLOCKS = {"PreToolUse", "PostToolUse", "UserPromptSubmit", "Stop", "SubagentStop"}
CONTEXT_EVENTS = {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "SubagentStart"}
LOG = Path.home() / ".claude" / "logs" / "codex-hook-dispatch.jsonl"


def _matches(matcher: str | None, tool: str | None) -> bool:
    if not matcher or matcher == "*" or tool is None:
        return True
    try:
        return re.fullmatch(matcher, tool) is not None
    except re.error:
        return matcher == tool


def _blocking(obj: dict) -> bool:
    spec = obj.get("hookSpecificOutput") or {}
    return (obj.get("decision") == "block" or obj.get("continue") is False
            or spec.get("permissionDecision") in ("deny", "ask"))


def main() -> int:
    event = sys.argv[1]
    raw = sys.stdin.buffer.read()
    try:
        payload = json.loads(raw.decode("utf-8-sig") or "{}")
    except ValueError:
        payload = {}
    tool = payload.get("tool_name")
    try:
        groups = json.loads(DISPATCH.read_text(encoding="utf-8-sig"))["hooks"].get(event, [])
    except (OSError, ValueError, KeyError) as exc:      # no handler list = guards cannot run: say so loudly
        print(f"codex_hook_dispatch: handler list {DISPATCH} unreadable ({exc}); {event} guards NOT run", file=sys.stderr)
        return 1
    handlers = [h for g in groups if _matches(g.get("matcher"), tool) for h in g.get("hooks", [])]

    def run(handler):
        cmd = handler.get("command", "")
        t0 = time.time()
        try:
            r = subprocess.run(cmd, input=raw, capture_output=True, shell=True,
                               timeout=float(handler.get("timeout") or 600))
            return cmd, r.returncode, r.stdout.decode("utf-8", "replace").strip(),                 r.stderr.decode("utf-8", "replace").strip(), round(time.time() - t0, 2)
        except subprocess.TimeoutExpired:
            return cmd, "timeout", "", "", round(time.time() - t0, 2)

    # In parallel, as Claude Code runs hooks: 23 sequential handlers took 49 s on the loaded PC (2026-10-13).
    # Verdicts are read back in configuration order, so the first blocking handler in the list wins.
    with ThreadPoolExecutor(max_workers=max(1, min(32, len(handlers)))) as pool:
        results = list(pool.map(run, handlers))
    context, messages, allow, notes = [], [], None, []
    ran = [(c[-60:], rc, dt) for c, rc, _, _, dt in results]
    for cmd, rc, out, err, _ in results:
        if rc == "timeout":
            notes.append(f"timeout: {cmd}")
            continue
        if rc == 2 and event not in EXIT2_BLOCKS:
            notes.append(f"exit 2 (not blocking for {event}): {cmd}: {err[:300]}")
            continue
        if rc == 2:
            _log(event, tool, ran, "block-exit2")
            sys.stderr.write(err or f"blocked by {cmd}")
            return 2
        if rc != 0:
            notes.append(f"exit {rc}: {cmd}: {err[:300]}")
            continue
        if not out:
            continue
        try:
            obj = json.loads(out)
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            if _blocking(obj):
                _log(event, tool, ran, "block-json")
                sys.stdout.write(out)
                return 0
            spec = obj.get("hookSpecificOutput") or {}
            if spec.get("additionalContext"):
                context.append(str(spec["additionalContext"]))
            if spec.get("permissionDecision") == "allow" and allow is None:
                allow = spec
            if obj.get("systemMessage"):
                messages.append(str(obj["systemMessage"]))
        else:
            context.append(out)
    _log(event, tool, ran, "pass")
    for n in notes:
        print(f"codex_hook_dispatch: {n}", file=sys.stderr)
    if not (context or messages or allow):
        return 0
    if event not in CONTEXT_EVENTS and not messages and not allow:
        sys.stdout.write("\n\n".join(context))
        return 0
    result: dict = {}
    spec_out: dict = {"hookEventName": event}
    if context and event in CONTEXT_EVENTS:
        spec_out["additionalContext"] = "\n\n".join(context)
    if allow:
        spec_out.update({k: v for k, v in allow.items() if k.startswith("permission")})
    if len(spec_out) > 1:
        result["hookSpecificOutput"] = spec_out
    if messages:
        result["systemMessage"] = "\n".join(messages)
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return 0


def _log(event, tool, ran, verdict):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event, "tool": tool,
                                "verdict": verdict, "handlers": len(ran),
                                "seconds": round(sum(x[2] for x in ran), 2)}) + "\n")
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(main())
