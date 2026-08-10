"""Every marker in the public repo tree at once, tracked and untracked, with the verdict.

The repo scanner stops at the first hit, so fixing one and re-running is a retry loop
that reports progress it has not made. This lists all of them in one pass and separates
the two states that need different responses:

  TRACKED   -- already on GitHub. Fixing the file does not unpublish the history.
  UNTRACKED -- present in the working tree only. One `git add -A` publishes it, and
               pre-push cannot see it, because pre-push scans the diff.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path.home() / ".claude" / "claude-code-config"
ROUTING = Path.home() / ".claude" / "claude-code-private" / "routing.json"

markers = json.loads(ROUTING.read_text(encoding="utf-8-sig")).get("privacy_markers", [])
exempt = set(json.loads(ROUTING.read_text(encoding="utf-8-sig")).get("marker_exempt_paths", []))
print(f"{len(markers)} markers, {len(exempt)} exempt paths\n")

tracked = set(subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True,
                             text=True, encoding="utf-8").stdout.split("\n"))

rows = []
for p in REPO.rglob("*"):
    if not p.is_file() or ".git" in p.parts or "__pycache__" in p.parts:
        continue
    rel = p.relative_to(REPO).as_posix()
    if rel in exempt or Path(rel).name in exempt:
        continue
    try:
        txt = p.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        continue
    hits = set()
    for m in markers:
        try:
            if re.search(m, txt, re.I):
                hits.add(m)
            if re.search(m, rel, re.I):
                hits.add(m + " (in the FILENAME)")
        except re.error:
            continue
    if hits:
        rows.append((rel in tracked, rel, sorted(hits)))

pub = [r for r in rows if r[0]]
loc = [r for r in rows if not r[0]]

print(f"=== TRACKED and therefore already on GitHub: {len(pub)} ===")
for _, rel, hits in pub:
    print(f"  {rel}")
    print(f"      {', '.join(hits)}")
print("  none" if not pub else "")

print(f"=== UNTRACKED, one `git add -A` from being published: {len(loc)} ===")
for _, rel, hits in loc:
    print(f"  {rel}")
    print(f"      {', '.join(hits)}")
print("  none" if not loc else "")

print(f"\nTOTAL {len(rows)} file(s) carrying a private marker in the public repo tree")
