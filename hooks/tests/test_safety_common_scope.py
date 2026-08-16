# -*- coding: utf-8 -*-
"""The shared matcher must fire on operations, not on vocabulary.

Cases marked False are commands I actually ran this session that were blocked
while destroying nothing. Cases marked True must keep matching, or the repair is
a hole in a guard that exists to prevent a catastrophe.
"""
import importlib.util
import pathlib
import sys

MODULE = pathlib.Path.home() / ".claude" / "claude-code-config" / "hooks" / "safety_common.py"
spec = importlib.util.spec_from_file_location("safety_common", MODULE)
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)

DESTRUCTIVE = [r"\brm\s+-[a-z]*r[a-z]*f", r"\breboot\b", r"\bshutdown\s+", r"\bDROP\s+TABLE\b"]

CASES = [
    ("# Reason: the reboot history is read with journalctl\nuptime -p", False,
     "the word sits in the agent's own comment"),
    ('echo "=== boots and shutdown history ==="\njournalctl --list-boots', False,
     "the word sits inside an echo label"),
    ('grep -n "reboot" /var/log/syslog', False,
     "searching a log for the word destroys nothing"),

    ("sudo reboot", True, "a real restart"),
    ("shutdown -h now", True, "a real halt"),
    ("rm -rf /home/example/data", True, "a real recursive delete"),
    ('psql -c "DROP TABLE prices"', True, "a real drop, quoted but executed by psql"),
    ("ssh host 'bash -s' <<'EOF'\nrm -rf /var/lib/thing\nEOF", True,
     "a here-doc executed as a remote shell really deletes"),
]

CASES.append((
    "python - <<'PY'\ntext = 'the reboot history is in journalctl'\nopen('n.md','w').write(text)\nPY",
    False, "a python here-doc whose data merely mentions the word"))
CASES.append((
    "python - <<'PY'\nimport os\nos.system('reboot')\nPY",
    True, "the same shape, but this data really does run it"))

CASES.append((
    "cd /tmp && echo '{\"cmd\":\"rm -rf /home\"}' | python guard.py",
    False, "the phrase inside an echo that is not the first word on the line"))
CASES.append((
    "cd /tmp && rm -rf /home", True,
    "a real delete that is not the first word on the line"))

failures = []
for command, expected, why in CASES:
    hit = sc.any_match(command, DESTRUCTIVE, command=True) is not None
    ok = hit == expected
    if not ok:
        failures.append((why, expected, hit))
    print(f"  {'ok  ' if ok else 'FAIL'} expected={'blocks' if expected else 'passes':<7} "
          f"got={'blocks' if hit else 'passes':<7} {command.splitlines()[0][:58]}")

print()
literal = sc.any_match('echo "reboot"', DESTRUCTIVE)
print(f"  prose scanning unchanged by default (still matches): {literal is not None}")
if failures or literal is None:
    for why, expected, hit in failures:
        print(f"  - {why}: expected {'block' if expected else 'pass'}, got {'block' if hit else 'pass'}")
    sys.exit(1)
print(f"all {len(CASES)} cases correct")
