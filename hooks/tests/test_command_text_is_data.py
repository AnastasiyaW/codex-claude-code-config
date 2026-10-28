# -*- coding: utf-8 -*-
"""Message text is data; a wrapped or substituted command is not.

PROBLEMS.md 2026-10-28 09:30 (transfer guard) and 2026-09-26 14:40 (deletion
guard). The DATA cases were measured as blocked on 2026-10-28: a multi-line
commit message naming Copy-Item/robocopy, one naming rmdir, and a printf of
text into a file. The CODE cases must stay blocked: a substitution inside the
message still runs, and so does a delete inside a wrapper.

Runs the guards in process (decide / _transfer_kind) so a mutation probe of
safety_common can afford one run per mutant.
"""
import importlib.util
import os
import pathlib
import sys

HOOKS = pathlib.Path(os.environ.get("HOOKS_DIR", pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(HOOKS))


def load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, HOOKS / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sc = load("safety_common", "safety_common.py")
sys.modules["safety_common"] = sc
sc._CURRENT_EVENT = {"tool_name": "Bash"}  # what read_event() sets for a Bash tool call
hcg = load("hcg", "human-confirmation-guard.py")
tcg = load("tcg", "transfer-contract-guard.py")

WORDS = ("rmdir", "robocopy", "copy-item", "remove-item")

# Text only: both guards pass, and executable_text no longer shows the words.
DATA = [
    ('git commit -m "transfer guard: message text\n\nCopy-Item/robocopy are named in docs"',
     "measured 2026-10-28: multi-line message naming transfer tools"),
    ('git commit -m "hcg: rmdir handling\n\nthe rmdir pattern\nfires on text"',
     "measured 2026-10-28: multi-line message naming rmdir"),
    ("printf '%s\\n' \"note about rmdir x and robocopy\" > notes.txt",
     "measured 2026-10-28: printf of text into a file"),
    ('git -C C:/repo commit -m "rmdir and robocopy in a message"', "-C before the subcommand"),
    ('git tag -a v1 -m "rmdir robocopy"', "a tag message"),
    ('git commit -m "title" -m "body names rmdir x\nand Remove-Item y"', "two -m, multi-line"),
    ('gh pr create --title "rmdir" --body "robocopy C:\\a C:\\b\nrmdir x"', "a PR body"),
    ("gh issue comment 5 --body 'Copy-Item a b\nrmdir c'", "an issue comment, single quotes"),
    ("printf '%s\\n' 'rmdir x' 'robocopy a b' > .claude/tmp/msg.txt && git commit -F .claude/tmp/msg.txt",
     "message file written then used by commit -F"),
    ('cd C:/repo && git add a.py && git commit -m "rmdir x\nrobocopy y"', "commit after cd and add"),
    ('echo "rmdir x" > notes.md', "echo into a file"),
]

# Code: the deletion guard (or, for transfers, the transfer guard) must block.
DELETE = [
    ('git commit -m "$(rm -rf /srv/data)"', "substitution inside the message runs"),
    ('git commit -m "`rm -rf /srv/data`"', "backticks inside the message run"),
    ('git commit -m "a\n$(rmdir /srv/data)\nb"', "substitution inside a multi-line message"),
    ('git commit -m "a\nb" && rmdir /srv/data', "a delete after the message"),
    ('git commit -m "a" ; rm -rf /srv/data', "a delete after ;"),
    ('git commit -m "rmdir /srv/data" | bash', "commit output fed to a shell"),
    ('git -c core.editor=x commit -m "rmdir /srv/data"', "-c can run code: not masked"),
    ('eval git commit -m "rmdir /srv/data"', "eval re-reads the message as code"),
    ('git commit -m "a\\" ; rmdir /srv/data ; echo "b"', "escaped quote: PowerShell reads it otherwise"),
    ("printf 'rmdir /srv/data' > x.sh && bash x.sh", "file written then run"),
    ("echo 'rmdir /srv/data' > /tmp/x.sh; sh /tmp/x.sh", "file written then run by sh"),
    ("printf 'rmdir /srv/data' > run.sh && bash ./*.sh", "file run through a glob"),
    ("printf 'rmdir /srv/data' > ~/.bashrc", "a shell startup file"),
    ("printf 'rmdir /srv/data' > .git/hooks/pre-commit && git commit -m x", "a git hook runs it"),
    ("printf 'rmdir /srv/data' > scripts/git-hooks/pre-push", "a hooks folder"),
    ("printf 'rmdir /srv/data' >> x.sh && git add x.sh && git commit -m x", "the file is used again"),
    ("printf 'rmdir /srv/data' > x.sh | bash", "printed into a pipe"),
    ("printf 'rmdir /srv/data' > $f", "target is a variable"),
    ("printf 'rmdir /srv/data' > x.sh 2> y.sh", "two outputs"),
    ("printf 'rmdir /srv/data' > x.sh && python x.sh", "an interpreter after it"),
    ("( printf 'rmdir /srv/data' > x.sh ) && bash x.sh", "inside a subshell"),
    ("bash -c 'rm -rf /srv/data'", "bash -c payload"),
    ('sh -c "rm -rf /srv/data"', "sh -c payload"),
    ("(rm -rf /srv/data)", "subshell"),
    ("{ rm -rf /srv/data; }", "group"),
    ("if true; then rm -rf /srv/data; fi", "if body"),
    ("echo /srv/data | xargs rm -rf", "xargs"),
    ("find /srv/data -exec rm -rf {} +", "find -exec"),
    ("env rm -rf /srv/data", "env"),
    ("nohup rm -rf /srv/data", "nohup"),
    ("busybox rm -rf /srv/data", "busybox"),
    ("\\rm -rf /srv/data", "leading backslash"),
    ("timeout 5 rm -rf /srv/data", "timeout"),
    ("nice rm -rf /srv/data", "nice"),
    ('powershell -c "del C:\\data\\x"', "powershell -c"),
    ('iex "ri C:\\data\\x"', "Invoke-Expression alias with the ri alias"),
    ("Invoke-Expression 'Remove-Item C:\\data\\x'", "Invoke-Expression"),
    ("unlink /srv/data/x", "unlink"),
    ("git commit -m 'msg\u2019 ; Remove-Item -Recurse C:\\data ; echo \u2018x'",
     "typographic quote: PowerShell closes the string there"),
    ('git commit -m "msg\u201d ; rmdir C:\\data ; echo \u201cx"', "typographic double quote"),
    ("printf 'rmdir /srv/data' > notes.txt && git add -A", "a clean filter may run what add picks up"),
    ("{ true; git tag -l --format='rm -rf /srv/data'; } | sh", "review: group output piped to a shell"),
    ("{\ngit commit --allow-empty -m 'x; rm -rf /srv/data'\n} | sh", "review: multi-line group piped"),
    ("exec > x.sh; git tag -l --format='rm -rf /srv/data'; bash x.sh", "exec rebinds stdout"),
    ("if true; then git tag -l --format='rm -rf /srv/data'; fi | sh", "if body piped"),
    ("printf -v GIT_EDITOR 'rm -rf /srv/data; true' > o.txt && git commit", "review: printf -v assigns"),
    ("cd .git/hooks && printf 'rm -rf /srv/data' > pre-commit && cd ../.. && git commit -m x",
     "review: hook reached through cd"),
    ("printf 'rm -rf /srv/data' > scripts/pre-commit && git commit -m x", "a custom hooksPath hook"),
    ("bash -x -c 'rm -rf /srv/data'", "bash flag before -c"),
    ("sh -ce 'rm -rf /srv/data'", "sh -ce"),
    ("bash --norc -c 'rm -rf /srv/data'", "bash --norc -c"),
    ('echo `"a ; Remove-Item -Recurse C:\\data ; echo "b', "PowerShell backtick-escaped quote opens no string"),
    ("python -c \"import shutil; shutil.rmtree('/srv/data')\"", "inline python"),
]
TRANSFER = [
    ('git commit -m "x" && robocopy C:\\a C:\\b', "a transfer after the message"),
    ("printf 'robocopy C:\\a C:\\b' > t.cmd && cmd /c t.cmd", "file written then run"),
    ('git commit -m "$(robocopy C:\\a C:\\b)"', "substitution in the message"),
]

failures = []
total = 0
for command, why in DATA:
    total += 1
    text = sc.executable_text(command).lower()
    allowed, hit = hcg.decide(command)
    kind = tcg._transfer_kind(command)
    shown = [w for w in WORDS if w in text]
    ok = allowed and kind is None and not shown
    if not ok:
        failures.append(f"DATA blocked/shown ({why}): hcg={allowed}/{hit} tcg={kind} words={shown}")
    print(f"  {'ok  ' if ok else 'FAIL'} data   {command.splitlines()[0][:64]}")
for command, why in DELETE:
    total += 1
    allowed, hit = hcg.decide(command)
    if allowed:
        failures.append(f"DELETE passed ({why}): {command!r}")
    print(f"  {'ok  ' if not allowed else 'FAIL'} delete {command.splitlines()[0][:64]}")
# The same text through the PowerShell tool: bash quote rules do not apply, so
# the whole-command mask stays off and the words remain visible.
sc._CURRENT_EVENT = {"tool_name": "PowerShell"}
for command, why in DATA[:3]:
    total += 1
    shown = [w for w in WORDS if w in sc.executable_text(command).lower()]
    if not shown:
        failures.append(f"POWERSHELL masked ({why}): {command!r}")
    print(f"  {'ok  ' if shown else 'FAIL'} pwsh   {command.splitlines()[0][:64]}")
sc._CURRENT_EVENT = {"tool_name": "Bash"}
for command, why in TRANSFER:
    total += 1
    kind = tcg._transfer_kind(command)
    if kind is None:
        failures.append(f"TRANSFER passed ({why}): {command!r}")
    print(f"  {'ok  ' if kind else 'FAIL'} xfer   {command.splitlines()[0][:64]}")

# Direct checks of the helpers, so a broken branch shows up as one named row.
def words(command):
    segments = sc._shell_words(command)
    return None if segments is None else [
        ([w["value"] for w in s["words"]], [(op, t["value"]) for op, t in s["redirects"]],
         s["depth"], s["sep"]) for s in segments]


def seg(command):
    return sc._shell_words(command)[0]


UNIT = [
    ("git commit", sc._git_subcommand, (["git", "commit"],), "commit"),
    ("git -C d", sc._git_subcommand, (["git", "-C", "d", "commit"],), "commit"),
    ("git --git-dir=", sc._git_subcommand, (["git", "--git-dir=x", "tag"],), "tag"),
    ("git --no-pager", sc._git_subcommand, (["git", "--no-pager", "log"],), "log"),
    ("git -c", sc._git_subcommand, (["git", "-c", "a=b", "commit"],), None),
    ("bare git", sc._git_subcommand, (["git"],), None),
    ("git -C no sub", sc._git_subcommand, (["git", "-C", "d"],), None),
    ("GIT.exe", sc._git_subcommand, (["GIT.exe", "commit"],), "commit"),
    ("not git", sc._git_subcommand, (["gh", "commit"],), None),
    ("empty", sc._git_subcommand, ([],), None),
    ("gh pr create", sc._is_message_command, (["gh", "pr", "create"],), True),
    ("gh.exe issue comment", sc._is_message_command, (["gh.exe", "issue", "comment"],), True),
    ("gh release edit", sc._is_message_command, (["gh", "release", "edit"],), True),
    ("gh pr view", sc._is_message_command, (["gh", "pr", "view"],), False),
    ("gh pr", sc._is_message_command, (["gh", "pr"],), False),
    ("gh repo create", sc._is_message_command, (["gh", "repo", "create"],), False),
    ("x pr create", sc._is_message_command, (["x", "pr", "create"],), False),
    ("git push", sc._is_message_command, (["git", "push"],), False),
    ("git tag", sc._is_message_command, (["git", "tag"],), True),
    ("input", sc._harmless_redirect, ("<", "x"), True),
    ("merge 1", sc._harmless_redirect, (">&", "1"), True),
    ("merge 2", sc._harmless_redirect, ("2>&", "2"), True),
    ("fd 3", sc._harmless_redirect, (">&", "3"), False),
    ("dev null", sc._harmless_redirect, (">", "/dev/null"), True),
    ("$NULL", sc._harmless_redirect, (">", "$NULL"), True),
    ("nul", sc._harmless_redirect, (">", "nul"), True),
    ("file", sc._harmless_redirect, (">", "f"), False),
    (">> 2", sc._harmless_redirect, (">>", "2"), False),
    ("plain", sc._plain_file_target, ("notes.txt",), True),
    ("nested", sc._plain_file_target, (".claude/tmp/msg.txt",), True),
    ("windows", sc._plain_file_target, ("C:\\r\\m.txt",), True),
    ("dotfile", sc._plain_file_target, (".bashrc",), False),
    ("in .git", sc._plain_file_target, ("a/.GIT/x",), False),
    ("in .husky", sc._plain_file_target, (".husky/x",), False),
    ("hooks dir", sc._plain_file_target, ("git-hooks/pre-push",), False),
    ("profile", sc._plain_file_target, ("my.profile.txt",), False),
    ("rc", sc._plain_file_target, ("zshrc",), False),
    ("variable", sc._plain_file_target, ("$f",), False),
    ("hook with extension", sc._plain_file_target, ("scripts/pre-commit.sh",), False),
    ("profile in a folder", sc._plain_file_target, ("a/my.profile.txt",), False),
    ("rc in a folder", sc._plain_file_target, ("dir/zshrc",), False),
    ("dotfile in a folder", sc._plain_file_target, ("dir/.env",), False),
    ("folder named like rc", sc._plain_file_target, ("src/notes.txt",), True),
    ("root", sc._plain_file_target, ("/",), False),
    ("no words", sc._cannot_run_a_file, ([],), True),
    ("git status", sc._cannot_run_a_file, (["git", "status"],), True),
    ("git add", sc._cannot_run_a_file, (["git", "add", "x"],), False),
    ("git -c status", sc._cannot_run_a_file, (["git", "-c", "x", "status"],), False),
    ("gh pr", sc._cannot_run_a_file, (["gh", "pr", "x"],), True),
    ("gh alone", sc._cannot_run_a_file, (["gh"],), False),
    ("gh alias", sc._cannot_run_a_file, (["gh", "alias"],), False),
    ("CD", sc._cannot_run_a_file, (["CD", "x"],), True),
    ("bash", sc._cannot_run_a_file, (["bash", "x"],), False),
    ("print >", sc._print_target, (seg("printf x > a.txt"),), "a.txt"),
    ("print >>", sc._print_target, (seg("printf x >> a.txt"),), "a.txt"),
    ("print 1>", sc._print_target, (seg("printf x 1> a.txt"),), "a.txt"),
    ("print 1>>", sc._print_target, (seg("printf x 1>> a.txt"),), "a.txt"),
    ("print 2>", sc._print_target, (seg("printf x 2> a.txt"),), None),
    ("print + merge", sc._print_target, (seg("printf x > a.txt 2>&1"),), "a.txt"),
    ("print two", sc._print_target, (seg("printf x > a.txt > b.txt"),), None),
    ("print none", sc._print_target, (seg("printf x"),), None),
    ("print rc", sc._print_target, (seg("printf x > .bashrc"),), None),
    ("print &>", sc._print_target, (seg("printf x &> a.txt"),), None),
    ("print >|", sc._print_target, (seg("printf x >| a.txt"),), None),
    ("-F file", sc._mentions, (seg("git commit -F msg.txt"), "msg.txt"), False),
    ("--file=", sc._mentions, (seg("git commit --file=msg.txt"), "msg.txt"), False),
    ("--body-file", sc._mentions, (seg("gh pr create --body-file MSG.txt"), "msg.txt"), False),
    ("-F first word", sc._mentions, (seg("msg.txt -F"), "msg.txt"), True),
    ("bash file", sc._mentions, (seg("bash msg.txt"), "msg.txt"), True),
    ("-m value", sc._mentions, (seg("git commit -m msg.txt"), "msg.txt"), True),
    ("redirect", sc._mentions, (seg("cat < msg.txt"), "msg.txt"), True),
    ("non-message -F", sc._mentions, (seg("bash -F msg.txt"), "msg.txt"), True),
    ("not named", sc._mentions, (seg("git status"), "msg.txt"), False),
    ("words", words, ('a "b c" d; e | f && g || h & i\nj',),
     [(["a", "b c", "d"], [], 0, ";"), (["e"], [], 0, "|"), (["f"], [], 0, "&&"), (["g"], [], 0, "||"),
      (["h"], [], 0, "&"), (["i"], [], 0, "\n"), (["j"], [], 0, "")]),
    ("depth", words, ("( a ) b",), [([], [], 0, "("), (["a"], [], 1, ")"), (["b"], [], 0, "")]),
    ("comment", words, ("a # b c\nd",), [(["a"], [], 0, "\n"), (["d"], [], 0, "")]),
    ("continuation", words, ("a \\\nb",), [(["a", "b"], [], 0, "")]),
    ("escaped space", words, ("a\\ b",), [(["a b"], [], 0, "")]),
    ("fd merge", words, ("a 2>&1",), [(["a"], [("2>&", "1")], 0, "")]),
    ("&>", words, ("a &>f",), [(["a"], [("&>", "f")], 0, "")]),
    (">|", words, ("a >|f",), [(["a"], [(">|", "f")], 0, "")]),
    (">>", words, ("a >>f",), [(["a"], [(">>", "f")], 0, "")]),
    ("x2>", words, ("x2>f",), [(["x2"], [(">", "f")], 0, "")]),
    ("'2'>", words, ("'2'>f",), [(["2"], [(">", "f")], 0, "")]),
    ("$VAR", words, ('a $b "$c"',), [(["a", "$b", "$c"], [], 0, "")]),
    ("cr", words, ("a\r\nb",), [(["a"], [], 0, "\n"), (["b"], [], 0, "")]),
    ("quote join", words, ("a'b'\"c\"d",), [(["abcd"], [], 0, "")]),
    ("escape in dq", words, ('"a\\\\" b',), [(["a\\\\", "b"], [], 0, "")]),
]
for bad in ["a $(b)", "a `b`", "a ${b}", "a $'x'", "a $[1]", "a <<EOF", "a <(b)", "a >(b)",
            'a "x\\"y"', "a \\'", "a \\\"", "a 'open", 'a "open', "a )", "( a", "a >", "a > > b",
            "a \\", '"$(b)"', '"${b}"', '"$[1]"', '"`b`"', "a >;"]:
    UNIT.append((f"unsure {bad!r}", words, (bad,), None))
spans = 'git commit -m "a" -m \'b\''
UNIT += [
    ("mask spans", sc._mask_message_data, (spans,), "git commit -m   -m  "),
    ("mask alias", sc._mask_message_data, ('alias x=y; git commit -m "rmdir"',), 'alias x=y; git commit -m "rmdir"'),
    ("mask redirect", sc._mask_message_data, ('git commit -m "r" > out.txt',), 'git commit -m "r" > out.txt'),
    ("mask merge", sc._mask_message_data, ('git commit -m "r" 2>&1',), "git commit -m   2>&1"),
    ("mask depth", sc._mask_message_data, ('( git commit -m "r" )',), '( git commit -m "r" )'),
    ("mask pipe", sc._mask_message_data, ('git commit -m "r" | cat',), 'git commit -m "r" | cat'),
    ("mask word 0", sc._mask_message_data, ("'git' commit -m 'r'",), "'git' commit -m  "),
    ("mask printf", sc._mask_message_data, ("printf 'r' > a.txt; git status",), "printf   > a.txt; git status"),
    ("mask printf other", sc._mask_message_data, ("printf 'r' > a.txt; bash b",), "printf 'r' > a.txt; bash b"),
    ("mask printf named", sc._mask_message_data, ("printf 'r' > a.txt; git log a.txt",),
     "printf 'r' > a.txt; git log a.txt"),
    ("mask not printer", sc._mask_message_data, ("cat 'r' > a.txt",), "cat 'r' > a.txt"),
    ("mask no target", sc._mask_message_data, ("printf 'r'",), "printf 'r'"),
    ("mask after cd", sc._mask_message_data, ("cd x && printf 'r' > a.txt",), "cd x && printf 'r' > a.txt"),
    ("mask quoted printer", sc._mask_message_data, ("'printf' 'r' > a.txt",), "'printf'   > a.txt"),
    ("mask name in folder", sc._mask_message_data, ("printf 'r' > d/x.sh; git log x.sh",),
     "printf 'r' > d/x.sh; git log x.sh"),
    ("mask printf -v", sc._mask_message_data, ("printf -v X 'r' > a.txt",), "printf -v X 'r' > a.txt"),
    ("mask echo -n", sc._mask_message_data, ("echo -n 'r' > a.txt",), "echo -n   > a.txt"),
    ("mask empty seg", sc._mask_message_data, ("; printf 'r' > a.txt",), ";printf   > a.txt"[0:1] + " printf   > a.txt"),
    ("mask two prints", sc._mask_message_data, ("echo 'a' > x.txt && echo 'b' > y.txt",),
     "echo   > x.txt && echo   > y.txt"),
    ("mask typographic", sc._mask_message_data, ("git commit -m 'r\u2019'",), "git commit -m 'r\u2019'"),
]
for name, function, args, expected in UNIT:
    total += 1
    try:
        got = function(*args)
    except Exception as exc:  # a crash is a wrong answer, not an aborted suite
        got = f"raised {type(exc).__name__}"
    if got != expected:
        failures.append(f"UNIT {name}: expected {expected!r}, got {got!r}")
sc._CURRENT_EVENT = {}
total += 1
if sc._mask_message_data('git commit -m "r"') != 'git commit -m "r"':
    failures.append("UNIT no event: masked without a Bash tool event")

print()
if failures:
    print(f"{len(failures)} of {total} cases wrong:")
    for line in failures:
        print("  - " + line)
    sys.exit(1)
print(f"all {total} cases correct")
