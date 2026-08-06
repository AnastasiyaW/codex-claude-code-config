#!/usr/bin/env python3
"""Find verified package-name alternatives without recommending blind matches.

The search result is only a candidate. Each candidate is fetched again from the
canonical PyPI/npm metadata endpoint and is emitted only when its latest stable
release is at least seven days old and has a registry artifact digest. Functional
compatibility still requires project tests.

Examples:
  python scripts/dependency-alternatives.py --ecosystem pypi --name reqeusts
  python scripts/dependency-alternatives.py --ecosystem npm --name image-reszie
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

MIN_RELEASE_AGE_DAYS = 7
MIN_WEEKLY_DOWNLOADS = 500
TIMEOUT = 5


def fetch(url: str, accept: str = "application/json"):
    try:
        request = urllib.request.Request(
            url,
            headers={"Accept": accept, "User-Agent": "dependency-alternatives-search"},
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if "json" in response.headers.get("Content-Type", accept) else raw
    except urllib.error.HTTPError as exc:
        return False if exc.code == 404 else None
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
        return None


def age_days(timestamp: str | None) -> float | None:
    if not timestamp:
        return None
    try:
        stamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - stamp).total_seconds() / 86400


def stable(version: str) -> bool:
    return not re.search(r"(?:a|b|alpha|beta|rc|dev)[0-9.]*$", version, re.IGNORECASE)


def name_score(query: str, candidate: str) -> float:
    normalize = lambda value: re.sub(r"[-_.]+", "", value.lower())
    return difflib.SequenceMatcher(None, normalize(query), normalize(candidate)).ratio()


class PyPISearchParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.names: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href") or ""
        match = re.fullmatch(r"/project/([^/]+)/", urllib.parse.urlparse(href).path)
        if match:
            self.names.add(urllib.parse.unquote(match.group(1)))


def pypi_search(query: str, limit: int) -> list[str]:
    url = "https://pypi.org/search/?q=" + urllib.parse.quote(query)
    html = fetch(url, "text/html")
    if not isinstance(html, str):
        return []
    parser = PyPISearchParser()
    parser.feed(html)
    return sorted(parser.names, key=lambda name: name_score(query, name), reverse=True)[:limit]


def npm_search(query: str, limit: int) -> list[dict]:
    url = "https://registry.npmjs.org/-/v1/search?text=" + urllib.parse.quote(query)
    url += "&size=" + str(max(limit, 10))
    data = fetch(url)
    if not isinstance(data, dict):
        return []
    return [item.get("package") or {} for item in data.get("objects", [])]


def npm_weekly_downloads(name: str) -> int:
    encoded = urllib.parse.quote(name, safe="@/")
    data = fetch("https://api.npmjs.org/downloads/point/last-week/" + encoded)
    if not isinstance(data, dict):
        return 0
    try:
        return int(data.get("downloads") or 0)
    except (TypeError, ValueError):
        return 0


def verify_pypi(name: str, query: str) -> dict | None:
    data = fetch("https://pypi.org/pypi/" + urllib.parse.quote(name) + "/json")
    if not isinstance(data, dict):
        return None
    info = data.get("info") or {}
    version = str(info.get("version") or "")
    files = (data.get("releases") or {}).get(version) or []
    timestamps = [item.get("upload_time_iso_8601") for item in files if item.get("upload_time_iso_8601")]
    digests = [item.get("digests", {}).get("sha256") for item in files if item.get("digests", {}).get("sha256")]
    age = age_days(min(timestamps) if timestamps else None)
    if not version or not stable(version) or age is None or age < MIN_RELEASE_AGE_DAYS or not digests:
        return None
    return {
        "name": name,
        "ecosystem": "pypi",
        "latest_stable": version,
        "release_age_days": round(age, 1),
        "artifact_digest": True,
        "name_similarity": round(name_score(query, name), 3),
        "source": "https://pypi.org/pypi/" + urllib.parse.quote(name) + "/json",
        "needs_project_tests": True,
    }


def verify_npm(package: dict, query: str) -> dict | None:
    name = str(package.get("name") or "")
    if not name:
        return None
    data = fetch("https://registry.npmjs.org/" + urllib.parse.quote(name, safe="@/"))
    if not isinstance(data, dict):
        return None
    version = str((data.get("dist-tags") or {}).get("latest") or "")
    version_data = (data.get("versions") or {}).get(version) or {}
    dist = version_data.get("dist") or {}
    age = age_days((data.get("time") or {}).get(version))
    downloads = npm_weekly_downloads(name)
    if not version or not stable(version) or age is None or age < MIN_RELEASE_AGE_DAYS:
        return None
    if not (dist.get("integrity") or dist.get("shasum")) or downloads < MIN_WEEKLY_DOWNLOADS:
        return None
    return {
        "name": name,
        "ecosystem": "npm",
        "latest_stable": version,
        "release_age_days": round(age, 1),
        "weekly_downloads": downloads,
        "artifact_digest": True,
        "name_similarity": round(name_score(query, name), 3),
        "source": "https://registry.npmjs.org/" + urllib.parse.quote(name, safe="@/"),
        "needs_project_tests": True,
    }


def search(ecosystem: str, query: str, limit: int) -> list[dict]:
    if ecosystem == "npm":
        candidates = [verify_npm(package, query) for package in npm_search(query, limit * 2)]
    else:
        candidates = [verify_pypi(name, query) for name in pypi_search(query, limit * 2)]
    return sorted(
        [candidate for candidate in candidates if candidate],
        key=lambda item: (item["name_similarity"], item["release_age_days"]),
        reverse=True,
    )[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ecosystem", choices=("pypi", "npm"), required=False)
    parser.add_argument("--name", required=False)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        checks = [
            name_score("reqeusts", "requests") > name_score("reqeusts", "totally-other"),
            stable("1.2.3") and not stable("1.2.3rc1"),
        ]
        print("SELF-TEST: PASS" if all(checks) else "SELF-TEST: FAIL")
        return 0 if all(checks) else 1
    if not args.ecosystem:
        parser.error("--ecosystem is required unless --self-test is used")
    if not args.name:
        parser.error("--name is required unless --self-test is used")
    results = search(args.ecosystem, args.name, max(1, min(args.limit, 20)))
    if not results:
        print(json.dumps({
            "status": "no_verified_alternatives",
            "query": args.name,
            "ecosystem": args.ecosystem,
            "message": "No candidate passed canonical metadata, age, and artifact-digest checks; do not install an unverified package.",
        }, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "verified_candidates", "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
