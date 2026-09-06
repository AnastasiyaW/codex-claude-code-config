#!/usr/bin/env python3
"""Atomically reserve one project-wide feature ID with a Git ref.

The ref is an allocator record, not a second feature registry.  It binds an ID
to its intended document path.  Repeating the same request resumes safely;
another path or slug with the ID is a conflict and makes no working-tree edit.
"""
from __future__ import annotations

import argparse
import json
from pathlib import PurePosixPath
import re
import subprocess
import sys


class GitLaunchError(RuntimeError):
    pass


def git(repo: str, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", repo, *args], input=input_text, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
    except OSError as error:
        raise GitLaunchError(error.strerror or error.__class__.__name__) from error


def fail(message: str) -> int:
    print(json.dumps({"status": "error", "message": message}))
    return 2


def valid_document(layer: str, document: str) -> bool:
    if "\\" in document:
        return False
    raw_parts = document.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        return False
    path = PurePosixPath(document)
    prefix = ("docs", "layers", layer, "features")
    return (
        not path.is_absolute()
        and len(path.parts) > len(prefix)
        and path.parts[:len(prefix)] == prefix
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Reserve a project-wide feature ID atomically.")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--id", required=True)
    ap.add_argument("--layer", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--document", required=True)
    ns = ap.parse_args()

    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", ns.id):
        return fail("feature ID must be a safe single ref component")
    if not re.fullmatch(r"[a-z][a-z0-9-]*", ns.slug):
        return fail("slug must be lowercase kebab-case")
    if not re.fullmatch(r"[a-z][a-z0-9-]*", ns.layer):
        return fail("layer must be lowercase kebab-case")
    if not valid_document(ns.layer, ns.document):
        return fail("document must be a safe docs/layers/<layer>/features/ relative path")
    inside = git(ns.repo, "rev-parse", "--is-inside-work-tree")
    if inside.returncode or inside.stdout.strip() != "true":
        return fail("--repo must be a Git work tree")

    intent = {"id": ns.id, "layer": ns.layer, "slug": ns.slug, "document": ns.document}
    payload = json.dumps(intent, sort_keys=True, separators=(",", ":")) + "\n"
    blob = git(ns.repo, "hash-object", "-w", "--stdin", input_text=payload)
    if blob.returncode:
        return fail(blob.stderr.strip() or "cannot create reservation object")
    ref = f"refs/feature-new/reservations/{ns.id}"
    zero = "0" * 40
    created = git(ns.repo, "update-ref", ref, blob.stdout.strip(), zero)
    if created.returncode == 0:
        print(json.dumps({"status": "reserved", "ref": ref, **intent}, sort_keys=True))
        return 0

    existing = git(ns.repo, "show", ref)
    if existing.returncode:
        return fail("reservation ref changed during allocation; re-inventory and retry")
    try:
        prior = json.loads(existing.stdout)
    except json.JSONDecodeError:
        return fail("existing reservation is unreadable; do not overwrite it")
    if prior == intent:
        print(json.dumps({"status": "resumed", "ref": ref, **intent}, sort_keys=True))
        return 0
    print(json.dumps({"status": "conflict", "ref": ref, "existing": prior, "requested": intent}, sort_keys=True))
    return 3


if __name__ == "__main__":
    try:
        sys.exit(main())
    except GitLaunchError as error:
        sys.exit(fail(f"cannot launch git: {error}"))
