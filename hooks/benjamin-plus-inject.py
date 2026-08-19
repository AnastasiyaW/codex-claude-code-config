#!/usr/bin/env python3
"""SessionStart hook: inject the benjamin-plus token-efficiency payload.

Upstream (MIT): https://github.com/JetBrains/benjamin-plus-skill
Vendored copy + provenance + local precedence clause:
    references/benjamin-plus/

Why a hook and not a skill folder: upstream measured both delivery methods head
to head. Injected, the text is the only arm significantly cheaper (-4.4% cost,
p=0.003 on Java SWE-bench; -17.9% median on SkillsBench). As a discoverable
skill folder it saved nothing (-0.5%, n.s.) because agents burned a median 3
steps finding SKILL.md with 73% path misses. So: inject, never install.

Why two files concatenated: the upstream payload stays byte-identical so it can
be updated with a fetch and a checksum. Our precedence clause is a separate file
appended AFTER it, so it reads as the governing clause where upstream's wording
about stopping early and not writing checks collides with this machine's canon
(finish-the-task P2/P3, quality-code, quality-over-tokens-independent-verify).

Fail-open by construction: any missing file or read error prints nothing and
exits 0. A hook that cannot inject an efficiency hint must never cost a session.

Opt out:
    CLAUDE_SKIP_BENJAMIN=1        (env)
    touch .claude/.skip-benjamin  (per project, checked against cwd)

Setup in ~/.claude/settings.json:
{
  "hooks": {
    "SessionStart": [{
      "matcher": "startup|resume|clear|compact",
      "hooks": [{ "type": "command",
                  "command": "python hooks/benjamin-plus-inject.py" }]
    }]
  }
}
The matcher covers the four events that wipe injected context; without `clear`
and `compact` the payload silently disappears mid-session.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PAYLOAD_DIR = Path(__file__).resolve().parent.parent / "references" / "benjamin-plus"
UPSTREAM = PAYLOAD_DIR / "injected-instruction.md"
PRECEDENCE = PAYLOAD_DIR / "local-precedence.md"

# Upstream payload as published in its own SHA256SUMS.txt at commit 532771be.
# Checked, not enforced: a mismatch is reported to stderr and the payload is
# still injected, because a stale hash must not silently disable the hook.
UPSTREAM_SHA256 = "be51fa14d9437840e7282d768f75e1938adb21286e9ef2eb167337daf418b275"


def opted_out(env: dict[str, str], cwd: Path) -> bool:
    """True when this session asked not to be injected into."""
    if env.get("CLAUDE_SKIP_BENJAMIN", "").strip() not in ("", "0", "false"):
        return True
    return (cwd / ".claude" / ".skip-benjamin").exists()


def _read(path: Path) -> str:
    """File text with LF endings, or '' if unreadable. Never raises."""
    try:
        return path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def build_payload(upstream: Path, precedence: Path) -> str:
    """Upstream text, then our precedence clause. Empty if upstream is gone.

    The precedence clause alone is meaningless (it references rules that only
    appear in the upstream text), so it is never emitted on its own.
    """
    head = _read(upstream).strip()
    if not head:
        return ""
    tail = _read(precedence).strip()
    return head + "\n\n" + tail + "\n" if tail else head + "\n"


def _hash_mismatch(path: Path) -> str | None:
    """Return the actual sha256 when it differs from the pinned one, else None."""
    import hashlib

    try:
        data = path.read_bytes().replace(b"\r\n", b"\n")
    except OSError:
        return None
    got = hashlib.sha256(data).hexdigest()
    return None if got == UPSTREAM_SHA256 else got


def main() -> int:
    if opted_out(dict(os.environ), Path.cwd()):
        return 0
    text = build_payload(UPSTREAM, PRECEDENCE)
    if not text:
        return 0
    drifted = _hash_mismatch(UPSTREAM)
    if drifted:
        print(
            f"[benjamin-plus] vendored payload no longer matches the pinned upstream "
            f"hash (got {drifted[:16]}...). Injecting anyway; re-check "
            f"references/benjamin-plus/PROVENANCE.md.",
            file=sys.stderr,
        )
    sys.stdout.write(text)
    return 0


def _self_test() -> int:
    import tempfile

    tmp = Path(tempfile.mkdtemp())

    # opt-out paths
    assert not opted_out({}, tmp), "no signal => inject"
    assert opted_out({"CLAUDE_SKIP_BENJAMIN": "1"}, tmp), "env opts out"
    assert not opted_out({"CLAUDE_SKIP_BENJAMIN": "0"}, tmp), "'0' is not an opt-out"
    (tmp / ".claude").mkdir()
    (tmp / ".claude" / ".skip-benjamin").write_text("", encoding="utf-8")
    assert opted_out({}, tmp), "marker file opts out"

    # composition
    up = tmp / "up.md"
    pr = tmp / "pr.md"
    assert build_payload(up, pr) == "", "missing upstream => nothing, not a bare clause"
    pr.write_text("LOCAL", encoding="utf-8")
    assert build_payload(up, pr) == "", "precedence alone is never emitted"
    up.write_bytes(b"UP\r\n")
    out = build_payload(up, pr)
    assert out == "UP\n\nLOCAL\n", f"CRLF normalised, order upstream-then-local: {out!r}"
    pr.unlink()
    assert build_payload(up, pr) == "UP\n", "upstream alone is fine"

    # the real vendored files compose and carry the local clause last
    real = build_payload(UPSTREAM, PRECEDENCE)
    assert "BENJAMIN-PLUS MODE ACTIVE" in real, "upstream payload present"
    assert real.index("LOCAL PRECEDENCE") > real.index("Polling is a step"), (
        "precedence clause must come after the rules it governs"
    )
    assert _hash_mismatch(UPSTREAM) is None, "vendored payload matches pinned hash"

    print("self-test OK")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    sys.exit(main())
