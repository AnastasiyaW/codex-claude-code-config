# -*- coding: utf-8 -*-
"""The shared matcher must fire on operations, not on vocabulary.

Cases marked False are commands I actually ran this session that were blocked
while destroying nothing. Cases marked True must keep matching, or the repair is
a hole in a guard that exists to prevent a catastrophe.

The bypass cases hold the other shared parser to its docstring: every marker
form it documents is honoured, and a name that merely resembles the requested
one is not.
"""
import importlib.util
import os
import pathlib
import sys

HOOKS = pathlib.Path(os.environ.get("HOOKS_DIR", pathlib.Path(__file__).resolve().parents[1]))
MODULE = HOOKS / "safety_common.py"
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
    ("rm -rf /srv/scratch/data", True, "a real recursive delete"),
    ('psql -c "DROP TABLE prices"', True, "a real drop, quoted but executed by psql"),
    ("ssh host 'bash -s' <<'EOF'\nrm -rf /var/lib/thing\nEOF", True,
     "a here-doc executed as a remote shell really deletes"),
]

CASES.append((
    # This expectation was False in the first version, and an independent review
    # showed why that was wrong: `python -` EXECUTES what arrives on stdin, and
    # the same shape reaches psql, mysql and every other client that runs its
    # input. Exempting it bought a nicer workflow and cost the invariant. The
    # cost of keeping it in scope is mine to pay: write data files with an editor
    # rather than through an interpreter here-doc.
    "python - <<'PY'\ntext = 'the reboot history is in journalctl'\nopen('n.md','w').write(text)\nPY",
    True, "a here-doc read by python, which executes what it is given"))
CASES.append((
    "cat <<'NOTE' > note.md\nthe reboot history is in journalctl\nNOTE",
    False, "a here-doc read by cat, which cannot execute anything"))
CASES.append((
    "python - <<'PY'\nimport os\nos.system('reboot')\nPY",
    True, "the same shape, but this data really does run it"))

CASES.append((
    # Expected False in the first version. Under the inverted rule a consumer is
    # trusted only if it provably cannot act on what it receives, and a script
    # can do anything with its stdin - so this is scanned. The cost is a false
    # positive on `echo json | python script.py`; the alternative was eight
    # spellings of `| bash` walking straight through.
    "cd /tmp && echo '{\"cmd\":\"rm -rf /home\"}' | python guard.py",
    True, "piped into a script, which may act on what it reads"))
CASES.append((
    "cd /tmp && echo '{\"cmd\":\"rm -rf /home\"}' | cat",
    False, "piped into cat, which cannot"))
CASES.append((
    "cd /tmp && rm -rf /home", True,
    "a real delete that is not the first word on the line"))

CASES.append((
    """python -c "note = 'the restart history lives in journalctl'" """,
    False, "an inline script whose text merely names a dangerous word"))
CASES.append((
    """python -c "import os; os.system('shutdown -h now')" """,
    True, "an inline script that really runs one"))

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

# bypass_marker reads the opt-out every guard honours. Measured 2026-09-15: the
# documented `<!-- claude-bypass: NAME -->` form returned False, because the name
# class also accepts `-` and space and so swallowed the `--` of the closing `-->`
# into the last name. A name list hid it whenever NAME was not the last entry.
BYPASS_CASES = [
    ("# claude-bypass: incomplete-handoff", "incomplete-handoff", True, "shell comment form"),
    ("// claude-bypass: git-destructive", "git-destructive", True, "js/ts comment form"),
    ("<!-- claude-bypass: incomplete-handoff -->", "incomplete-handoff", True, "html/md comment form"),
    ("<!--claude-bypass:incomplete-handoff-->", "incomplete-handoff", True, "html/md form without spaces"),
    ("# claude-bypass: other, git-destructive, third", "git-destructive", True, "a name inside a list"),
    ("<!-- claude-bypass: bloat, incomplete-handoff -->", "incomplete-handoff", True,
     "the last name of an html/md list"),
    ("<!-- claude-bypass: all -->", "incomplete-handoff", True, "the all wildcard in html/md form"),
    ("# claude-bypass: git-destructive", "git", False, "a prefix of a hyphenated name is another name"),
    ("<!-- claude-bypass: incomplete-handoffs -->", "incomplete-handoff", False, "a longer name is another name"),
    ("claude-bypass: incomplete-handoff", "incomplete-handoff", False, "text without a comment opener"),
]

print()
bypass_failures = []
for content, name, expected, why in BYPASS_CASES:
    got = sc.bypass_marker(content, name)
    if got != expected:
        bypass_failures.append((why, expected, got))
    print(f"  {'ok  ' if got == expected else 'FAIL'} expected={'honoured' if expected else 'ignored':<8} "
          f"got={'honoured' if got else 'ignored':<8} {name:<18} {content[:52]}")

if failures or bypass_failures or literal is None:
    for why, expected, hit in failures:
        print(f"  - {why}: expected {'block' if expected else 'pass'}, got {'block' if hit else 'pass'}")
    for why, expected, got in bypass_failures:
        print(f"  - {why}: expected {'honoured' if expected else 'ignored'}, got {'honoured' if got else 'ignored'}")
    sys.exit(1)
print(f"all {len(CASES) + len(BYPASS_CASES)} cases correct")
