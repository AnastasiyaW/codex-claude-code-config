#!/usr/bin/env python3
"""PreToolUse (Bash, Write, Edit, MultiEdit): no secret material in world-readable temp files.

ADR-0007 F1 (happyin-workspace). Policy `secrets-as-data` lets agents use secrets freely; what it does not allow is
leaving them where any process on the host can read them. Measured 2026-10-24: a task script pulled a prod
encryption key out of `docker inspect` and wrote it into `/tmp/<dir>/proof.env` with default permissions — found
only because an unrelated review happened to read that file.

Blocks:
  * Bash that redirects/tees/copies into a temp location (/tmp, /var/tmp, $TMPDIR, D:/tmp, %TEMP%) while handling
    secret material (a variable or env key named *KEY/*SECRET/*TOKEN/*PASSWORD/*CREDENTIAL, `docker inspect`,
    `printenv`, `.env`, `~/.secrets`), unless it restricts permissions first (`umask 077`, `chmod 600/400/go-rwx`,
    `install -m 600`, `mktemp`).
  * Write/Edit of a temp-location file whose content carries a credential literal (PEM private key, GitHub/Anthropic/
    AWS/Slack token shapes, `*_KEY=<hex>`, `password=`).

Bypass: `# claude-bypass: secret-on-disk` with a `# Reason:` line, or CLAUDE_ALLOW_SECRET_ON_DISK=1.
Self-test: `python secret-on-disk-guard.py --self-test` (exit 0 = every case as expected, 1 = a case wrong).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from safety_common import allow, bash_command, block, bypass, file_path, log, read_event  # noqa: E402

TEMP = r"(?:/tmp/|/var/tmp/|\$\{?TMPDIR\}?/|\$\{?TEMP\}?|%TEMP%|[A-Za-z]:[\\/]+(?:tmp|temp)[\\/]|/[a-z]/tmp/|\\AppData\\Local\\Temp\\)"
# A write into temp: redirection, tee, cp/mv/install target, or an assignment of a temp path that is then written.
WRITE_INTO_TEMP = [
    rf">>?\s*[\"']?{TEMP}",
    rf"\btee\s+(?:-a\s+)?[\"']?{TEMP}",
    rf"\b(?:cp|mv|install)\b[^;&|\n]*\s[\"']?{TEMP}\S*\s*(?:$|[;&|])",
    rf"\b[A-Za-z_][A-Za-z0-9_]*=[\"']?{TEMP}",
]
SECRET_SOURCE = {
    "переменная с ключом/токеном/паролем": r"\$\{?[A-Za-z_]*(?:KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL)[A-Za-z0-9_]*\}?",
    "присваивание ключа/токена": r"\b[A-Z][A-Z0-9_]*(?:_KEY|_SECRET|_TOKEN|_PASSWORD|_PASSWD)(?:_[A-Z0-9]+)*=",
    "docker inspect (окружение контейнера)": r"\bdocker\s+inspect\b",
    "printenv": r"\bprintenv\b",
    "файл .env": r"(?:^|[\s/\"'])\.env\b",
    "~/.secrets": r"\.secrets[\\/]",
}
PROTECTED = [
    r"\bumask\s+0?077\b",
    r"\bchmod\s+(?:0?[46]00|go-rwx|u=rw,go=|600|400)\b",
    r"\binstall\s+[^;&|\n]*-m\s*0?[46]00\b",
    r"\bmktemp\b",
]
CREDENTIAL_LITERAL = [
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY",
    r"\bgh[pousr]_[A-Za-z0-9]{30,}",
    r"\bgithub_pat_[A-Za-z0-9_]{40,}",
    r"\bsk-ant-[A-Za-z0-9_-]{20,}",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\bxox[abpr]-[A-Za-z0-9-]{10,}",
    r"\b[A-Z][A-Z0-9_]*(?:KEY|SECRET|TOKEN)[A-Z0-9_]*=[0-9a-fA-F]{32,}\b",
    r"(?i)\bpassword\s*[=:]\s*\S{8,}",
]


def _hit(text: str, patterns: list[str]) -> str | None:
    for p in patterns:
        if re.search(p, text):
            return p
    return None


def bash_verdict(cmd: str) -> str | None:
    """Reason to block a shell command, or None."""
    where = _hit(cmd, WRITE_INTO_TEMP)
    if not where:
        return None
    what = next((label for label, p in SECRET_SOURCE.items() if re.search(p, cmd)), None)
    if not what or _hit(cmd, PROTECTED):
        return None
    return ("команда пишет во временный каталог и при этом работает с секретом (%s), но права не ограничены. "
            "Временные каталоги читают все процессы хоста. Передайте значение процессу напрямую (`docker run -e`, "
            "stdin, `--env-file <(…)`), а если файл неизбежен — `umask 077` в начале, `mktemp`/`install -m 600`, "
            "и удалить сразу после использования. ADR-0007, хук secret-on-disk-guard." % what)


def write_verdict(path: str, content: str) -> str | None:
    """Reason to block a Write/Edit, or None."""
    norm = path.replace("\\", "/")
    if not re.search(TEMP, norm if norm.endswith("/") else norm + "/", re.IGNORECASE) and \
            not re.search(TEMP, path, re.IGNORECASE):
        return None
    lit = _hit(content, CREDENTIAL_LITERAL)
    if not lit:
        return None
    return ("в файл во временном каталоге (%s) пишется значение, похожее на секрет. Временные каталоги читают все "
            "процессы хоста, а инструмент записи не ставит права 600. Держите секрет в ~/.secrets или передайте "
            "процессу напрямую. ADR-0007, хук secret-on-disk-guard." % path)


def main() -> None:
    event = read_event()
    tool = event.get("tool_name", "")
    ti = event.get("tool_input", {}) or {}
    if tool == "Bash":
        cmd = bash_command(ti)
        reason = bash_verdict(cmd)
        if reason and not bypass("secret-on-disk", cmd):
            log("BLOCK", "secret_on_disk", "bash", reason[:80], cmd[:300])
            block(reason)
        allow()
    if tool in {"Write", "Edit", "MultiEdit"}:
        path = file_path(ti)
        content = str(ti.get("content") or ti.get("new_string") or "")
        for e in ti.get("edits") or []:
            content += "\n" + str(e.get("new_string", ""))
        reason = write_verdict(path, content)
        if reason and not bypass("secret-on-disk", content):
            log("BLOCK", "secret_on_disk", "write", path, path)
            block(reason)
    allow()


CASES = [
    # (kind, input, must_block)
    ("bash", "F=/tmp/task/proof.env\nK=$(docker inspect srv | sed -n 's/^APP_ENVELOPE_KEY_HEX=//p')\n"
             "grep -v '^APP_ENVELOPE_KEY_HEX=' \"$F\" > \"$F.new\" && echo \"APP_ENVELOPE_KEY_HEX=$K\" >> \"$F.new\"", True),
    ("bash", "echo \"$ANTHROPIC_API_KEY\" > /tmp/key.txt", True),
    ("bash", "printenv > /var/tmp/env.dump", True),
    ("bash", "cat ~/.secrets/tokens.env | tee /tmp/t.env", True),
    ("bash", "cp .env /d/tmp/backup.env", True),
    ("bash", "umask 077; echo \"$ANTHROPIC_API_KEY\" > /tmp/key.txt", False),
    ("bash", "F=$(mktemp); printenv > \"$F\"", False),
    ("bash", "echo \"$ANTHROPIC_API_KEY\" > ~/.secrets/new.env", False),
    ("bash", "docker inspect srv > /dev/null; ls /tmp", False),
    ("bash", "go test ./... > /tmp/test.log", False),
    ("bash", "# claude-bypass: secret-on-disk\n# Reason: test\necho $TOKEN > /tmp/x", None),
    ("write", ("/tmp/creds.env", "GITHUB_TOKEN=ghp_" + "a" * 36), True),
    # Заголовок ключа собран из частей: целиком он сам выглядит как ключ для сканеров публичного репозитория.
    ("write", ("D:\\tmp\\x\\key.pem", "-----BEGIN " + "OPENSSH PRIVATE" + " KEY-----\nabc"), True),
    ("write", ("C:\\Users\\me\\.secrets\\x.env", "GITHUB_TOKEN=ghp_" + "a" * 36), False),
    ("write", ("/tmp/notes.md", "the env var ANTHROPIC_API_KEY must be set"), False),
]


def self_test() -> int:
    bad = 0
    for kind, inp, want in CASES:
        if kind == "bash":
            got = bash_verdict(inp) is not None
            if want is None:  # bypass case: the verdict fires, the marker excuses it
                ok = got and bypass("secret-on-disk", inp)
            else:
                ok = got == want
        else:
            got = write_verdict(*inp) is not None
            ok = got == want
        print(("ok   " if ok else "FAIL ") + kind + ": " + (inp if isinstance(inp, str) else inp[0])[:70].replace("\n", " "))
        bad += not ok
    print(f"{len(CASES) - bad}/{len(CASES)} cases as expected")
    return 1 if bad else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    main()
