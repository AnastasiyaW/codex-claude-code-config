#!/usr/bin/env python3
"""PreToolUse: check dependencies against the registry before they enter a manifest.

Package names and versions are where writing from memory fails first and most
quietly. A hallucinated package name looks exactly like a real one until install
time; a version recalled from training data is silently years old; and our own
supply-chain rule (`min-release-age=7` in ~/.npmrc and uv.toml) is policy that
nothing has ever enforced at the moment a dependency is actually added.

So this asks the registry, at the one moment the answer matters:

  * package does not exist         -> BLOCK. The hallucinated-dependency failure,
                                     and how typosquats land.
  * name registered recently       -> BLOCK. Existence is not authenticity. In a
                                     slopsquat the package DOES exist -- someone
                                     registered the hallucination on purpose. A
                                     model cannot remember a name younger than
                                     its training data, so confidence about one
                                     is the signature of the attack, not of use.
  * almost nobody installs it      -> BLOCK. A real dependency proposed with
                                     confidence has users; a lure does not.
  * published less than 7 days ago -> BLOCK. Our stated supply-chain buffer,
                                     finally mechanical instead of aspirational.
  * fast-moving package pinned far
    behind (torch, transformers,
    numpy and friends)             -> BLOCK. Not a security failure but a silent
                                     one: an old CUDA-tagged pin installs, runs,
                                     and quietly costs the wrong kernels.
  * anything else behind           -> report the current version, do not block.
                                     Old is often deliberate; unknown never is.

Fail-open by design: no network, a slow registry or an unparsable manifest must
never wedge an edit. A guard that blocks when the internet hiccups gets disabled,
and a disabled guard protects nothing.

Bypass: `# claude-bypass: deps` in the content, or CLAUDE_SKIP_DEP_CHECK=1.

Self-test: python dependency-currency-guard.py --self-test
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

MIN_RELEASE_AGE_DAYS = 7
BEHIND_MAJOR_WARN = 2          # report when the pin trails by this many majors

# Slopsquatting window. A model cannot legitimately know a package first published
# after its training data was collected, so "the agent is confident about a package
# that appeared weeks ago" is the exact profile of a registered hallucination.
# Measured 2026: 43% of hallucinated names recur across every identical prompt, so
# an attacker harvests reliable targets from a few dozen prompts and registers them.
# Documented: react-codeshift, registered Jan 2026, reached 237 repositories through
# AI-generated skill files with agent download attempts from day one.
YOUNG_PACKAGE_DAYS = 120
# Adoption floor for npm, where the download API is public. A real dependency an
# agent proposes with confidence has users; a freshly registered lure does not.
MIN_WEEKLY_DOWNLOADS = 500

# Packages where recall skews years out of date. The failure is not security but
# silent obsolescence: an old CUDA-tagged torch pin installs, runs, and quietly
# costs the wrong kernels. A floor here is cheaper than discovering it on a GPU.
FAST_MOVING = {
    "torch", "torchvision", "torchaudio", "transformers", "diffusers",
    "accelerate", "safetensors", "tokenizers", "peft", "bitsandbytes",
    "numpy", "scipy", "pandas", "onnxruntime", "onnxruntime-gpu",
    "nvidia-cuda-runtime-cu12", "xformers", "vllm",
}
FAST_MOVING_MAX_MINORS_BEHIND = 12
NET_TIMEOUT = 4                # a guard people wait on is a guard people remove
CACHE_TTL = 6 * 3600
CACHE = Path.home() / ".claude" / "state" / "dep-registry-cache.json"

MANIFESTS = {
    "requirements.txt": "pypi", "requirements-dev.txt": "pypi",
    "pyproject.toml": "pypi", "setup.py": "pypi", "Pipfile": "pypi",
    "package.json": "npm",
}

# name==1.2.3 / name>=1.2 / "name": "^1.2.3" / name = "1.2.3"
PY_SPEC = re.compile(r"^\s*([A-Za-z][\w.\-]{1,60})\s*(?:\[[^\]]+\])?\s*(==|>=|~=)\s*([\w.\-]+)", re.M)
NPM_SPEC = re.compile(r'"([@\w][\w.\-/]{1,60})"\s*:\s*"[\^~]?([\w.\-]+)"')


def load_cache() -> dict:
    try:
        data = json.loads(CACHE.read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if time.time() - v.get("at", 0) < CACHE_TTL}
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(cache: dict) -> None:
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass


ABSENT = object()   # the registry answered: no such package


def fetch(url: str):
    """Parsed JSON, ABSENT when the registry says 404, or None when it did not answer.

    Conflating those three is the whole bug this guard exists to catch: a 404 is
    a definitive "this package does not exist", and treating it as silence makes
    the guard quietest exactly where it is needed.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "dependency-currency-guard"})
        with urllib.request.urlopen(req, timeout=NET_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        return ABSENT if e.code == 404 else None
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return None


def registry_info(name: str, ecosystem: str, cache: dict) -> dict | None:
    """{'exists', 'latest', 'released'} or None when the registry could not answer."""
    key = f"{ecosystem}:{name.lower()}"
    if key in cache:
        return cache[key]["info"]

    if ecosystem == "pypi":
        data = fetch(f"https://pypi.org/pypi/{name}/json")
        if data is None:
            return None
        if data is ABSENT:
            info = {"exists": False, "latest": None, "released": None}
            cache[key] = {"at": time.time(), "info": info}
            return info
        latest = (data.get("info") or {}).get("version")
        released = None
        for f in (data.get("urls") or []):
            if f.get("upload_time_iso_8601"):
                released = f["upload_time_iso_8601"]
                break
        # First-ever upload: how long the NAME has existed, which is what
        # separates an established package from a registered hallucination.
        created = None
        for files in (data.get("releases") or {}).values():
            for f in files:
                ts = f.get("upload_time_iso_8601")
                if ts and (created is None or ts < created):
                    created = ts
        info = {"exists": bool(latest), "latest": latest, "released": released,
                "created": created, "downloads": None}
    else:
        data = fetch(f"https://registry.npmjs.org/{name.replace('/', '%2F')}")
        if data is None:
            return None
        if data is ABSENT:
            info = {"exists": False, "latest": None, "released": None}
            cache[key] = {"at": time.time(), "info": info}
            return info
        latest = (data.get("dist-tags") or {}).get("latest")
        times = data.get("time") or {}
        released = times.get(latest) if latest else None
        downloads = None
        stats = fetch(f"https://api.npmjs.org/downloads/point/last-week/{name.replace('/', '%2F')}")
        if isinstance(stats, dict):
            downloads = stats.get("downloads")
        info = {"exists": bool(latest), "latest": latest, "released": released,
                "created": times.get("created"), "downloads": downloads}

    cache[key] = {"at": time.time(), "info": info}
    return info


def age_days(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        stamp = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - stamp).total_seconds() / 86400


def major(version: str) -> int | None:
    m = re.match(r"(\d+)", version or "")
    return int(m.group(1)) if m else None


def minors_behind(pinned: str, latest: str) -> int | None:
    """Distance in minor releases, counting a major bump as ten minors.

    Crude on purpose. The question is not "exactly how far behind" but "is this a
    version someone chose, or one that surfaced from memory" -- and a torch pin
    two majors back answers that without needing the real release calendar.
    """
    pm, lm = major(pinned), major(latest)
    if pm is None or lm is None:
        return None

    def minor(v: str) -> int:
        m = re.match(r"\d+\.(\d+)", v or "")
        return int(m.group(1)) if m else 0

    return (lm - pm) * 10 + (minor(latest) - minor(pinned))


def extract(content: str, ecosystem: str) -> list[tuple[str, str]]:
    pattern = PY_SPEC if ecosystem == "pypi" else NPM_SPEC
    out, seen = [], set()
    for m in pattern.finditer(content):
        name = m.group(1)
        version = m.group(3) if ecosystem == "pypi" else m.group(2)
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append((name, version))
    return out[:40]


def review(content: str, ecosystem: str, cache: dict) -> tuple[list[str], list[str]]:
    blocking: list[str] = []
    notes: list[str] = []
    for name, version in extract(content, ecosystem):
        info = registry_info(name, ecosystem, cache)
        if info is None:
            continue                      # registry silent -> say nothing, never block
        if not info["exists"]:
            blocking.append(f"{name}: not found in {ecosystem}. A package that does not "
                            f"exist is either a misremembered name or a typosquat target.")
            continue
        released = age_days(info.get("released"))
        if released is not None and released < MIN_RELEASE_AGE_DAYS:
            blocking.append(f"{name} {info['latest']}: published {released:.1f} days ago, "
                            f"under our {MIN_RELEASE_AGE_DAYS}-day supply-chain buffer.")

        # Slopsquat profile: the NAME is young, yet it is being proposed with
        # confidence. Existence is not authenticity -- a registered hallucination
        # exists by definition, which is the whole point of the attack.
        name_age = age_days(info.get("created"))
        if name_age is not None and name_age < YOUNG_PACKAGE_DAYS:
            blocking.append(
                f"{name}: the name has only existed for {name_age:.0f} days. A package "
                f"younger than the model's knowledge cannot be something it remembers -- "
                f"confirm it is the package you mean, from its own repository, not from a "
                f"search result.")

        downloads = info.get("downloads")
        if downloads is not None and downloads < MIN_WEEKLY_DOWNLOADS:
            blocking.append(f"{name}: {downloads} downloads last week, under the "
                            f"{MIN_WEEKLY_DOWNLOADS} adoption floor. Real dependencies "
                            f"proposed with confidence have users.")

        pinned_major, latest_major = major(version), major(info.get("latest") or "")
        base = name.lower()
        if base in FAST_MOVING:
            behind = minors_behind(version, info.get("latest") or "")
            if behind is not None and behind >= FAST_MOVING_MAX_MINORS_BEHIND:
                blocking.append(
                    f"{name}: pinned {version}, current {info['latest']} ({behind} minor "
                    f"releases behind). This one moves fast enough that a recalled version "
                    f"is almost certainly wrong -- pick deliberately or bypass.")
        elif (pinned_major is not None and latest_major is not None
                and latest_major - pinned_major >= BEHIND_MAJOR_WARN):
            notes.append(f"{name}: pinned {version}, current {info['latest']} "
                         f"({latest_major - pinned_major} majors behind) -- deliberate?")
    return blocking, notes


def main() -> int:
    if os.environ.get("CLAUDE_SKIP_DEP_CHECK"):
        return 0
    try:
        event = json.loads(sys.stdin.read().lstrip("﻿") or "{}")
    except json.JSONDecodeError:
        return 0
    if event.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
        return 0

    ti = event.get("tool_input") or {}
    path = str(ti.get("file_path") or "")
    ecosystem = MANIFESTS.get(Path(path).name)
    if not ecosystem:
        return 0

    content = " ".join(str(ti.get(k) or "") for k in ("content", "new_string"))
    for edit in (ti.get("edits") or []):
        if isinstance(edit, dict):
            content += " " + str(edit.get("new_string") or "")
    if not content.strip() or "claude-bypass: deps" in content:
        return 0

    cache = load_cache()
    try:
        blocking, notes = review(content, ecosystem, cache)
    except Exception:
        return 0                          # a bug here must not cost an edit
    save_cache(cache)

    if blocking:
        reason = ("DEPENDENCY CHECK — the registry disagrees with this manifest:\n  "
                  + "\n  ".join(blocking)
                  + "\n\nFix the name or the version, or bypass with "
                    "'# claude-bypass: deps' once you know why.")
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
        return 0
    if notes:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": "Dependency note: " + "; ".join(notes),
        }}, ensure_ascii=False))
    return 0


def _self_test() -> int:
    fails: list[str] = []
    cache = load_cache()

    real = review("requests==2.31.0\n", "pypi", cache)
    if real[0]:
        fails.append(f"a real, long-published package was blocked: {real[0]}")

    fake = review("thispackagedoesnotexist-qwerty-12345==1.0.0\n", "pypi", cache)
    if not any("not found" in b for b in fake[0]):
        fails.append("a nonexistent package was not blocked (registry unreachable?)")

    behind = review("flask==0.12.2\n", "pypi", cache)
    if not behind[1] and not behind[0]:
        fails.append("a badly outdated pin produced no note")

    npm = review('{"dependencies": {"react": "^18.2.0"}}', "npm", cache)
    if npm[0]:
        fails.append(f"a real npm package was blocked: {npm[0]}")

    parsed = extract("requests==2.31.0\nflask>=1.0\n# comment\n-e .\n", "pypi")
    if [p[0] for p in parsed] != ["requests", "flask"]:
        fails.append(f"parser picked up the wrong specs: {parsed}")

    # The slopsquat and adoption rules cannot be demonstrated against a live
    # registry without naming a real young package, so they are exercised
    # against a seeded answer instead. Untested branches in a security guard are
    # the branches that quietly do nothing.
    now = datetime.now(timezone.utc)
    seeded = dict(cache)
    seeded["pypi:freshly-registered-lure"] = {"at": time.time(), "info": {
        "exists": True, "latest": "1.0.0",
        "released": (now - timedelta(days=30)).isoformat(),
        "created": (now - timedelta(days=30)).isoformat(), "downloads": None}}
    young = review("freshly-registered-lure==1.0.0\n", "pypi", seeded)
    if not any("only existed for" in b for b in young[0]):
        fails.append("a name registered 30 days ago did not trip the slopsquat rule")

    seeded["npm:barely-used-pkg"] = {"at": time.time(), "info": {
        "exists": True, "latest": "2.0.0",
        "released": (now - timedelta(days=400)).isoformat(),
        "created": (now - timedelta(days=800)).isoformat(), "downloads": 12}}
    thin = review('{"dependencies": {"barely-used-pkg": "2.0.0"}}', "npm", seeded)
    if not any("adoption floor" in b for b in thin[0]):
        fails.append("a package with 12 weekly downloads did not trip the adoption floor")

    save_cache(cache)
    for f in fails:
        print("FAIL", f)
    print("SELF-TEST: PASS" if not fails else f"SELF-TEST: FAIL ({len(fails)})")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    sys.exit(main())

