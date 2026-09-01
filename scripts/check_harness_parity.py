"""Do both harnesses actually respond, and does every route resolve on each side?

Presence in a config is not behaviour -- that is the failure this whole week keeps
producing. So: run each newly wired hook on a real event, and check every router
target against the skills each harness can actually read.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HOME = Path.home()
CFG = HOME / ".claude" / "claude-code-config"
CLAUDE_CFG = HOME / ".claude" / "settings.json"
CODEX_CFG = HOME / ".codex" / "hooks.json"

# Asymmetries that are meant. The reason is the point: an allowlist without one is
# where a real gap hides, and this file exists because a gap hid in a weaker check.
INTENTIONAL = {
    ("codex", "Stop", "*", "conversation-history-github-sync.py"):
        "Codex keeps its own conversation-history archive; Claude transcripts go elsewhere",
    ("claude", "PreToolUse", "Task", "agent-skill-contract.py"):
        "Claude exposes Task before launch, so it can bind the exact child prompt to curated skill routing",
    ("claude", "SessionStart", "startup|resume|clear|compact", "benjamin-plus-inject.py"):
        "Claude loses injected session context on these lifecycle events; Codex receives the same policy through its native AGENTS context",
    ("codex", "SubagentStart", "*", "subagent-skill-context.py"):
        "Codex exposes only native subagent lifecycle events, so it injects universal source and skill discipline after launch",
    ("codex", "SubagentStop", "*", "subagent-evidence-receipt.py"):
        "Codex exposes the child final message at SubagentStop; Claude enforces the complementary prompt-bound contract before Task launch",
}

_GATE = re.compile(
    r"""tool_name"?\)?\s*(?P<op>not\s+in|in|==|!=)\s*(?P<val>\{[^}]*\}|\([^)]*\)|"[^"]*")""")
_NAME = re.compile(r'"([A-Za-z_][A-Za-z0-9_]*)"')
KNOWN_TOOLS = ["Bash", "PowerShell", "Read", "Write", "Edit", "MultiEdit", "Glob", "Grep",
               "WebFetch", "WebSearch", "NotebookEdit", "Task", "AskUserQuestion"]


def triples(path):
    """(event, matcher, script) for one harness.

    Matcher included deliberately. A (event, script) comparison called Codex and
    Claude identical on 2026-08-04 while dependency-currency-guard was wired to
    PreToolUse/Bash on one and PreToolUse/Write|Edit|MultiEdit on the other -- each
    harness had half the coverage, and the Codex half could never fire at all.
    """
    cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    return {(event, group.get("matcher") or "*", script)
            for event, groups in (cfg.get("hooks") or {}).items()
            for group in groups
            for hook in group.get("hooks", [])
            for script in re.findall(r"([\w.\-]+\.py)", hook.get("command", ""))}


def wired_paths(path):
    cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    return {p for groups in (cfg.get("hooks") or {}).values() for group in groups
            for hook in group.get("hooks", [])
            for p in re.findall(r"([A-Za-z]:[^\"']+?\.py)", hook.get("command", ""))}


def accepted_tools(source):
    """Tools a hook can act on, or None when it declares no gate.

    The idiom here is `if tool_name not in (...): return 0`, which ACCEPTS the named
    tools -- the negation is in the rejection, not in the list. Reading that backwards
    inverts the whole report, so the sense is decided by whether the body returns.
    """
    match = _GATE.search(source)
    if not match:
        return None
    names = set(_NAME.findall(match.group("val")))
    if not names:
        return None
    op = re.sub(r"\s+", " ", match.group("op"))
    tail = source[match.end():match.end() + 80]
    if op in ("in", "==") and re.search(r"^\s*:?\s*return\b", tail):
        return {t for t in KNOWN_TOOLS if t not in names}
    return names


def matcher_matches(matcher, tool):
    if matcher in ("*", ""):
        return True
    try:
        return re.fullmatch(matcher, tool) is not None or tool in matcher.split("|")
    except re.error:
        return tool in matcher.split("|")


def _self_test():
    fails = []

    def want(label, got, expected):
        if got != expected:
            fails.append(f"{label}: {got!r} != {expected!r}")
        print(f"  [{'ok ' if got == expected else 'FAIL'}] {label}")

    want("early-return gate accepts exactly the named tools",
         accepted_tools('if event.get("tool_name") not in ("Write", "Edit"): return 0'),
         {"Write", "Edit"})
    want("a hook that returns on != Bash accepts only Bash",
         accepted_tools('if event.get("tool_name") != "Bash": return 0'), {"Bash"})
    want("gate on == is read as that single tool",
         accepted_tools('if tool_name == "Edit":'), {"Edit"})
    want("no gate declared -> None", accepted_tools("def main(): return 0"), None)
    gate = accepted_tools((CFG / "hooks" / "dependency-currency-guard.py")
                          .read_text(encoding="utf-8")) or set()
    want("the real dependency guard reads as Write/Edit/MultiEdit",
         gate, {"Write", "Edit", "MultiEdit"})
    # The regression this section exists for.
    want("the 2026-08-04 Codex wiring is seen as a no-op",
         any(matcher_matches("Bash", t) for t in gate), False)
    want("the corrected wiring is not flagged",
         any(matcher_matches("Write|Edit|MultiEdit", t) for t in gate), True)
    print("\nSELF-TEST:", "PASS" if not fails else "FAIL")
    for f in fails:
        print("  -", f)
    return 0 if not fails else 1


if "--self-test" in sys.argv:
    sys.exit(_self_test())

print("=== 1. do the new hooks RESPOND (not just appear in config) ===")
with tempfile.TemporaryDirectory() as td:
    big = Path(td) / "big.py"
    big.write_text("\n".join(f"x{i} = {i}" for i in range(900)), encoding="utf-8")
    ev = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(big)}})
    r = subprocess.run([sys.executable, str(CFG / "hooks" / "module-shape-advisor.py")],
                       input=ev, capture_output=True, text=True, encoding="utf-8")
    spoke = "[shape]" in (r.stderr or "")
    print(f"  module-shape-advisor      exit={r.returncode}  spoke={spoke}")

    man = Path(td) / "requirements.txt"
    man.write_text("torch==1.7.1\n", encoding="utf-8")
    ev = json.dumps({"tool_name": "Write",
                     "tool_input": {"file_path": str(man), "content": "torch==1.7.1\n"}})
    r2 = subprocess.run([sys.executable, str(CFG / "hooks" / "dependency-currency-guard.py")],
                        input=ev, capture_output=True, text=True, encoding="utf-8")
    out = (r2.stdout or "") + (r2.stderr or "")
    print(f"  dependency-currency-guard exit={r2.returncode}  "
          f"reacted={'torch' in out or 'block' in out.lower()}")

print("\n=== 2. every router target resolves on each harness ===")
router = (CFG / "hooks" / "keyword-skill-router.py").read_text(encoding="utf-8")
targets = sorted(set(re.findall(r'"skill"\s*:\s*"([^"]+)"', router)))
local_only = set(re.findall(r'LOCAL_ONLY_SKILLS\s*=\s*\{([^}]*)\}', router, re.S))
local_only = set(re.findall(r'"([^"]+)"', local_only.pop())) if local_only else set()

claude = {p.name for p in (HOME / ".claude" / "skills").iterdir() if p.is_dir()}
codex = {p.name for p in (HOME / ".codex" / "skills").iterdir() if p.is_dir()}

print(f"  {'route target':<32}{'Claude':>8}{'Codex':>8}   note")
gaps = []
for t in targets:
    if ":" in t:
        note = "plugin-namespaced, resolves where installed"
        c1 = c2 = "n/a"
    else:
        c1 = "yes" if t in claude else "NO"
        c2 = "yes" if t in codex else "NO"
        note = "local-only by declaration" if t in local_only else ""
        # Both directions. Looking only at Codex hid `testing-strategy`, which lived
        # in ~/.codex/skills alone: the shared router pointed at it and it resolved
        # to nothing on Claude. A one-way parity check is not a parity check.
        if c2 == "NO" and t not in local_only:
            gaps.append(f"{t} (missing on Codex)")
        if c1 == "NO":
            gaps.append(f"{t} (missing on Claude)")
    print(f"  {t:<32}{c1:>8}{c2:>8}   {note}")

print(f"\n  routes pointing at nothing (excluding declared local-only): {gaps or 'none'}")

print("\n=== 3. same hooks on the same TRIGGERS (event, matcher, script) ===")
problems = [f"router target resolves nowhere: {g}" for g in gaps]
claude_t, codex_t = triples(CLAUDE_CFG), triples(CODEX_CFG)
print(f"  shared triples: {len(claude_t & codex_t)}")
for label, only in (("claude", claude_t - codex_t), ("codex", codex_t - claude_t)):
    for event, matcher, script in sorted(only):
        reason = INTENTIONAL.get((label, event, matcher, script))
        print(f"  {label}-only {event}[{matcher}] {script} -- {reason or 'NO REASON RECORDED'}")
        if not reason:
            problems.append(f"{label}-only with no recorded reason: {event}[{matcher}] {script}")

print("\n=== 4. no wiring that cannot fire ===")
for event, matcher, script in sorted(claude_t | codex_t):
    source = None
    for base in (CFG / "hooks", HOME / ".claude" / "private-hooks"):
        if (base / script).exists():
            source = (base / script).read_text(encoding="utf-8", errors="replace")
            break
    if source is None:
        continue
    tools = accepted_tools(source)
    if tools and not any(matcher_matches(matcher, t) for t in tools):
        problems.append(f"no-op wiring: {event}[{matcher}] {script} only acts on "
                        f"{sorted(tools)}")
print(f"  checked {len(claude_t | codex_t)} triples")

print("\n=== 5. every wired script exists ===")
for label, paths in (("claude", wired_paths(CLAUDE_CFG)), ("codex", wired_paths(CODEX_CFG))):
    for p in sorted(paths):
        if not Path(p).exists():
            problems.append(f"{label}: wired but missing on disk -- {p}")
print(f"  checked {len(wired_paths(CLAUDE_CFG) | wired_paths(CODEX_CFG))} paths")

if problems:
    print(f"\nPROBLEMS ({len(problems)}):")
    for p in problems:
        print(f"  - {p}")
    sys.exit(1)
print("\nOK: both harnesses wire the same hooks to the same triggers, and each can fire.")
