# -*- coding: utf-8 -*-
"""Every evasion an independent reviewer found, turned into a test.

The first version of the scoping repair was REJECTED on review: 17 of 20 probes
were regressions - commands the raw scan caught and the scoped scan missed. The
reviewer's point about the original test suite was the sharper one: every
"must still block" case was the naive spelling of the thing being masked, so the
suite was evidence about the forms its author imagined.

These are the forms the author did not imagine. All must be seen as dangerous.
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

DESTRUCTIVE = [
    r"\brm\s+-[a-z]*r[a-z]*f?\b", r"\breboot\b", r"\bshutdown\s+",
    r"\bDROP\s+TABLE\b", r"\bDELETE\s+FROM\b", r"\bgit\s+reset\s+--hard\b",
    r"\bkubectl\s+delete\b", r"\bscp\b", r"\brsync\b", r"\bsystemctl\s+stop\b",
    r"\bgit\s+push\s+--force\b", r"\bRemove-Item\b",
]

# Finding 1: the masked argument is executed by the rest of the pipeline.
PIPED_INTO_A_SHELL = [
    "echo 'rm -rf /srv/data' | bash",
    "printf 'rm -rf /srv/data\\n' | sh",
    "echo 'git reset --hard origin/main' | sh",
    "echo 'kubectl delete ns prod' | bash",
    "echo 'scp /etc/passwd host:/tmp/' | bash",
    "echo '/srv/data' | xargs rm -rf",
    "Write-Output 'Remove-Item -Recurse -Force C:\\data' | Invoke-Expression",
]

# Finding 2: a substitution inside the quoted run executes first.
SUBSTITUTION_INSIDE = [
    'echo "$(rm -rf /srv/data)"',
    "echo \"`rm -rf /srv/data`\"",
    'echo "$(git reset --hard origin/main)"',
    'Write-Host "$(Remove-Item -Recurse -Force C:\\data)"',
]

# Finding 3: awk and sed execute shell commands.
AWK_AND_SED = [
    "awk 'BEGIN{system(\"rm -rf /srv/data\")}'",
    "awk 'BEGIN{system(\"systemctl stop nginx\")}'",
    "awk 'BEGIN{system(\"scp /etc/passwd host:/tmp/\")}'",
]

# Finding 4: a here-doc read by a database client is executed by it.
HEREDOC_TO_A_CLIENT = [
    "psql -q mydb <<SQL\nDROP TABLE prices;\nSQL",
    "mysql app <<'EOSQL'\nDELETE FROM users;\nEOSQL",
    "sqlite3 index.db <<-SQL\n\tDROP TABLE shop;\n\tSQL",
    "psql mydb <<SQL\nDROP TABLE prices;",          # tag never closes
]

# Finding 5: inline scripts in every language shell out.
INLINE_SCRIPTS = [
    "perl -e 'system(\"rm -rf /srv/data\")'",
    "ruby -e 'system(\"rm -rf /srv/data\")'",
    'node -e \'require("child_process").execSync("rm -rf /srv/data")\'',
    "perl -e 'system(\"git push --force origin main\")'",
    "perl -e 'system(\"rsync -a /src/ host:/dst/\")'",
    "python -c \"import os; os.system('rm -rf /srv/data')\"",
]

# A gap this suite deliberately does NOT hide: `python -c "import os;
# os.remove(path)"` is missed - by the scoped scan and by the raw one equally,
# because no pattern in any guard's list describes a python-level delete. That
# is a coverage hole in the pattern lists, not in the scoping, and pretending
# otherwise by writing a passing assertion around it would be the kind of green
# test this file exists to argue against.

# Finding 6: a bare & separates commands, and echo=1 is not echo.
SEPARATORS = [
    "echo x & sh -c 'rm -rf /srv/data'",
    "echo=1 sh -c 'rm -rf /srv/data'",
]

GROUPS = [
    ("piped into a shell", PIPED_INTO_A_SHELL),
    ("substitution inside the quotes", SUBSTITUTION_INSIDE),
    ("awk and sed execute", AWK_AND_SED),
    ("here-doc to a client that executes it", HEREDOC_TO_A_CLIENT),
    ("inline scripts that shell out", INLINE_SCRIPTS),
    ("separators and lookalike commands", SEPARATORS),
]

# The false positives the scoping exists to remove must still pass.
STILL_INERT = [
    "# Reason: the reboot history is read with journalctl\nuptime -p",
    'grep -n "rm -rf" /var/log/history',
    'echo "=== boots and shutdown history ==="',
    "cat <<'NOTE' > note.md\nrm -rf is dangerous, do not run it\nNOTE",
]

failures = []
for label, group in GROUPS:
    for command in group:
        seen = sc.any_match(command, DESTRUCTIVE, command=True) is not None
        if not seen:
            failures.append((label, command))
        first = command.splitlines()[0][:58]
        print(f"  {'ok  ' if seen else 'MISS'} {label:<38} {first}")

print()
for command in STILL_INERT:
    seen = sc.any_match(command, DESTRUCTIVE, command=True) is not None
    if seen:
        failures.append(("a harmless command must still pass", command))
    print(f"  {'ok  ' if not seen else 'FALSE POSITIVE'} inert: {command.splitlines()[0][:52]}")

print()
if failures:
    print(f"{len(failures)} evasion(s) still slip through:")
    for label, command in failures[:8]:
        print(f"  - {label}: {command.splitlines()[0][:70]}")
    sys.exit(1)
total = sum(len(g) for _, g in GROUPS) + len(STILL_INERT)
print(f"all {total} adversarial cases correct")
