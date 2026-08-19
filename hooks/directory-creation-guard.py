#!/usr/bin/env python3
"""PreToolUse: guard ad-hoc directory creation.

Blocks new loose folders that should live in an existing hierarchy, and requires
an explicit lifecycle marker for scratch/test/temp/dataset work directories.

Preferred marker in the same command:
  .folder-meta.json

Accepted label values inside the command:
  PROJECT_ROOT, TEMP_REPRODUCIBLE, GIT_BACKED, DATASET_REBUILDABLE,
  CACHE_GENERATED, ARTIFACT_REGENERABLE, KEEP_MANUAL, NEEDS_REVIEW

Legacy delete markers are still accepted for scratch folders:
  _DELETE_OK.md, .delete-ok, DELETE_OK, .tmp-meta.json

Bypass, only after conscious review:
  # claude-bypass: mkdir-cohesion
"""
from __future__ import annotations

import os
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from safety_common import allow, bash_command, block, bypass, log, read_event  # noqa: E402


SHELL_SPLIT_RE = re.compile(r"(?:\r?\n|&&|\|\||;)")
MKDIR_RE = re.compile(r"^\s*(?:mkdir|md)\b\s+(?P<args>.+)$", re.IGNORECASE)
NEW_ITEM_RE = re.compile(r"\bNew-Item\b", re.IGNORECASE)
CREATE_DIR_RE = re.compile(r"\[IO\.Directory\]::CreateDirectory\s*\((?P<arg>[^)]+)\)", re.IGNORECASE)
ITEMTYPE_DIR_RE = re.compile(r"-ItemType\s+(?:Directory|'Directory'|\"Directory\")", re.IGNORECASE)
PATH_ARG_RE = re.compile(
    r"-(?:LiteralPath|Path)\s+(?P<path>\"[^\"]+\"|'[^']+'|[^\s;|&]+)",
    re.IGNORECASE,
)

DELETE_MARKER_RE = re.compile(
    r"(_DELETE_OK\.md|\.delete-ok\b|DELETE_OK\b|\.tmp-meta\.json)",
    re.IGNORECASE,
)
FOLDER_META_RE = re.compile(r"\.folder-meta\.json\b", re.IGNORECASE)
LIFECYCLE_LABEL_RE = re.compile(
    r"\b(PROJECT_ROOT|TEMP_REPRODUCIBLE|GIT_BACKED|DATASET_REBUILDABLE|"
    r"CACHE_GENERATED|ARTIFACT_REGENERABLE|KEEP_MANUAL|NEEDS_REVIEW)\b",
    re.IGNORECASE,
)

SCRATCH_HINT_RE = re.compile(
    r"(^|[\\/._-])(tmp|temp|scratch|sandbox|experiment|experiments|proof|"
    r"smoke|try|trial|test-run|testdata|fixture-work|worktree-test)([\\/._-]|$)",
    re.IGNORECASE,
)
DATASET_HINT_RE = re.compile(
    r"(^|[\\/._-])(dataset|datasets|data-set|train|training|images|photos|"
    r"samples|labels|masks|review|annotation|annotations)([\\/._-]|$)",
    re.IGNORECASE,
)

APPROVED_DURABLE_PREFIXES = (
    ".agent/",
    ".claude/",
    ".codex/",
    ".github/",
    "agents/",
    "alternatives/",
    "docs/",
    "hooks/",
    "principles/",
    "references/",
    "reports/",
    "rules/",
    "scripts/",
    "skills/",
    "templates/",
    "tests/",
)

APPROVED_SCRATCH_PREFIXES = (
    ".tmp/",
    "tmp/",
    "temp/",
    ".scratch/",
    "scratch/",
    ".cache/",
    "cache/",
)

GENERATED_BUILD_PREFIXES = (
    "build/",
    "dist/",
    "out/",
    "target/",
    "node_modules/",
    ".venv/",
    "venv/",
    "__pycache__/",
)

SCRATCH_LABELS = {"TEMP_REPRODUCIBLE", "CACHE_GENERATED", "ARTIFACT_REGENERABLE", "NEEDS_REVIEW"}
DATASET_LABELS = {"DATASET_REBUILDABLE", "KEEP_MANUAL", "NEEDS_REVIEW"}
ROOT_LABELS = {"PROJECT_ROOT", "GIT_BACKED", "NEEDS_REVIEW"}


def _norm(path: str) -> str:
    p = path.strip().strip("\"'")
    p = p.replace("\\", "/")
    p = re.sub(r"/+", "/", p)
    return p.rstrip("/")


def _strip_shell_noise(token: str) -> str:
    token = token.strip().strip(",")
    while token.startswith(("./", ".\\")):
        token = token[2:]
    return _norm(token)


def _split_args(args: str) -> list[str]:
    try:
        return shlex.split(args, posix=False)
    except ValueError:
        return args.split()


def _extract_mkdir_targets(cmd: str) -> list[str]:
    targets: list[str] = []
    for segment in SHELL_SPLIT_RE.split(cmd):
        seg = segment.strip()
        if not seg:
            continue

        m = MKDIR_RE.search(seg)
        if m:
            for tok in _split_args(m.group("args")):
                clean = _strip_shell_noise(tok)
                if not clean or clean.startswith("-"):
                    continue
                if clean in {"2>nul", "nul", "NUL"}:
                    continue
                targets.append(clean)
            continue

        if NEW_ITEM_RE.search(seg) and ITEMTYPE_DIR_RE.search(seg):
            for pm in PATH_ARG_RE.finditer(seg):
                targets.append(_strip_shell_noise(pm.group("path")))
            continue

        for cm in CREATE_DIR_RE.finditer(seg):
            targets.append(_strip_shell_noise(cm.group("arg")))

    return [t for t in targets if t]


def _is_absolute(path: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:/", path)) or path.startswith("/")


def _is_direct_root_child(path: str, cwd: str) -> bool:
    p = _norm(path)
    if not p or "/" in p or _is_absolute(p):
        return False
    return True


def _absolute_loose_reason(path: str, cwd: str) -> str | None:
    p = _norm(path)
    if not _is_absolute(p):
        return None

    home = _norm(str(Path.home())).lower()
    desktop = _norm(str(Path.home() / "Desktop")).lower()
    downloads = _norm(str(Path.home() / "Downloads")).lower()
    cwd_norm = _norm(cwd or os.getcwd()).lower()
    low = p.lower()

    parent = low.rsplit("/", 1)[0] if "/" in low else low
    if parent in {home, desktop, downloads, cwd_norm}:
        return f"direct child of {parent}"
    if "/appdata/local/temp/" in low or low.startswith(_norm(os.environ.get("TEMP", "")).lower() + "/"):
        return "OS temp directory"
    return None


def _relative(path: str, cwd: str) -> str:
    p = _norm(path)
    if not _is_absolute(p):
        return p.lower()
    try:
        return _norm(str(Path(p).resolve().relative_to(Path(cwd or os.getcwd()).resolve()))).lower()
    except Exception:
        return p.lower()


def _needs_delete_marker(path: str, cwd: str) -> bool:
    rel = _relative(path, cwd)
    return rel.startswith(APPROVED_SCRATCH_PREFIXES) or bool(SCRATCH_HINT_RE.search(rel))


def _looks_dataset_like(path: str, cwd: str) -> bool:
    rel = _relative(path, cwd)
    return bool(DATASET_HINT_RE.search(rel))


def _has_good_hierarchy(path: str, cwd: str) -> bool:
    rel = _relative(path, cwd)
    if rel.startswith(APPROVED_DURABLE_PREFIXES):
        return True
    if rel.startswith(APPROVED_SCRATCH_PREFIXES):
        return True
    if rel.startswith(GENERATED_BUILD_PREFIXES):
        return True
    return False


def _labels_in_command(cmd: str) -> set[str]:
    return {m.group(1).upper() for m in LIFECYCLE_LABEL_RE.finditer(cmd or "")}


def _has_folder_meta(cmd: str) -> bool:
    return bool(FOLDER_META_RE.search(cmd or ""))


def _has_lifecycle_label(cmd: str, accepted: set[str]) -> bool:
    labels = _labels_in_command(cmd)
    return bool(labels & accepted)


def _already_exists(path: str, cwd: str) -> bool:
    """`mkdir -p` on an existing directory creates nothing, so there is nothing to place well.

    The guard exists to stop folder PROLIFERATION. A directory that is already there cannot be
    proliferated by a no-op, and the moment to argue about its placement was when it was first
    created. Blocking the idempotent re-run instead punishes the safest way to write a script -
    which is how this fired on a harness-provided scratch directory that the harness itself had
    created. Passing here cannot weaken the guard: every genuinely NEW directory still goes
    through every check below.
    """
    try:
        candidate = path if os.path.isabs(path) else os.path.join(cwd, path)
        return os.path.isdir(candidate)
    except (OSError, ValueError):
        return False


def _verdict_for_target(path: str, cmd: str, cwd: str) -> str | None:
    if _already_exists(path, cwd):
        return None

    legacy_delete_marker = bool(DELETE_MARKER_RE.search(cmd))
    folder_meta = _has_folder_meta(cmd)

    if _looks_dataset_like(path, cwd):
        if not (folder_meta and _has_lifecycle_label(cmd, DATASET_LABELS)):
            return (
                f"Directory '{path}' looks dataset/review/media-related. Add "
                ".folder-meta.json with label DATASET_REBUILDABLE when images can "
                "be recreated from code/manifests, KEEP_MANUAL when originals are "
                "irreplaceable, or NEEDS_REVIEW when cleanup safety is unknown."
            )
        return None

    if _needs_delete_marker(path, cwd) and not (
        legacy_delete_marker or (folder_meta and _has_lifecycle_label(cmd, SCRATCH_LABELS))
    ):
        return (
            f"Directory '{path}' looks temporary/test/scratch, but the command "
            "does not create a lifecycle marker. Create it in a tracked scratch "
            "place and add .folder-meta.json with label TEMP_REPRODUCIBLE, "
            "CACHE_GENERATED, ARTIFACT_REGENERABLE, or NEEDS_REVIEW. Legacy "
            "_DELETE_OK.md / .delete-ok is accepted for simple scratch folders."
        )

    loose_abs = _absolute_loose_reason(path, cwd)
    if loose_abs and not _has_good_hierarchy(path, cwd):
        if folder_meta and _has_lifecycle_label(cmd, ROOT_LABELS):
            return None
        return (
            f"Directory '{path}' is a loose folder ({loose_abs}). Re-check the "
            "placement: use an existing project hierarchy such as docs/, "
            "reports/, tests/, scripts/, or mark intentional roots with "
            ".folder-meta.json label PROJECT_ROOT/GIT_BACKED/NEEDS_REVIEW."
        )

    if _is_direct_root_child(path, cwd) and not _has_good_hierarchy(path, cwd):
        if folder_meta and _has_lifecycle_label(cmd, ROOT_LABELS):
            return None
        return (
            f"Directory '{path}' would be created directly in the project root. "
            "Avoid folder proliferation: put durable artifacts under the right "
            "project hierarchy, or mark intentional roots with .folder-meta.json "
            "label PROJECT_ROOT/GIT_BACKED/NEEDS_REVIEW."
        )

    return None


def main() -> None:
    event = read_event()
    if event.get("tool_name") not in {"Bash", "PowerShell"}:
        allow()

    cmd = bash_command(event.get("tool_input", {}) or {})
    if not cmd:
        allow()

    targets = _extract_mkdir_targets(cmd)
    if not targets:
        allow()

    if bypass("mkdir-cohesion", cmd):
        log("WARN", "directory_creation_guard", "bypass", "mkdir-cohesion", cmd)
        allow()

    cwd = str(event.get("cwd") or os.getcwd())
    reasons = []
    for target in targets:
        reason = _verdict_for_target(target, cmd, cwd)
        if reason:
            reasons.append(reason)

    if reasons:
        log("BLOCK", "directory_creation_guard", "deny", "mkdir-cohesion", cmd)
        block(
            "Directory creation cohesion guard blocked this command.\n\n"
            + "\n\n".join(f"- {r}" for r in reasons)
            + "\n\nExpected pattern: durable folders go into the existing project "
            "tree; scratch/dataset folders include .folder-meta.json with a "
            "cleanup lifecycle label."
        )

    allow()


def _self_test() -> int:
    """Prove both halves: the no-op passes, and a genuinely new scratch folder still does not."""
    import shutil
    import tempfile

    # The sandbox may NOT live in the OS temp directory: the guard classifies anything under it
    # as a loose folder at any depth, which would make the marked-directory case fail for a
    # reason that has nothing to do with what is being tested. Build it beside this hook.
    failures = []
    sandbox = tempfile.mkdtemp(dir=os.path.dirname(os.path.abspath(__file__)),
                               prefix=".selftest-")
    try:
        root = sandbox
        existing = os.path.join(root, "scratch-tmp")
        os.makedirs(existing)

        proj = os.path.join(root, "proj", "scripts")
        os.makedirs(proj)
        marked = os.path.join(proj, "tmp-run2")
        cases = [
            # (label, path, cmd, cwd, expect_blocked)
            # the half this change adds: a no-op is not a creation
            ("existing dir, absolute", existing,
             "mkdir -p %s" % existing, root, False),
            ("existing dir, relative", "scratch-tmp",
             "mkdir -p scratch-tmp", root, False),
            # the half that must not weaken: a genuinely new folder is still judged
            ("NEW scratch dir, no marker", os.path.join(root, "tmp-run"),
             "mkdir -p %s/tmp-run" % root, root, True),
            ("NEW scratch dir, marked, inside a tree", marked,
             "mkdir -p %s && echo TEMP_REPRODUCIBLE > %s/.folder-meta.json" % (marked, marked),
             root, False),
        ]
        for label, path, cmd, cwd, expect_blocked in cases:
            got = _verdict_for_target(path, cmd, cwd) is not None
            mark = "ok " if got == expect_blocked else "FAIL"
            if got != expect_blocked:
                failures.append(label)
            print("  %s %-34s blocked=%-5s expected=%s" % (mark, label, got, expect_blocked))

    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    print("  %d/%d passed" % (len(cases) - len(failures), len(cases)))
    return 1 if failures else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    main()
