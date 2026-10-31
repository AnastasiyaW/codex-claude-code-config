#!/usr/bin/env python3
"""safe_merge.py - the only sanctioned way an agent lands a pull request on the default branch.

    python safe_merge.py <owner/repo> <pr> [--gh "<command>"] [--lock-dir DIR]
    python safe_merge.py --self-test

Merge-queue semantics without a merge queue: a PR is merged only when
  1. its base is the default branch (or a branch declared in `integration_branches`),
  2. its head already contains the current base tip - otherwise the branch is brought up
     to date with `gh pr update-branch` (a merge, never a rebase) and the call stops with
     "waiting for fresh CI"; a later call completes it,
  3. every check on the exact head commit is SUCCESS, SKIPPED or NEUTRAL, none pending,
     every `required` name is present, and at least one real check passed (unless the
     repository declares `allow_no_checks` with a reason),
  4. GitHub reports it MERGEABLE, and neither head nor base moved during the evaluation.
Then `gh pr merge --merge --match-head-commit <sha>`, and the result is verified: the PR is
MERGED and the merge commit's parents are exactly [base tip, tested head], i.e. the tree on
the default branch is the tree CI tested.

Per-repository policy lives in `.github/merge-gate.json`, read from the DEFAULT branch (a
PR cannot bless itself by editing its own allowlist):

    {
      "allow_unavailable": [
        {"name": "<check name>", "reason": "<why it cannot run>", "expires": "YYYY-MM-DD"}
      ],
      "required": ["<check name>", ...],
      "integration_branches": ["<branch>", ...],
      "allow_no_checks": "<reason this repository has no CI>"
    }

An allowlisted check may be in any state; an entry past its date, or dated more than
MAX_ALLOW_DAYS ahead, refuses every merge until the file is fixed. Unknown keys are an
error (a misspelt key must not silently drop a rule); keys starting with "_" are comments.

Merges into one repository are serialized by a lock file (stale after LOCK_STALE_SECONDS or
when its owner process is gone). The lock is per machine; the parent check after the merge
is what detects a race the lock cannot see.

Exit: 0 merged (or already merged), 1 refused or waiting (the reason is printed),
      2 not checked (gh failed, policy file malformed, mergeability unknown, or the merged
        result could not be verified as the tested combination).
Every run prints one `SCANNED:` line and one `RECEIPT:` JSON line, and appends the receipt
to ~/.claude/logs/safe-merge.jsonl.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path

MERGED, REFUSED, UNCHECKED = 0, 1, 2
MAX_ALLOW_DAYS = 90
LOCK_STALE_SECONDS = 30 * 60
PASS_CONCLUSIONS = {"success", "skipped", "neutral"}
PAGE = 100  # GitHub's maximum per_page for these list endpoints
GH_TIMEOUT, NOT_STARTED = 120, -1  # seconds per gh call; exit code when gh could not start
PROCESS_QUERY_LIMITED_INFORMATION, NO_HANDLE_INHERIT, STILL_ACTIVE = 0x1000, False, 259  # Win32 API
PREFIX = {MERGED: "OK: ", REFUSED: "REFUSED: ", UNCHECKED: "NOT CHECKED: "}
# A refusal is the start of the agent's own repair, not a stop (owner 2026-10-31: «их надо
# разбирать и решать проблемы»). Each line names the next action the agent takes itself.
NEXT_STEP = {
    "checks-failed": "read the failing logs (gh run view <run> --log-failed / gh pr checks), reproduce "
                     "locally, fix the cause on the PR branch, push, wait for the new head's checks, rerun",
    "checks-pending": "wait for the head's checks (one wait at most 50 min, rule long-wait-cache-ttl), then rerun; "
                      "a check stuck queued is a runner problem to diagnose, not a reason to stop",
    "updated-waiting-ci": "the branch now contains the base tip: run the repo's gates on the new head, wait for "
                          "its checks, rerun safe_merge",
    "conflicting": "merge the base into the PR branch in a worktree, resolve the conflicts by the "
                   "merge-conflict-resolution protocol (verified data, not by logic), run the gates, push, rerun",
    "head-moved": "someone pushed to the PR while it was checked: rerun on the new head",
    "base-moved": "the base moved while merging: rerun; safe_merge brings the branch up to date",
    "mergeable-unknown": "GitHub is still computing mergeability: rerun in a minute",
    "locked": "another merge holds the lock: rerun after it finishes",
    "no-checks": "a repo without CI: add allow_no_checks with the local gates to .github/merge-gate.json "
                 "on the default branch, or merge with --owner-approved-no-checks when the owner asked to merge",
    "draft": "finish the work and mark the PR ready (gh pr ready) if it is yours; otherwise ask its author",
    "wrong-base": "retarget the PR to the default branch (gh pr edit --base) or declare the integration branch",
    "allowlist-expired": "fix the check or renew the allow_unavailable entry with a new reason and date",
}
CONFIG_PATH = ".github/merge-gate.json"
CONFIG_KEYS = {"allow_unavailable", "required", "integration_branches", "allow_no_checks"}
RECEIPT_LOG = Path.home() / ".claude" / "logs" / "safe-merge.jsonl"
DEFAULT_LOCK_DIR = Path.home() / ".claude" / "state" / "safe-merge-locks"


class GhError(Exception):
    def __init__(self, args: list[str], code: int, stderr: str) -> None:
        super().__init__(f"gh {' '.join(args)} -> exit {code}: {stderr.strip()[:400]}")
        self.stderr = stderr


class Outcome(Exception):
    """Ends the run with an exit code and a reason."""

    def __init__(self, code: int, result: str, reason: str) -> None:
        super().__init__(reason)
        self.code, self.result, self.reason = code, result, reason


def invoke(prefix: list[str], args: list[str]) -> tuple[int, str, str]:
    """Run one gh command: (exit code, stdout, stderr); -1 when it could not start."""
    try:
        proc = subprocess.run([*prefix, *args], capture_output=True, encoding="utf-8", timeout=GH_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return NOT_STARTED, "", str(exc)
    return proc.returncode, proc.stdout, proc.stderr


class Gh:
    def __init__(self, prefix: list[str]) -> None:
        self.prefix = prefix

    def answer(self, args: list[str]) -> tuple[int, str, str]:
        return invoke(self.prefix, args)

    def run(self, *args: str) -> str:
        code, out, err = self.answer(list(args))
        if code != 0:
            raise GhError(list(args), code, err or out)
        return out

    def json(self, *args: str):
        out = self.run(*args)
        try:
            return json.loads(out)
        except json.JSONDecodeError as exc:
            raise GhError(list(args), 0, f"not JSON: {out}") from exc


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

def read_config(gh: Gh, repo: str, branch: str) -> dict:
    try:
        text = gh.run("api", "-H", "Accept: application/vnd.github.raw+json",
                      f"repos/{repo}/contents/{CONFIG_PATH}?ref={branch}")
    except GhError as exc:
        if "HTTP 404" in exc.stderr:
            return {}
        raise
    try:
        data = json.loads(text)
        if isinstance(data, dict) and data.get("encoding") == "base64" and "content" in data:
            # gh ignored the raw Accept header and returned the contents object
            data = json.loads(base64.b64decode(data["content"]).decode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise Outcome(UNCHECKED, "config-malformed", f"{CONFIG_PATH} is not JSON: {exc}")
    if not isinstance(data, dict):
        raise Outcome(UNCHECKED, "config-malformed", f"{CONFIG_PATH} must be a JSON object")
    return data


def _names(cfg: dict, key: str) -> list[str]:
    val = cfg.get(key, [])
    if not isinstance(val, list) or not all(isinstance(v, str) and v for v in val):
        raise Outcome(UNCHECKED, "config-malformed", f"{CONFIG_PATH}: {key} must be a list of names")
    return val


def validate_config(cfg: dict, today: dt.date) -> dict:
    """Normalized policy; raises Outcome on a malformed or expired policy."""
    unknown = sorted(k for k in cfg if not k.startswith("_") and k not in CONFIG_KEYS)
    if unknown:
        raise Outcome(UNCHECKED, "config-malformed", f"{CONFIG_PATH}: unknown keys {unknown}")
    entries = cfg.get("allow_unavailable", [])
    if not isinstance(entries, list):
        raise Outcome(UNCHECKED, "config-malformed", f"{CONFIG_PATH}: allow_unavailable must be a list")
    allow: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not all(isinstance(entry.get(k), str) and entry.get(k).strip()
                                                  for k in ("name", "reason", "expires")):
            raise Outcome(UNCHECKED, "config-malformed",
                          f"{CONFIG_PATH}: allow_unavailable entry needs name, reason, expires: {entry}")
        try:
            expires = dt.date.fromisoformat(entry["expires"])
        except ValueError:
            raise Outcome(UNCHECKED, "config-malformed",
                          f"{CONFIG_PATH}: expires is not YYYY-MM-DD: {entry['expires']}")
        if expires < today:
            raise Outcome(REFUSED, "allowlist-expired",
                          f"allowlist entry for '{entry['name']}' expired on {expires}: fix the check "
                          f"or renew the entry with a fresh reason in {CONFIG_PATH}")
        if (expires - today).days > MAX_ALLOW_DAYS:
            raise Outcome(REFUSED, "allowlist-too-long",
                          f"allowlist entry for '{entry['name']}' expires {expires}, more than "
                          f"{MAX_ALLOW_DAYS} days ahead")
        allow[entry["name"]] = entry
    no_checks = cfg.get("allow_no_checks")
    if no_checks is not None and not (isinstance(no_checks, str) and no_checks.strip()):
        raise Outcome(UNCHECKED, "config-malformed", f"{CONFIG_PATH}: allow_no_checks must be a reason")
    return {"allow": allow, "required": _names(cfg, "required"),
            "integration": _names(cfg, "integration_branches"), "allow_no_checks": no_checks}


# ---------------------------------------------------------------------------
# Checks on the exact head commit
# ---------------------------------------------------------------------------

def _paged(gh: Gh, path: str, key: str) -> list[dict]:
    """Every item of a paginated list endpoint (100 per page)."""
    items: list[dict] = []
    page = 1
    while True:
        batch = gh.json("api", f"{path}per_page={PAGE}&page={page}").get(key) or []
        items.extend(batch)
        if len(batch) < PAGE:
            return items
        page += 1


def collect_checks(gh: Gh, repo: str, sha: str) -> list[dict]:
    """[{name, state: pass|skip|pending|fail, detail}] from check runs, check suites and
    commit statuses of the exact commit."""
    checks: list[dict] = []
    for run in _paged(gh, f"repos/{repo}/commits/{sha}/check-runs?filter=latest&", "check_runs"):
        status = (run.get("status") or "").lower()
        conclusion = (run.get("conclusion") or "").lower()
        if status != "completed":
            state = "pending"
        elif conclusion == "success":
            state = "pass"
        elif conclusion in PASS_CONCLUSIONS:
            state = "skip"
        else:
            state = "fail"
        checks.append({"name": run.get("name") or "?", "state": state, "detail": f"{status}/{conclusion}"})
    # A workflow whose jobs do not exist yet (needs:, dynamic matrix) shows only as an
    # unfinished suite. Suites of other apps with no runs stay queued forever: ignored.
    for suite in _paged(gh, f"repos/{repo}/commits/{sha}/check-suites?", "check_suites"):
        app = ((suite.get("app") or {}).get("slug") or "?").lower()
        if (suite.get("status") or "").lower() != "completed" and (
                app == "github-actions" or suite.get("latest_check_runs_count")):
            checks.append({"name": f"suite:{app}:{suite.get('id')}", "state": "pending",
                           "detail": f"suite/{suite.get('status')}"})
    for st in _paged(gh, f"repos/{repo}/commits/{sha}/status?", "statuses"):
        raw = (st.get("state") or "").lower()
        state = {"success": "pass", "pending": "pending"}.get(raw, "fail")
        checks.append({"name": st.get("context") or "?", "state": state, "detail": f"status/{raw}"})
    return checks


def evaluate_checks(checks: list[dict], policy: dict) -> dict:
    allow, required = policy["allow"], policy["required"]
    counted = [c for c in checks if c["name"] not in allow]
    passed = [c["name"] for c in counted if c["state"] == "pass"]
    done = passed + [c["name"] for c in counted if c["state"] == "skip"]
    pending = [c["name"] for c in counted if c["state"] == "pending"]
    failed = [f"{c['name']} ({c['detail']})" for c in counted if c["state"] == "fail"]
    missing = [r for r in required if r not in done and r not in pending and r not in allow]
    summary = {"checks": len(checks), "passed": len(passed), "pending": pending, "failed": failed,
               "allowlisted": sorted({c["name"] for c in checks if c["name"] in allow}),
               "missing_required": missing}
    if failed:
        raise Outcome(REFUSED, "checks-failed", f"failed checks on head: {failed}")
    if pending or missing:
        raise Outcome(REFUSED, "checks-pending",
                      f"waiting for checks: pending={pending} not-reported-required={missing}")
    if not passed and not policy["allow_no_checks"]:
        raise Outcome(REFUSED, "no-checks",
                      "no check succeeded on this head: nothing was tested. Add CI, or declare "
                      f"allow_no_checks with a reason in {CONFIG_PATH} on the default branch")
    return summary


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------

def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, NO_HANDLE_INHERIT, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return bool(ok) and code.value == STILL_ACTIVE
    try:
        os.kill(pid, 0)  # signal 0: existence probe, nothing is delivered
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def _lock_stale(path: Path) -> bool:
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - path.stat().st_mtime
    except (OSError, ValueError):
        return True
    pid = info.get("pid") if isinstance(info, dict) else None
    if age > LOCK_STALE_SECONDS or not isinstance(pid, int) or pid <= 0:
        return True
    return info.get("host") == socket.gethostname() and not _pid_alive(pid)


class RepoLock:
    def __init__(self, lock_dir: Path, repo: str, pr: int) -> None:
        self.path = lock_dir / (repo.replace("/", "__") + ".lock")
        self.token = f"{socket.gethostname()}:{os.getpid()}:{time.time_ns()}"
        self.pr = pr

    def _create(self) -> bool:
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"token": self.token, "host": socket.gethostname(), "pid": os.getpid(),
                       "pr": self.pr, "started": dt.datetime.now().isoformat(timespec="seconds")}, fh)
        return True

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._create():
            return
        if not _lock_stale(self.path):
            try:
                holder = self.path.read_text(encoding="utf-8")
            except OSError:
                holder = "?"
            raise Outcome(REFUSED, "locked", f"another merge into this repository is running: {holder}")
        try:
            # a stale lock is moved aside atomically, then removed (our own state file)
            stale = self.path.with_name(f"{self.path.name}.stale-{time.time_ns()}")
            os.replace(self.path, stale)
            stale.unlink()
        except OSError:
            pass
        if not self._create():
            raise Outcome(REFUSED, "locked", "could not take the repository lock (contended)")

    def held(self) -> bool:
        """Still ours? A competitor that judged the same stale lock may have moved ours away."""
        try:
            return json.loads(self.path.read_text(encoding="utf-8")).get("token") == self.token
        except (OSError, ValueError, AttributeError):
            return False

    def release(self) -> None:
        if self.held():
            try:
                self.path.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# The merge
# ---------------------------------------------------------------------------

PR_FIELDS = "number,state,isDraft,baseRefName,headRefName,headRefOid,mergeable,url"


def _ref_sha(gh: Gh, repo: str, branch: str) -> str:
    return gh.json("api", f"repos/{repo}/git/ref/heads/{branch}")["object"]["sha"]


def _state(obj: dict) -> str:
    return str(obj.get("state") or "").upper()


def safe_merge(gh: Gh, repo: str, number: int, lock_dir: Path, receipt: dict,
               owner_no_checks: bool = False) -> None:
    """Raises Outcome; the caller maps it to an exit code. `owner_no_checks` lifts only the
    no-checks refusal (a repo without CI); merge-gate-guard lets the flag through only when the
    owner's latest chat message asks to merge (owner 2026-10-31: «ты сама вливать и мерить должна»)."""
    today = dt.date.today()
    pr = gh.json("pr", "view", str(number), "-R", repo, "--json", PR_FIELDS)
    receipt.update(pr=number, url=pr.get("url"), base=pr.get("baseRefName"), head=pr.get("headRefOid"))
    state = _state(pr)
    if state == "MERGED":
        raise Outcome(MERGED, "already-merged", "the PR is already MERGED (not merged by this call)")
    if state != "OPEN":
        raise Outcome(REFUSED, "not-open", f"the PR is {state}")
    if pr.get("isDraft"):
        raise Outcome(REFUSED, "draft", "the PR is a draft")

    default = gh.json("api", f"repos/{repo}")["default_branch"]
    policy = validate_config(read_config(gh, repo, default), today)
    if owner_no_checks and not policy["allow_no_checks"]:
        policy["allow_no_checks"] = "owner asked in chat to merge (--owner-approved-no-checks)"
    receipt["policy"] = {"allowlisted": sorted(policy["allow"]), "required": policy["required"],
                         "allow_no_checks": bool(policy["allow_no_checks"]),
                         "owner_approved_no_checks": bool(owner_no_checks)}
    base = pr["baseRefName"]
    if base != default and base not in policy["integration"]:
        raise Outcome(REFUSED, "wrong-base",
                      f"base is '{base}', not the default branch '{default}' or a declared "
                      "integration branch")

    lock = RepoLock(lock_dir, repo, number)
    lock.acquire()
    try:
        head = pr["headRefOid"]
        base_sha = _ref_sha(gh, repo, base)
        receipt["base_sha"] = base_sha
        relation = gh.json("api", f"repos/{repo}/compare/{base_sha}...{head}").get("status")
        receipt["relation"] = relation
        if relation not in ("ahead", "identical"):
            gh.run("pr", "update-branch", str(number), "-R", repo)
            raise Outcome(REFUSED, "updated-waiting-ci",
                          f"head did not contain the current {base} tip {base_sha[:12]} ({relation}); "
                          "the branch was updated with a merge commit. Waiting for fresh CI: run "
                          "safe_merge again once the checks on the new head finish")

        receipt["checks"] = evaluate_checks(collect_checks(gh, repo, head), policy)

        fresh = gh.json("pr", "view", str(number), "-R", repo, "--json", PR_FIELDS)
        if fresh.get("headRefOid") != head:
            raise Outcome(REFUSED, "head-moved", "the PR head moved during evaluation; run again")
        mergeable = str(fresh.get("mergeable") or "").upper()
        receipt["mergeable"] = mergeable
        if mergeable == "CONFLICTING":
            raise Outcome(REFUSED, "conflicting", "GitHub reports merge conflicts")
        if mergeable != "MERGEABLE":
            raise Outcome(UNCHECKED, "mergeable-unknown",
                          f"GitHub has not computed mergeability ({mergeable or 'empty'}); run again")
        if _ref_sha(gh, repo, base) != base_sha:
            raise Outcome(REFUSED, "base-moved", f"{base} moved during evaluation; run again")
        if not lock.held():
            raise Outcome(REFUSED, "lock-lost", "another merge took the repository lock; run again")

        try:
            gh.run("pr", "merge", str(number), "-R", repo, "--merge", "--match-head-commit", head)
        except GhError as exc:
            if _state(gh.json("pr", "view", str(number), "-R", repo, "--json", "state")) != "MERGED":
                raise Outcome(REFUSED, "merge-rejected", f"GitHub refused the merge: {exc}")
        done = gh.json("pr", "view", str(number), "-R", repo, "--json", "state,mergeCommit")
        if _state(done) != "MERGED":
            raise Outcome(UNCHECKED, "merge-unverified", f"after merge the PR state is {done.get('state')}")
        merge_sha = (done.get("mergeCommit") or {}).get("oid")
        receipt["merge_commit"] = merge_sha
        parents = [p.get("sha") for p in gh.json("api", f"repos/{repo}/commits/{merge_sha}").get("parents", [])]
        receipt["merge_parents"] = parents
        if parents != [base_sha, head]:
            raise Outcome(UNCHECKED, "merged-untested-combination",
                          f"MERGED, but the merge commit parents {parents} are not [{base_sha}, {head}]: "
                          f"{base} moved in the last moment, the merged tree was not the tested tree. "
                          "Check CI on the default branch now")
        raise Outcome(MERGED, "merged", f"merged {head[:12]} onto {base}@{base_sha[:12]} as {merge_sha[:12]}")
    finally:
        lock.release()


def run_gate(gh: Gh, repo: str, number: int, lock_dir: Path, log: Path | None = RECEIPT_LOG,
             owner_no_checks: bool = False) -> int:
    receipt: dict = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "repo": repo}
    try:
        safe_merge(gh, repo, number, lock_dir, receipt, owner_no_checks)
        outcome = Outcome(UNCHECKED, "no-outcome", "internal: safe_merge returned without an outcome")
    except Outcome as exc:
        outcome = exc
    except GhError as exc:
        outcome = Outcome(UNCHECKED, "gh-error", str(exc))
    except Exception as exc:  # noqa: BLE001 - any surprise is "not checked", never a merge
        outcome = Outcome(UNCHECKED, "bad-response", f"unexpected response or state: {exc!r}")
    receipt.update(exit=outcome.code, result=outcome.result, reason=outcome.reason)
    checks = receipt.get("checks") or {}
    print(f"SCANNED: repo={repo} pr={number} head={str(receipt.get('head'))[:12]} "
          f"base={receipt.get('base')}@{str(receipt.get('base_sha'))[:12]} "
          f"checks={checks.get('checks', 0)} passed={checks.get('passed', 0)} "
          f"allowlisted={len(checks.get('allowlisted', []))} result={outcome.result}")
    print("RECEIPT: " + json.dumps(receipt))
    print(PREFIX[outcome.code] + outcome.reason)
    if outcome.code != MERGED and outcome.result in NEXT_STEP:
        print("NEXT: " + NEXT_STEP[outcome.result])
    if log is not None:
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(receipt) + "\n")
        except OSError:
            pass
    return outcome.code


# ---------------------------------------------------------------------------
# Scenario fake (used by --self-test and by the fake gh shim in the tests)
# ---------------------------------------------------------------------------

class ScenarioGh(Gh):
    """Answers gh calls from a scenario dict and records them in self.calls.

    scenario keys: repo, default_branch, config (dict | None for 404 | str raw), pr (dict),
    base_shas (list, consumed per ref read, last one repeats), compare_status,
    check_runs (list, served 100 per page), statuses (list, 100 per page),
    check_suites (list), mergeable_after, head_after, merge_fails (bool),
    merged_despite_error (bool), merge_parents (list | None -> [base, head])
    """

    def __init__(self, scenario: dict) -> None:
        super().__init__([])
        self.s = scenario
        self.calls: list[list[str]] = []
        self.merged = False
        self.ref_reads = 0

    def answer(self, a: list[str]) -> tuple[int, str, str]:
        self.calls.append(list(a))
        s, repo = self.s, self.s["repo"]

        def ok(obj) -> tuple[int, str, str]:
            return 0, obj if isinstance(obj, str) else json.dumps(obj), ""

        def page_of(items: list, path: str) -> list:
            page = int(re.search(r"[?&]page=(\d+)", path).group(1))
            return items[(page - 1) * 100: page * 100]

        if a[:2] == ["pr", "view"]:
            pr = dict(s["pr"])
            if self.merged:
                pr.update(state="MERGED", mergeCommit={"oid": "m" * 40})
            elif len([c for c in self.calls if c[:2] == ["pr", "view"]]) > 1:
                pr["mergeable"] = s.get("mergeable_after", pr.get("mergeable"))
                pr["headRefOid"] = s.get("head_after", pr["headRefOid"])
                if s.get("steal_lock"):
                    Path(s["steal_lock"]).write_text(json.dumps({"token": "other", "pid": 1}),
                                                     encoding="utf-8")
            return ok(pr)
        if a[:2] == ["pr", "update-branch"]:
            return ok("")
        if a[:2] == ["pr", "merge"]:
            if s.get("merge_fails"):
                self.merged = bool(s.get("merged_despite_error"))
                return 1, "", "merge refused"
            self.merged = True
            return ok("")
        if a[:1] == ["api"]:
            path = a[-1]
            if path == f"repos/{repo}":
                return ok({"default_branch": s.get("default_branch", "master")})
            if path.startswith(f"repos/{repo}/contents/"):
                cfg = s.get("config")
                if cfg is None:
                    return 1, "", "gh: Not Found (HTTP 404)"
                return ok(cfg)
            if path.startswith(f"repos/{repo}/git/ref/heads/"):
                shas = s.get("base_shas") or ["b" * 40]
                sha = shas[min(self.ref_reads, len(shas) - 1)]
                self.ref_reads += 1
                return ok({"object": {"sha": sha}})
            if path.startswith(f"repos/{repo}/compare/"):
                return ok({"status": s.get("compare_status", "ahead")})
            if "/check-runs?" in path:
                runs = s.get("check_runs", [])
                return ok({"total_count": len(runs), "check_runs": page_of(runs, path)})
            if "/check-suites?" in path:
                suites = s.get("check_suites", [])
                return ok({"total_count": len(suites), "check_suites": page_of(suites, path)})
            if "/status?" in path:
                return ok({"state": "success", "statuses": page_of(s.get("statuses", []), path)})
            if path.startswith(f"repos/{repo}/commits/"):
                parents = s.get("merge_parents") or [(s.get("base_shas") or ["b" * 40])[0],
                                                     s["pr"]["headRefOid"]]
                return ok({"parents": [{"sha": p} for p in parents]})
        return 1, "", f"scenario has no answer for {a}"


def base_scenario() -> dict:
    return {
        "repo": "o/r", "default_branch": "master", "config": None,
        "pr": {"number": 5, "state": "OPEN", "isDraft": False, "baseRefName": "master",
               "headRefName": "feat", "headRefOid": "h" * 40, "mergeable": "MERGEABLE",
               "url": "https://example.invalid/o/r/pull/5"},
        "base_shas": ["b" * 40], "compare_status": "ahead",
        "check_runs": [{"name": "unit", "status": "completed", "conclusion": "success"}],
        "statuses": [],
    }


def _self_test() -> int:
    import tempfile

    today = dt.date.today()
    cases: list[tuple[str, dict, int, str]] = []

    def case(name: str, want: int, want_result: str, **change) -> None:
        s = base_scenario()
        s.update(change)
        cases.append((name, s, want, want_result))

    case("green and fresh merges", MERGED, "merged")
    case("stale head updates and waits", REFUSED, "updated-waiting-ci", compare_status="diverged")
    case("pending check refuses", REFUSED, "checks-pending",
         check_runs=[{"name": "unit", "status": "in_progress", "conclusion": None}])
    case("failed check refuses", REFUSED, "checks-failed",
         check_runs=[{"name": "unit", "status": "completed", "conclusion": "failure"}])
    case("expired allowlist refuses", REFUSED, "allowlist-expired",
         config={"allow_unavailable": [{"name": "x", "reason": "r",
                                        "expires": (today - dt.timedelta(days=1)).isoformat()}]})
    case("conflicting refuses", REFUSED, "conflicting", mergeable_after="CONFLICTING")
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, s, want, want_result in cases:
            gh = ScenarioGh(s)
            receipt: dict = {}
            try:
                safe_merge(gh, "o/r", 5, Path(tmp), receipt)
                got, result = UNCHECKED, "no-outcome"
            except Outcome as exc:
                got, result = exc.code, exc.result
            merged = any(c[:2] == ["pr", "merge"] for c in gh.calls)
            if (got, result) != (want, want_result) or merged != (want == MERGED):
                failures.append(f"{name}: got {got}/{result} merge_called={merged}")
    for f in failures:
        print("FAIL", f)
    print(f"SCANNED: cases={len(cases)} failures={len(failures)}")
    print(f"{'FAILED' if failures else 'OK'}: {len(failures)} failure(s)")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("repo", nargs="?", help="owner/repo")
    ap.add_argument("pr", nargs="?", type=int)
    ap.add_argument("--gh", default=os.environ.get("SAFE_MERGE_GH", "gh"),
                    help="gh command (tests point this at a fake)")
    ap.add_argument("--lock-dir", type=Path, default=DEFAULT_LOCK_DIR)
    ap.add_argument("--receipt-log", type=Path, default=RECEIPT_LOG)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--owner-approved-no-checks", action="store_true",
                    help="the owner asked in chat to merge; lifts only the no-checks refusal")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.repo or a.pr is None or a.repo.count("/") != 1:
        print("usage: safe_merge.py <owner/repo> <pr>", file=sys.stderr)
        return UNCHECKED
    return run_gate(Gh(shlex.split(a.gh.replace("\\", "/"))), a.repo, a.pr, a.lock_dir, a.receipt_log,
                    a.owner_approved_no_checks)


if __name__ == "__main__":
    raise SystemExit(main())
