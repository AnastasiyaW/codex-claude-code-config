"""The backup swap `[cd DIR &&] test ! -e BAK && cp -p DST BAK && mv NEW DST`, recognized in one place.

human-confirmation-guard judges the mv of a swap as no deletion; transfer-contract-guard judges its
cp as no transfer (a backup next to the file moves nothing between places). Both import this module,
so the two guards cannot disagree on what a swap is.
"""
from __future__ import annotations

import os
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from safety_common import executable_text  # noqa: E402


MOVE_FLAGS = {"-f", "--force", "-T", "--no-target-directory", "-v", "--verbose"}


def move_overwrite_targets(segment: str) -> list[str] | None:
    """Destination of `mv [-f|-T|-v] SRC DST`: the file a replacement overwrites (owner 2026-10-11).
    None for any other shape (several sources, -t, unknown flags), which stays unapproved."""
    # simplification: POSIX mv only; a Move-Item replacement still needs an explicit delete request
    try:
        toks = [t.strip("'\"") for t in shlex.split(segment, posix=False)]
    except ValueError:
        return None
    if not toks or toks[0].rsplit("/", 1)[-1] != "mv":
        return None
    flags = [t for t in toks[1:] if t.startswith("-")]
    operands = [t for t in toks[1:] if not t.startswith("-")]
    if any(f not in MOVE_FLAGS for f in flags) or len(operands) != 2:
        return None
    return [operands[1]]


# Owner 2026-10-12 ("поправь хук, чтобы ты такое делала сама" after a deploy swap was refused):
# `test ! -e f.bak && cp -p f f.bak && mv f.new f` loses nothing - the old content survives in a
# backup that provably did not exist before (review 2026-10-12: cp onto an existing file destroys
# it) - so that mv is not a deletion. && only (each step runs only if the previous succeeded);
# plain names only (no glob, variable, quote or redirect). The three steps must be adjacent: any
# step between them (cd, pushd, touch, a redirect) could move or rewrite what the check proved, so
# none is allowed. Approval is by step position, so an identical second mv later in the command is
# judged on its own (review 2026-10-12).
# No -a/-r: a directory (or a symlink to one) is then refused by cp and && stops the chain;
# `cp -a link` would copy the link, not the files behind it (review 2026-10-12).
BACKUP_COPY_FLAGS = {"-p", "--preserve"}
PLAIN_WORD = re.compile(r"[A-Za-z0-9_./~+-]+")


def split_steps(text: str) -> list[tuple[str, str]]:
    """split_segments with the separator that preceded each segment ("" for the first)."""
    out: list[tuple[str, str]] = []
    buf: list[str] = []
    sep = ""
    quote = None
    i = 0
    while i < len(text):
        c = text[i]
        if c == "\\" and quote != "'" and i + 1 < len(text):
            buf.append(text[i:i + 2])  # \" \; \<newline> are literal to the shell (review 2026-10-06)
            i += 2
            continue
        if quote:
            buf.append(c)
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
            buf.append(c)
        elif text.startswith(("&&", "||"), i):
            out.append(("".join(buf), sep))
            buf, sep = [], text[i:i + 2]
            i += 2
            continue
        elif c in ";|\n" or (c == "&" and text[i - 1:i] not in (">", "<")
                               and text[i + 1:i + 2] != ">"):
            # a lone & (background) ends a command too; >& <& &> are redirections (review 2026-10-28:
            # `ssh h rm F&rm F` ran the second rm locally while it was judged as remote)
            out.append(("".join(buf), sep))
            buf, sep = [], c
        else:
            buf.append(c)
        i += 1
    out.append(("".join(buf), sep))
    return out


def _norm_name(path: str) -> str:
    return os.path.normpath(path.replace("\\", "/")).replace("\\", "/")


def backed_up_moves(text: str) -> set[int]:
    """Index of the mv step when the WHOLE of text is `[cd DIR &&] test ! -e BAK && cp -p DST BAK
    && mv NEW DST` (or `[ ! -e BAK ]`), else nothing.

    Whole-command shape, by review 2026-10-12: a step after the mv could clobber BAK without
    naming it (`> ?`, `> B`, $'\\x62'); a step before the test could redefine `test`/`cp` (a shell
    function, PATH) so no backup is made. Only a plain `cd` may come first."""
    steps = [(seg.split(), sep) for seg, sep in split_steps(executable_text(text))]
    while steps and not steps[-1][0]:
        steps.pop()
    mv_index = len(steps) - 1  # index in decide()'s segment list (same split)
    if len(steps) == 4 and len(steps[0][0]) == 2 and steps[0][0][0] == "cd" \
            and PLAIN_WORD.fullmatch(steps[0][0][1]) and steps[1][1] == "&&":
        steps = steps[1:]
    if len(steps) != 3:
        return set()
    (test, _), (cp, cp_sep), (mv, mv_sep) = steps
    if cp_sep != "&&" or mv_sep != "&&" or not all(PLAIN_WORD.fullmatch(t) for t in cp + mv):
        return set()  # also rejects > < $ * quotes
    if test[:3] == ["test", "!", "-e"] and len(test) == 4:
        bak = test[3]
    elif test[:3] == ["[", "!", "-e"] and len(test) == 5 and test[4] == "]":
        bak = test[3]
    else:
        return set()
    cp_ops = [t for t in cp[1:] if not t.startswith("-")]
    mv_ops = [t for t in mv[1:] if not t.startswith("-")]
    if cp[0].rsplit("/", 1)[-1] != "cp" or len(cp_ops) != 2 \
            or any(t not in BACKUP_COPY_FLAGS for t in cp[1:] if t.startswith("-")):
        return set()
    dst = move_overwrite_targets(" ".join(mv))  # it already accepts /bin/mv
    if mv[0].rsplit("/", 1)[-1] != "mv" or not dst or len(mv_ops) != 2:
        return set()
    # Equalities that GRANT the exemption compare raw strings: normpath would make `x/../f` equal
    # `f` although x may be a symlink, and on a case-sensitive disk `B` is not `b`. Differences it
    # REQUIRES are normalised and case-folded, the cautious direction (review rounds 4-5).
    src, new = cp_ops[0], mv_ops[0]
    if cp_ops[1] != bak or dst[0] != src:
        return set()
    if _norm_name(new).casefold() in (_norm_name(bak).casefold(), _norm_name(src).casefold()):
        return set()
    return {mv_index}
