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
        if c2 == "NO" and t not in local_only:
            gaps.append(t)
    print(f"  {t:<32}{c1:>8}{c2:>8}   {note}")

print(f"\n  routes pointing at nothing on Codex (excluding declared local-only): "
      f"{gaps or 'none'}")
