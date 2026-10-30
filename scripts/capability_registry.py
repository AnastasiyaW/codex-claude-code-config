#!/usr/bin/env python3
"""capability_registry.py - is someone already building this, and which number is free?

Why: a branch can live on origin for days without a PR; its claims sit in one worktree
and say where, not what; a second line then builds the same capability under other names,
and both take the same ADR/migration number as "max + 1". No check sees the first line.

The shared state is GitHub, because every machine, harness and worktree already reads it:
open PRs, branches without a PR, and refs/reservations/<kind>/<n>.

Commands (GitHub API over HTTPS; token from GH_TOKEN, GITHUB_TOKEN or `gh auth token`; stdlib only):
  check    --repo O/N --config C.json [--capability ID ...] [--title TEXT] [--paths P ...]
           [--branch MINE] [--joins PR#|BRANCH ...] [--overlap-reason TEXT]
  check    --repo O/N --config C.json --ref BRANCH   judge an open PR/branch by itself
           (its body may carry `Joins: #N` and `Overlap-reason: <text>` lines)
  orphans  --repo O/N [--min-age-hours 24]        branches ahead of base with no open PR
  numbers  --repo O/N --config C.json [--ref B]    one number held by two different files
  reserve  --repo O/N --config C.json --kind K [--slug S] [--branch B]
  snapshot --repo O/N --out FILE                  freeze the live state (replay, tests)
check/orphans/numbers also take --snapshot FILE instead of reading GitHub.

Exit: 0 clear, 1 finding (same capability / heavy overlap / orphan / collision),
2 NOT CHECKED (GitHub unreachable, partial data, bad config). 2 is never a pass.
reserve: 0 and prints the number, 2 when no ref could be created.

Config (JSON):
  {"capabilities": {"<id>": {"synonyms": [...], "paths": [globs], "min_path_hits": 2}},
   "numbering": {"<kind>": {"regex": "^dir/(\\d{4})-(.+)\\.md$", "dir": "dir", "width": 4,
                            "reservation_required_above": 62}},
   "aggregate_refs": ["integration/*"]}
A PR declares its capability with a line `Capability: <id>[, <id>]` in its body; a branch
without a PR declares it the same way in a commit message.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import fnmatch
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

CLEAR, FOUND, UNKNOWN = 0, 1, 2
DECLARE_RE = re.compile(r"^\s*Capability:\s*(.+?)\s*$", re.I | re.M)
JOINS_RE = re.compile(r"^\s*Joins:\s*(.+?)\s*$", re.I | re.M)
REASON_RE = re.compile(r"^\s*Overlap-reason:\s*(.+?)\s*$", re.I | re.M)
OVERLAP_FILES = 10
MIN_AREA_DEPTH = 2  # an area like `src` covers everything; overlap is judged on `src/engine` and deeper
ACTIVE_DAYS = 14    # simplification: branches idle longer are counted as dormant, not fetched
RESERVE_TRIES = 50
SUBJECT_SHARE = 0.2  # calibration in capabilities_of()
PATH_SHARE = 0.25
WORKERS = 8
COMPARE_FILE_CAP = 300  # GitHub compare API lists at most 300 files


class NotChecked(Exception):
    """GitHub could not answer; the caller must report UNKNOWN, never a pass."""


# ---------------------------------------------------------------- GitHub (live) ---------
# One transport: the REST/GraphQL API over HTTPS. The token comes from GH_TOKEN or
# GITHUB_TOKEN (CI) or `gh auth token` (a workstation). No token is NOT CHECKED.

API = "https://api.github.com"
_TOKEN: list[str] = []


def token() -> str:
    if _TOKEN:
        return _TOKEN[0]
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not tok:
        try:
            tok = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True,
                                 timeout=30).stdout.strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise NotChecked(f"no GH_TOKEN/GITHUB_TOKEN and `gh auth token` failed: {exc}") from exc
    if not tok:
        raise NotChecked("no GH_TOKEN/GITHUB_TOKEN and `gh auth token` printed nothing")
    _TOKEN.append(tok)
    return tok


def http(method: str, url: str, payload: dict | None = None) -> tuple[int, object, str]:
    """(status, decoded JSON, Link header). Network failure raises NotChecked."""
    if not url.startswith("https://"):
        url = API + "/" + url.lstrip("/")
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token()}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "capability-registry"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
            return r.status, json.loads(body) if body else None, r.headers.get("Link") or ""
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(body), ""
        except json.JSONDecodeError:
            return exc.code, {"message": body[:300]}, ""
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise NotChecked(f"{method} {url}: {exc}") from exc


def _short(body) -> str:
    return str(body)[:300]


def get(path: str):
    """GET with Link-header pagination; a list endpoint returns the concatenated list."""
    out, url = None, path
    while url:
        status, body, link = http("GET", url)
        if status != 200:
            raise NotChecked(f"GET {path}: HTTP {status} {_short(body)}")
        if not isinstance(body, list):
            return body
        out = (out or []) + body
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = m.group(1) if m else None
    return out or []


def graphql(query: str, variables: dict) -> dict:
    status, body, _ = http("POST", "graphql", {"query": query, "variables": variables})
    if status != 200 or not isinstance(body, dict) or body.get("errors") or "data" not in body:
        raise NotChecked(f"graphql: HTTP {status} {_short(body)}")
    return body["data"]


def graphql_pages(query: str, variables: dict, path: list[str]) -> list[dict]:
    nodes, cursor = [], None
    while True:
        conn = graphql(query, {**variables, "endCursor": cursor})
        for key in path:
            conn = conn[key]
        nodes += conn["nodes"]
        if not conn["pageInfo"]["hasNextPage"]:
            return nodes
        cursor = conn["pageInfo"]["endCursor"]


PR_QUERY = """query($owner:String!,$name:String!,$endCursor:String){repository(owner:$owner,name:$name){
 pullRequests(states:OPEN,first:40,after:$endCursor){pageInfo{hasNextPage endCursor}
  nodes{number title body headRefName baseRefName createdAt
   commits(first:100){totalCount nodes{commit{oid message committedDate authoredDate}}}
   files(first:100){totalCount nodes{path changeType}}}}}}"""
PR_BY_HEAD_QUERY = """query($owner:String!,$name:String!,$head:String!){repository(owner:$owner,name:$name){
 pullRequests(states:OPEN,first:1,headRefName:$head){nodes{number title body headRefName baseRefName createdAt
   commits(first:100){totalCount nodes{commit{oid message committedDate authoredDate}}}
   files(first:100){totalCount nodes{path changeType}}}}}}"""
BRANCH_QUERY = """query($owner:String!,$name:String!,$endCursor:String){repository(owner:$owner,name:$name){
 refs(refPrefix:"refs/heads/",first:100,after:$endCursor){pageInfo{hasNextPage endCursor}
  nodes{name target{... on Commit{committedDate}}
   associatedPullRequests(first:20,states:[OPEN,MERGED,CLOSED]){nodes{number state closedAt}}}}}}"""
CHANGE = {"ADDED": "added", "DELETED": "removed", "MODIFIED": "modified", "RENAMED": "renamed",
          "COPIED": "copied", "CHANGED": "changed"}


def _commit_key(message: str, authored: str) -> str:
    """Survives a rebase (the sha does not): first line of the message + author date."""
    return (message.splitlines()[0] if message else "") + "|" + authored


def _pr_item(repo: str, pr: dict) -> dict:
    n = pr["number"]
    commits = [{"sha": c["commit"]["oid"], "message": c["commit"]["message"], "date": c["commit"]["committedDate"],
                "authored": c["commit"]["authoredDate"]} for c in pr["commits"]["nodes"]]
    if pr["commits"]["totalCount"] > len(commits):
        commits = [{"sha": c["sha"], "message": c["commit"]["message"], "date": c["commit"]["committer"]["date"],
                    "authored": c["commit"]["author"]["date"]}
                   for c in get(f"repos/{repo}/pulls/{n}/commits?per_page=100")]
    files = [{"path": f["path"], "status": CHANGE.get(f["changeType"], f["changeType"].lower())}
             for f in pr["files"]["nodes"]]
    if pr["files"]["totalCount"] > len(files):
        files = [{"path": f["filename"], "status": f["status"]}
                 for f in get(f"repos/{repo}/pulls/{n}/files?per_page=100")]
    dates = sorted(c["date"] for c in commits)
    return {"kind": "pr", "number": n, "ref": pr["headRefName"], "base": pr["baseRefName"],
            "title": pr["title"], "body": pr.get("body") or "", "created_at": pr["createdAt"],
            "subjects": [c["message"] for c in commits], "shas": [c["sha"] for c in commits],
            "commit_keys": [_commit_key(c["message"], c["authored"]) for c in commits], "files": files,
            "first_commit_at": dates[0] if dates else pr["createdAt"],
            "last_commit_at": dates[-1] if dates else pr["createdAt"]}


def _numbered_beyond_cap(repo: str, fork: str, name: str, numbering: dict, known: set[str]) -> list[dict]:
    """Compare lists at most 300 files: diff the numbered directories between the merge base and
    the branch tip (not the base tip: the base may have renumbered after the fork)."""
    added = []
    for spec in numbering.values():
        at_fork = {e["path"] for e in get(f"repos/{repo}/contents/{spec['dir']}?ref={fork}")}
        for e in get(f"repos/{repo}/contents/{spec['dir']}?ref={urllib.parse.quote(name)}"):
            if e["path"] not in at_fork and e["path"] not in known:
                added.append({"path": e["path"], "status": "added"})
    return added


def _branch_item(repo: str, base: str, name: str, numbering: dict | None = None) -> dict | None:
    cmp = get(f"repos/{repo}/compare/{urllib.parse.quote(base)}...{urllib.parse.quote(name)}")
    if not cmp.get("ahead_by"):
        return None
    commits = cmp.get("commits") or []
    dates = sorted(c["commit"]["committer"]["date"] for c in commits)
    files = [{"path": f["filename"], "status": f["status"]} for f in cmp.get("files") or []]
    truncated = len(files) >= COMPARE_FILE_CAP
    if truncated and numbering:
        files += _numbered_beyond_cap(repo, cmp["merge_base_commit"]["sha"], name, numbering,
                                      {f["path"] for f in files})
    return {"kind": "branch", "number": None, "ref": name, "base": base, "title": "", "body": "",
            "subjects": [c["commit"]["message"] for c in commits], "shas": [c["sha"] for c in commits],
            "commit_keys": [_commit_key(c["commit"]["message"], c["commit"]["author"]["date"]) for c in commits],
            "files": files,
            # simplification: beyond 300 files only the numbered directories are complete
            "files_truncated": truncated,
            "first_commit_at": dates[0] if dates else None, "last_commit_at": dates[-1] if dates else None}


def _branch_candidates(refs: list[dict], base: str, open_heads: set[str],
                       horizon: dt.datetime) -> tuple[list[str], list[str]]:
    """(branches to compare, dormant branches) among refs without an open PR."""
    candidates, dormant = [], []
    for r in refs:
        nm = r["name"]
        if nm == base or nm in open_heads:
            continue
        last = _ts((r.get("target") or {}).get("committedDate"))
        closed = [_ts(p.get("closedAt")) for p in r["associatedPullRequests"]["nodes"]]
        if closed and last and all(c and last <= c for c in closed):
            continue  # its PR was merged/closed and nothing was pushed after
        (dormant if not last or last < horizon else candidates).append(nm)
    return candidates, dormant


def collect(repo: str, now: dt.datetime | None = None, active_days: int = ACTIVE_DAYS,
            numbering: dict | None = None) -> dict:
    """In-flight state of `repo`. With `numbering`, also the numbered files on the base."""
    now = now or dt.datetime.now(dt.timezone.utc)
    owner, name = repo.split("/", 1)
    base = get(f"repos/{repo}")["default_branch"]
    var = {"owner": owner, "name": name}
    prs = graphql_pages(PR_QUERY, var, ["repository", "pullRequests"])
    refs = graphql_pages(BRANCH_QUERY, var, ["repository", "refs"])
    on_base = base_files(repo, base, numbering) if numbering else {}
    candidates, dormant = _branch_candidates(refs, base, {p["headRefName"] for p in prs},
                                             now - dt.timedelta(days=active_days))
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = [pool.submit(_pr_item, repo, p) for p in prs]
        futs += [pool.submit(_branch_item, repo, base, nm, numbering) for nm in candidates]
        # NotChecked propagates from result(): partial data is not a pass
        items = [it for it in (f.result() for f in futs) if it]
    snap = {"repo": repo, "base": base, "now": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "items": items, "dormant_branches": sorted(dormant),
            "reservations": [{"ref": r["ref"]} for r in get(f"repos/{repo}/git/matching-refs/reservations/")]}
    if numbering:
        snap["base_files"] = on_base
    return snap


def refresh(snap: dict, ref: str, numbering: dict | None = None) -> dict:
    """A reused snapshot with one ref re-read now (a CI run judges its own fresh state);
    reservations and base files are re-read too. The age of the rest stays in `now`."""
    repo, base = snap["repo"], snap["base"]
    owner, name = repo.split("/", 1)
    found = graphql(PR_BY_HEAD_QUERY, {"owner": owner, "name": name, "head": ref})
    nodes = found["repository"]["pullRequests"]["nodes"]
    on_base = base_files(repo, base, numbering) if numbering else snap.get("base_files", {})
    fresh = _pr_item(repo, nodes[0]) if nodes else (
        None if ref == base else _branch_item(repo, base, ref, numbering))
    items = [i for i in snap["items"] if i["ref"] != ref] + ([fresh] if fresh else [])
    out = {**snap, "items": items, "refreshed": ref,
           "reservations": [{"ref": r["ref"]} for r in get(f"repos/{repo}/git/matching-refs/reservations/")]}
    if numbering:
        out["base_files"] = on_base
    return out


# ---------------------------------------------------------------- pure logic ------------

def _ts(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def norm(text: str) -> str:
    return " " + re.sub(r"[\W_]+", " ", text.lower()).strip() + " "


def declared(item: dict) -> set[str]:
    out: set[str] = set()
    for text in [item.get("body") or ""] + list(item.get("subjects") or []):
        for m in DECLARE_RE.finditer(text):
            out |= {x.strip().lower() for x in m.group(1).split(",") if x.strip()}
    return out


def synonym_hits(text: str, spec: dict, cap_id: str) -> list[str]:
    t = norm(text)
    hits = []
    for syn in [cap_id.replace("-", " ")] + list(spec.get("synonyms") or []):
        s = norm(syn).strip()
        # left word boundary only: "large document" also matches "large documents"
        if s and re.search(r"(?<!\w)" + re.escape(s), t):
            hits.append(syn)
    return hits


def path_hits(paths: list[str], spec: dict) -> list[str]:
    globs = spec.get("paths") or []
    return [p for p in paths if any(fnmatch.fnmatch(p, g) for g in globs)]


def capabilities_of(item: dict, vocab: dict) -> dict[str, list[str]]:
    """capability id -> human-readable reasons.

    Strong signals: a declared `Capability:` line, words in the title or branch name.
    Weak signals need a majority-like share, because long branches carry unrelated
    commits and shared files: words in at least SUBJECT_SHARE of commit subjects (and
    two of them), paths in at least PATH_SHARE of the changed files (and min_path_hits).
    Calibrated 2026-10-30 on about 90 PRs/branches in flight in one real repository."""
    out: dict[str, list[str]] = {}
    for cap in declared(item):
        out.setdefault(cap, []).append("declared Capability:")
    head = " ".join([item.get("title") or "", item.get("ref") or ""])
    # first line only: a commit body often lists what the change is NOT
    subjects = [s.splitlines()[0] for s in item.get("subjects") or [] if s]
    paths = [f["path"] for f in item.get("files") or []]
    for cap, spec in vocab.items():
        syn = synonym_hits(head, spec, cap)
        if syn:
            out.setdefault(cap, []).append("words: " + ", ".join(sorted(set(syn))))
        matching = [x for x in subjects if synonym_hits(x, spec, cap)]
        if len(matching) >= max(2, SUBJECT_SHARE * len(subjects)):
            out.setdefault(cap, []).append(f"{len(matching)} of {len(subjects)} commit subjects")
        ph = path_hits(paths, spec)
        if len(ph) >= max(int(spec.get("min_path_hits", 2)), PATH_SHARE * len(paths)):
            out.setdefault(cap, []).append(f"{len(ph)} of {len(paths)} files on its paths")
    return out


def _label(item: dict) -> str:
    return f"PR #{item['number']} ({item['ref']})" if item["kind"] == "pr" else f"branch {item['ref']} (no PR)"


def stack_of(items: list[dict], joins: list[str], base: str) -> set[str]:
    """Refs of every PR/branch in the same stack as a joined PR or branch (never via the base)."""
    by_num = {str(i["number"]): i["ref"] for i in items if i.get("number") is not None}
    want = {by_num.get(j.lstrip("#"), j) for j in joins}
    edges: dict[str, set[str]] = {}
    for i in items:
        if i.get("base") and i["base"] != base:
            edges.setdefault(i["ref"], set()).add(i["base"])
            edges.setdefault(i["base"], set()).add(i["ref"])
    seen, todo = set(), list(want)
    while todo:
        r = todo.pop()
        if r in seen:
            continue
        seen.add(r)
        todo.extend(edges.get(r, ()))
    return seen


def under(path: str, area: str) -> bool:
    if any(ch in area for ch in "*?["):
        return fnmatch.fnmatch(path, area)
    return path == area or path.startswith(area.rstrip("/") + "/")


def check(snap: dict, vocab: dict, caps: list[str], title: str, paths: list[str], branch: str,
          joins: list[str], overlap_files: int = OVERLAP_FILES, aggregate: list[str] = (),
          own_commits: list[str] = ()) -> tuple[list[dict], list[str]]:
    """In-flight work that duplicates the given one. Not a duplicate: the same stack, a joined
    line, and any PR/branch that shares a commit with it (one line built on the other).
    `aggregate` globs name integration branches: only a declared Capability line counts there,
    because they carry everybody's commits and files."""
    caps = {c.lower() for c in caps}
    unknown = sorted(c for c in caps if c not in vocab)
    if unknown:
        raise ValueError(f"unknown capability {unknown}; known: {sorted(vocab)}")
    if title:
        for cap, spec in vocab.items():
            if synonym_hits(title, spec, cap):
                caps.add(cap)
    notes = []
    areas = [a.strip().strip("/").replace("\\", "/") for a in paths if a.strip()]
    broad = [a for a in areas if len(a.split("/")) < MIN_AREA_DEPTH and not any(ch in a for ch in "*?[")]
    if broad:
        notes.append(f"area {broad} is too broad for a path-overlap verdict; capability check still applies")
    areas = [a for a in areas if a not in broad]
    if not caps and not areas:
        raise ValueError("nothing to check: give --capability, a --title that names one, or a --paths area")
    skip = stack_of(snap["items"], joins, snap["base"]) | ({branch} if branch else set())
    own = set(own_commits)
    findings = []
    for it in snap["items"]:
        if it["ref"] in skip or own & (set(it.get("shas") or []) | set(it.get("commit_keys") or [])):
            continue
        agg = any(fnmatch.fnmatch(it["ref"], g) for g in aggregate)
        said = declared(it)
        # a line that says what it builds is taken at its word; only silent lines are inferred
        if said or agg:
            theirs = {c: ["declared Capability:"] for c in said}
        else:
            theirs = capabilities_of(it, vocab)
            if it["kind"] == "pr":
                # a PR has a title: commit-subject and path shares only speak for branches without one
                theirs = {c: r for c, r in theirs.items() if any(x.startswith("words: ") for x in r)}
        files = [] if agg else [f["path"] for f in it.get("files") or []]
        same = sorted(caps & set(theirs))
        overlap = [p for p in files if any(under(p, a) for a in areas)]
        if same:
            findings.append({"type": "same-capability", "item": _label(it), "ref": it["ref"],
                             "number": it.get("number"), "capability": same,
                             "why": "; ".join(r for c in same for r in theirs[c])})
        elif len(overlap) >= overlap_files:
            findings.append({"type": "path-overlap", "item": _label(it), "ref": it["ref"],
                             "number": it.get("number"), "files": len(overlap), "example": overlap[:3]})
    return findings, notes


def _own_intent(mine: dict, vocab: dict) -> tuple[list[str], list[str]]:
    """What a line says it builds (declared, else inferred) and which files it changes."""
    caps = sorted(c for c in (declared(mine) or capabilities_of(mine, vocab)) if c in vocab)
    return caps, [f["path"] for f in mine.get("files") or []]


def body_lines(body: str) -> tuple[list[str], str]:
    """(`Joins:` refs, `Overlap-reason:` text) from a PR body."""
    joins = [j.strip() for m in JOINS_RE.finditer(body) for j in m.group(1).split(",") if j.strip()]
    return joins, " ".join(m.group(1) for m in REASON_RE.finditer(body))


def check_ref(snap: dict, vocab: dict, ref: str, overlap_files: int = OVERLAP_FILES, aggregate: list[str] = ()):
    """Judge an in-flight PR/branch against all others: its own capabilities and files.
    `Joins: #N|branch` and `Overlap-reason: text` lines in its body are honoured.
    Returns (findings, notes, overlap reason or "")."""
    mine = next((i for i in snap["items"] if i["ref"] == ref), None)
    if mine is None:
        raise ValueError(f"{ref} is not an open PR or a branch ahead of {snap['base']}")
    joins, reason = body_lines(mine.get("body") or "")
    joins = [ref] + joins
    if any(fnmatch.fnmatch(ref, g) for g in aggregate):
        return [], [f"{ref} is an integration branch; its members are judged one by one"], reason
    caps, files = _own_intent(mine, vocab)
    if not caps and not files:
        return [], [f"{ref} names no capability and changes no files"], reason
    findings, notes = check(snap, vocab, caps, "", files, ref, joins, overlap_files, aggregate,
                            (mine.get("shas") or []) + (mine.get("commit_keys") or []))
    return findings, notes, reason


def orphans(snap: dict, min_age_hours: float) -> list[dict]:
    """PR-less branches: ahead of the base for min_age_hours or longer, and dormant ones
    (idle longer than ACTIVE_DAYS, not compared: ahead or not is unknown)."""
    now = _ts(snap["now"])
    out = [{"type": "dormant-branch", "item": f"branch {r} (no PR, idle)", "ref": r}
           for r in snap.get("dormant_branches") or []]
    for it in snap["items"]:
        if it["kind"] != "branch":
            continue
        first = _ts(it.get("first_commit_at"))
        if first and (now - first).total_seconds() >= min_age_hours * 3600:
            out.append({"type": "orphan-branch", "item": _label(it), "ref": it["ref"],
                        "age_hours": round((now - first).total_seconds() / 3600, 1),
                        "commits": len(it.get("subjects") or [])})
    return out


def _holders(snap: dict, numbering: dict) -> tuple[dict, int]:
    """(kind, number) -> slug -> labels of the lines that add it; and the count of numbered files."""
    holders: dict[tuple[str, int], dict[str, set[str]]] = {}
    seen = 0
    sources = [(snap["base"], snap.get("base_files", {}), None)] + [(_label(i), None, i) for i in snap["items"]]
    for kind, spec in numbering.items():
        rx = re.compile(spec["regex"])
        for label, base_files, it in sources:
            paths = base_files.get(kind, []) if it is None else [
                f["path"] for f in it.get("files") or [] if f.get("status") in ("added", "renamed", "copied")]
            for m in filter(None, map(rx.match, paths)):
                seen += 1
                holders.setdefault((kind, int(m.group(1))), {}).setdefault(m.group(2), set()).add(label)
    return holders, seen


def _involves(mine: str | None, slugs: dict, base: str) -> bool:
    # the base answers only for its own duplicates; a branch reusing a base number is that branch's finding
    return mine is None or sum(mine in h for h in slugs.values()) >= (2 if mine == base else 1)


def _unreserved(snap: dict, spec: dict, kind: str, num: int, holder: list[str], reserved: set[str]) -> dict | None:
    limit = spec.get("reservation_required_above")
    ref = f"refs/reservations/{kind}/{num:0{int(spec['width'])}d}"
    if limit is None or num <= int(limit) or ref in reserved or snap["base"] in holder:
        return None
    return {"type": "number-unreserved", "kind": kind, "number": num, "holders": holder, "missing": ref}


def number_collisions(snap: dict, numbering: dict, scope: str | None = None) -> tuple[list[dict], int]:
    """One (kind, number) held by two different slugs. Stacked PRs that carry the same file
    (same slug) count once. With `scope` (a ref, or the base) only findings that involve it.
    Returns findings and the count of numbered files seen."""
    holders, seen = _holders(snap, numbering)
    reserved = {r["ref"] for r in snap.get("reservations") or []}
    findings = []
    mine = scope if scope in (None, snap["base"]) else next((_label(i) for i in snap["items"] if i["ref"] == scope), "-")
    for (kind, num), slugs in sorted(holders.items()):
        if len(slugs) > 1:
            if _involves(mine, slugs, snap["base"]):
                findings.append({"type": "number-collision", "kind": kind, "number": num,
                                 "holders": {s: sorted(h) for s, h in sorted(slugs.items())}})
            continue
        holder = sorted(next(iter(slugs.values())))
        f = _unreserved(snap, numbering[kind], kind, num, holder, reserved)
        if f and (mine is None or mine in holder):
            findings.append(f)
    return findings, seen


def next_number(snap: dict, spec: dict, kind: str) -> int:
    rx = re.compile(spec["regex"])
    nums = [0]
    for path in snap.get("base_files", {}).get(kind, []):
        m = rx.match(path)
        if m:
            nums.append(int(m.group(1)))
    for it in snap["items"]:
        for f in it.get("files") or []:
            m = rx.match(f["path"])
            if m:
                nums.append(int(m.group(1)))
    pre = f"refs/reservations/{kind}/"
    for r in snap.get("reservations") or []:
        if r["ref"].startswith(pre) and r["ref"][len(pre):].isdigit():
            nums.append(int(r["ref"][len(pre):]))
    return max(nums) + 1


# ---------------------------------------------------------------- reserve (live) --------

class LiveRefs:
    def __init__(self, repo: str):
        self.repo = repo

    def head_sha(self, branch: str) -> str:
        return get(f"repos/{self.repo}/commits/{urllib.parse.quote(branch)}")["sha"]

    def create(self, ref: str, sha: str, message: str) -> bool:
        """True = created, False = already taken. NotChecked on any other failure.
        The annotated tag object carries who reserved it; the ref creation is the atomic step."""
        status, tag, _ = http("POST", f"repos/{self.repo}/git/tags", {
            "tag": ref.split("/", 2)[2].replace("/", "-"), "message": message, "object": sha, "type": "commit"})
        if status != 201:
            raise NotChecked(f"create tag object: HTTP {status} {_short(tag)}")
        status, body, _ = http("POST", f"repos/{self.repo}/git/refs", {"ref": ref, "sha": tag["sha"]})
        if status == 201:
            return True
        if status == 422 and "already exists" in str(body).lower():
            return False
        raise NotChecked(f"create {ref}: HTTP {status} {_short(body)}")


def reserve(refs, snap: dict, spec: dict, kind: str, slug: str, branch: str) -> int:
    width = int(spec["width"])
    n = next_number(snap, spec, kind)
    sha = refs.head_sha(branch or snap["base"])
    for _ in range(RESERVE_TRIES):
        ref = f"refs/reservations/{kind}/{n:0{width}d}"
        msg = json.dumps({"kind": kind, "number": n, "slug": slug, "branch": branch})
        if refs.create(ref, sha, msg):
            return n
        n += 1
    raise NotChecked(f"{RESERVE_TRIES} numbers after the start were all taken")


def base_files(repo: str, base: str, numbering: dict) -> dict[str, list[str]]:
    return {kind: [e["path"] for e in get(f"repos/{repo}/contents/{spec['dir']}?ref={urllib.parse.quote(base)}")]
            for kind, spec in numbering.items()}


# ---------------------------------------------------------------- CLI -------------------

def load_config(path: str | None) -> dict:
    if not path:
        return {}
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(cfg.get("capabilities", {}), dict) or not isinstance(cfg.get("numbering", {}), dict):
        raise ValueError("config: capabilities and numbering must be objects")
    return cfg


def get_snapshot(a, cfg: dict) -> dict:
    if a.snapshot:
        return json.loads(Path(a.snapshot).read_text(encoding="utf-8"))
    return collect(a.repo, numbering=cfg.get("numbering"))


def reused(a, cfg: dict) -> tuple[dict | None, str]:
    """A cached snapshot of the same repo younger than --max-age-min, with --refresh-ref re-read."""
    if not a.reuse or not Path(a.reuse).is_file():
        return None, ""
    try:
        snap = json.loads(Path(a.reuse).read_text(encoding="utf-8"))
        age = (dt.datetime.now(dt.timezone.utc) - _ts(snap["now"])).total_seconds() / 60
    except (OSError, ValueError, KeyError, TypeError):
        return None, ""  # an unreadable cache is collected afresh, not trusted
    if snap.get("repo") != a.repo or age > a.max_age_min:
        return None, ""
    if a.refresh_ref:
        snap = refresh(snap, a.refresh_ref, cfg.get("numbering"))
    return snap, f"reused ({age:.1f} min old, refreshed {a.refresh_ref or 'nothing'})"


def emit(a, verdict: str, findings: list, extra: dict) -> None:
    if getattr(a, "json", False):
        print(json.dumps({"verdict": verdict, "findings": findings, **extra}, ensure_ascii=False, indent=2))
        return
    print(f"[capability-registry] {verdict}")
    for f in findings:
        print("  - " + json.dumps(f, ensure_ascii=False))
    for k, v in extra.items():
        print(f"  {k}: {v}")


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="capability_registry.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "orphans", "numbers", "reserve", "snapshot"):
        p = sub.add_parser(name)
        p.add_argument("--repo")
        p.add_argument("--config")
        p.add_argument("--json", action="store_true")
        if name in ("check", "orphans", "numbers"):
            p.add_argument("--snapshot")
    c = sub.choices["check"]
    c.add_argument("--capability", nargs="*", default=[])
    c.add_argument("--title", default="")
    c.add_argument("--paths", nargs="*", default=[])
    c.add_argument("--branch", default="")
    c.add_argument("--joins", nargs="*", default=[])
    c.add_argument("--overlap-reason", default="")
    c.add_argument("--overlap-files", type=int, default=OVERLAP_FILES)
    c.add_argument("--ref", help="judge this open PR/branch by its own capabilities and files")
    sub.choices["orphans"].add_argument("--min-age-hours", type=float, default=24)
    sub.choices["numbers"].add_argument("--ref", help="only findings that involve this branch (or the base)")
    r = sub.choices["reserve"]
    r.add_argument("--kind", required=True)
    r.add_argument("--slug", default="")
    r.add_argument("--branch", default="")
    sn = sub.choices["snapshot"]
    sn.add_argument("--out", required=True)
    sn.add_argument("--reuse", help="reuse this snapshot when younger than --max-age-min (CI cache)")
    sn.add_argument("--max-age-min", type=float, default=5)
    sn.add_argument("--refresh-ref", help="with --reuse: re-read this one ref now")
    return ap


def _cmd_snapshot(a, cfg: dict) -> int:
    snap, how = reused(a, cfg)
    if snap is None:
        snap, how = get_snapshot(argparse.Namespace(snapshot=None, repo=a.repo), cfg), "collected"
    tmp = Path(f"{a.out}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(a.out)  # atomic: a parallel reader sees the old or the new file, never half
    print(f"SCANNED: items={len(snap['items'])} dormant={len(snap['dormant_branches'])} {how} -> {a.out}")
    return CLEAR


def _cmd_reserve(a, cfg: dict) -> int:
    spec = cfg.get("numbering", {}).get(a.kind)
    if not spec:
        raise ValueError(f"kind {a.kind!r} is not in config numbering")
    snap = get_snapshot(argparse.Namespace(snapshot=None, repo=a.repo), cfg)
    n = reserve(LiveRefs(a.repo), snap, spec, a.kind, a.slug, a.branch)
    print(f"{n:0{int(spec['width'])}d}")
    return CLEAR


def _cmd_check(a, cfg: dict, snap: dict, scanned: dict) -> int:
    reason = a.overlap_reason
    if a.ref:
        findings, notes, body_reason = check_ref(snap, cfg.get("capabilities", {}), a.ref, a.overlap_files,
                                                 cfg.get("aggregate_refs", []))
        reason = reason or body_reason
    else:
        findings, notes = check(snap, cfg.get("capabilities", {}), a.capability, a.title, a.paths,
                                a.branch, a.joins, a.overlap_files, cfg.get("aggregate_refs", []))
    if notes:
        scanned["notes"] = notes
    if findings and reason:
        emit(a, "ACKNOWLEDGED", findings, {**scanned, "overlap_reason": reason})
        return CLEAR
    emit(a, "IN-FLIGHT ELSEWHERE" if findings else "CLEAR", findings, scanned)
    return FOUND if findings else CLEAR


def _cmd_orphans(a, cfg: dict, snap: dict, scanned: dict) -> int:
    findings = orphans(snap, a.min_age_hours)
    emit(a, "ORPHANS" if findings else "CLEAR", findings, scanned)
    return FOUND if findings else CLEAR


def _cmd_numbers(a, cfg: dict, snap: dict, scanned: dict) -> int:
    findings, seen = number_collisions(snap, cfg.get("numbering", {}), a.ref)
    scanned["SCANNED"] += f" numbered_files={seen}"
    if not seen:
        emit(a, "NOT CHECKED", [], {**scanned, "reason": "0 numbered files seen - wrong config?"})
        return UNKNOWN
    emit(a, "COLLISION" if findings else "CLEAR", findings, scanned)
    return FOUND if findings else CLEAR


def main(argv: list[str] | None = None) -> int:
    a = _parser().parse_args(argv)
    try:
        cfg = load_config(a.config)
        if not a.repo and not getattr(a, "snapshot", None):
            raise ValueError(f"{a.cmd} needs --repo" + (" or --snapshot" if a.cmd in ("check", "orphans", "numbers") else ""))
        if a.cmd in ("snapshot", "reserve"):
            return {"snapshot": _cmd_snapshot, "reserve": _cmd_reserve}[a.cmd](a, cfg)
        snap = get_snapshot(a, cfg)
        scanned = {"SCANNED": f"items={len(snap['items'])} dormant_branches={len(snap.get('dormant_branches') or [])}"}
        return {"check": _cmd_check, "orphans": _cmd_orphans, "numbers": _cmd_numbers}[a.cmd](a, cfg, snap, scanned)
    except NotChecked as exc:
        print(f"[capability-registry] NOT CHECKED: {exc}", file=sys.stderr)
        return UNKNOWN
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        print(f"[capability-registry] NOT CHECKED (input): {exc}", file=sys.stderr)
        return UNKNOWN


if __name__ == "__main__":
    sys.exit(main())
