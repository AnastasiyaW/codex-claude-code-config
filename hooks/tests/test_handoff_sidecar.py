# -*- coding: utf-8 -*-
"""Handoff JSON sidecar and the shared PROBLEMS.md parser.

A handoff X.md may carry X.json with the Closure Audit as fields. The guard
validates the sidecar when it exists and keeps accepting prose-only handoffs;
agent_roster prefers the sidecar's fields; PROBLEMS.md status values live in
one module that both the Stop validator and the handoff guard read.
"""
import datetime as dt
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HOOKS = pathlib.Path(os.environ.get("HOOKS_DIR", pathlib.Path(__file__).resolve().parents[1])).resolve()
SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(HOOKS))


def load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


import handoff_sidecar as hs  # noqa: E402  (the same module objects the hooks import)
import problems_md as pm  # noqa: E402
validator = load("problems_md_validator", HOOKS / "problems-md-validator.py")
guard = load("handoff_closure_audit_guard", HOOKS / "handoff-closure-audit-guard.py")

checks = 0
failures: list[str] = []


def check(name: str, condition: bool, detail: object = "") -> None:
    global checks
    checks += 1
    if not condition:
        failures.append(f"{name}: {detail}")


PROSE_AUDIT = (
    "## Closure Audit\n"
    "- Primary request status: COMPLETE\n"
    "- Acceptance/checklist verified: suite green, 12 checks\n"
    "- Related/scope-adjacent tasks checked: roster and guard\n"
    "- Unfinished related tasks: NONE\n"
    "- Why not continuing now: NONE\n"
)


def good() -> dict:
    return {
        "schema_version": 1,
        "session_id": "71b3da3f",
        "project": "demo",
        "status": "ACTIVE",
        "closure_audit": {
            "primary_status": "COMPLETE",
            "acceptance_verified": "suite green, 12 checks",
            "related_checked": "roster and guard",
            "unfinished": [],
            "why_not_continuing": "NONE",
        },
        "next_step": "open the PR",
    }


def mutate(path: tuple, value) -> dict:
    data = good()
    target = data
    for key in path[:-1]:
        target = target[key]
    if value is DELETE:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return data


DELETE = object()

# --- validate_sidecar: positive and every field's negative control --------------
check("valid sidecar has no errors", hs.validate_sidecar(good()) == [], hs.validate_sidecar(good()))
for primary in ("COMPLETE", "BLOCKED-ON-CREDS", "HANDOFF-NEAR-CONTEXT-LIMIT", "USER-REDIRECTED"):
    errs = hs.validate_sidecar(mutate(("closure_audit", "primary_status"), primary))
    check(f"primary {primary} accepted", errs == [], errs)
for status in ("ACTIVE", "CLOSED", "ABANDONED"):
    errs = hs.validate_sidecar(mutate(("status",), status))
    check(f"status {status} accepted", errs == [], errs)
withtracker = mutate(("closure_audit", "unfinished"), [{"item": "PROJ-CANCEL-01 retry", "tracker": "PROBLEMS.md"}])
check("unfinished item with tracker accepted", hs.validate_sidecar(withtracker) == [], hs.validate_sidecar(withtracker))

BAD = {
    "not an object": ["x"],
    "schema_version 2": mutate(("schema_version",), 2),
    "schema_version true": mutate(("schema_version",), True),
    "schema_version missing": mutate(("schema_version",), DELETE),
    "session_id empty": mutate(("session_id",), "  "),
    "session_id missing": mutate(("session_id",), DELETE),
    "session_id not str": mutate(("session_id",), 7),
    "project empty": mutate(("project",), ""),
    "status OPEN": mutate(("status",), "OPEN"),
    "status lowercase": mutate(("status",), "active"),
    "status missing": mutate(("status",), DELETE),
    "closure_audit missing": mutate(("closure_audit",), DELETE),
    "closure_audit not object": mutate(("closure_audit",), "COMPLETE"),
    "primary DONE": mutate(("closure_audit", "primary_status"), "DONE"),
    "primary bare BLOCKED-": mutate(("closure_audit", "primary_status"), "BLOCKED-"),
    "primary lowercase": mutate(("closure_audit", "primary_status"), "complete"),
    "primary with tail": mutate(("closure_audit", "primary_status"), "COMPLETE mostly"),
    "primary missing": mutate(("closure_audit", "primary_status"), DELETE),
    "acceptance empty": mutate(("closure_audit", "acceptance_verified"), ""),
    "related missing": mutate(("closure_audit", "related_checked"), DELETE),
    "why missing": mutate(("closure_audit", "why_not_continuing"), DELETE),
    "unfinished not list": mutate(("closure_audit", "unfinished"), "NONE"),
    "unfinished missing": mutate(("closure_audit", "unfinished"), DELETE),
    "unfinished item not object": mutate(("closure_audit", "unfinished"), ["fix later"]),
    "unfinished without tracker": mutate(("closure_audit", "unfinished"), [{"item": "retry"}]),
    "unfinished empty tracker": mutate(("closure_audit", "unfinished"), [{"item": "retry", "tracker": " "}]),
    "unfinished non-durable tracker": mutate(("closure_audit", "unfinished"), [{"item": "retry", "tracker": "my head"}]),
    "unfinished empty item": mutate(("closure_audit", "unfinished"), [{"item": "", "tracker": "PROBLEMS.md"}]),
    "evasive acceptance": mutate(("closure_audit", "acceptance_verified"), "probably done"),
    "evasive why": mutate(("closure_audit", "why_not_continuing"), "TBD"),
    "next_step empty": mutate(("next_step",), ""),
    "next_step missing": mutate(("next_step",), DELETE),
    "project is the flat handoffs folder": mutate(("project",), "handoffs"),
    "project is .claude": mutate(("project",), ".claude"),
}
for name, data in BAD.items():
    errs = hs.validate_sidecar(data)
    check(f"rejects {name}", bool(errs), errs)
# Each error names its field, so one bad field is not reported as another.
check("tracker error names tracker", any("tracker" in e for e in hs.validate_sidecar(BAD["unfinished without tracker"])))
check("one bad field gives one error", len(hs.validate_sidecar(BAD["status OPEN"])) == 1, hs.validate_sidecar(BAD["status OPEN"]))
check("second unfinished item checked",
      bool(hs.validate_sidecar(mutate(("closure_audit", "unfinished"),
                                      [{"item": "a", "tracker": "PROBLEMS.md"}, {"item": "b"}]))))

# --- consistency between sidecar and the prose Closure Audit ---------------------
check("same primary is consistent", hs.check_consistency(good(), "# H\n\n" + PROSE_AUDIT) == [])
check("prose without audit has nothing to contradict", hs.check_consistency(good(), "# H\n") == [])
check("different primary is inconsistent",
      bool(hs.check_consistency(mutate(("closure_audit", "primary_status"), "USER-REDIRECTED"), "# H\n\n" + PROSE_AUDIT)))
check("prose primary case-insensitive", hs.check_consistency(good(), "# H\n\n" + PROSE_AUDIT.replace("COMPLETE", "complete")) == [])
check("primary outside the audit section is ignored",
      hs.prose_primary_status("- Primary request status: USER-REDIRECTED\n\n" + PROSE_AUDIT) == "COMPLETE")

# --- paths ------------------------------------------------------------------------
check("sidecar path is sibling json", hs.sidecar_path(pathlib.Path("a/b/X.md")) == pathlib.Path("a/b/X.json"))
check("sidecar under handoffs recognised", guard.is_sidecar_path("C:/p/.claude/handoffs/demo/2026-10-28_10-00_ab.json"))
check("single-file sidecar recognised", guard.is_sidecar_path("C:/p/.claude/HANDOFF.json"))
check("other json is not a sidecar", not guard.is_sidecar_path("C:/p/.claude/settings.json"))
check("md is not a sidecar", not guard.is_sidecar_path("C:/p/.claude/handoffs/demo/x.md"))
check("INDEX sidecar ignored", not guard.is_sidecar_path("C:/p/.claude/handoffs/INDEX.json"))


# --- the hook end to end ---------------------------------------------------------
def run_guard(cwd: pathlib.Path, event: dict) -> str | None:
    home = cwd / "home"
    home.mkdir(exist_ok=True)
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "PYTHONIOENCODING": "utf-8"}
    env.pop("CLAUDE_ALLOW_INCOMPLETE_HANDOFF", None)
    result = subprocess.run([sys.executable, "-B", str(HOOKS / "handoff-closure-audit-guard.py")],
                            input=json.dumps(event), text=True, capture_output=True,
                            encoding="utf-8", env=env, cwd=cwd, check=False)
    for line in result.stdout.splitlines():
        if line.strip().startswith("{") and '"block"' in line:
            return json.loads(line).get("reason", "")
    return None


with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    folder = root / ".claude" / "handoffs" / "demo"
    folder.mkdir(parents=True)
    md = folder / "2026-10-28_10-00_71b3da3f.md"
    js = hs.sidecar_path(md)
    write_md = {"tool_name": "Write", "tool_input": {"file_path": str(md), "content": "# H\n\n" + PROSE_AUDIT}}

    check("prose-only handoff allowed as before", run_guard(root, write_md) is None)
    bad_prose = {"tool_name": "Write", "tool_input": {"file_path": str(md), "content": "# H\n"}}
    check("prose handoff without audit still blocked", run_guard(root, bad_prose) is not None)

    js.write_text(json.dumps(good()), encoding="utf-8")
    check("handoff with valid sidecar allowed", run_guard(root, write_md) is None)

    js.write_text(json.dumps(mutate(("closure_audit", "unfinished"), [{"item": "retry"}])), encoding="utf-8")
    reason = run_guard(root, write_md)
    check("handoff with invalid sidecar blocked", reason is not None and "tracker" in reason, reason)

    js.write_text("{not json", encoding="utf-8")
    check("handoff with unparsable sidecar blocked", run_guard(root, write_md) is not None)

    js.write_text(json.dumps(mutate(("closure_audit", "primary_status"), "USER-REDIRECTED")), encoding="utf-8")
    check("handoff contradicting sidecar blocked", run_guard(root, write_md) is not None)
    js.unlink()

    md.write_text("# H\n\n" + PROSE_AUDIT, encoding="utf-8")
    write_js = {"tool_name": "Write", "tool_input": {"file_path": str(js), "content": json.dumps(good())}}
    check("valid sidecar write allowed", run_guard(root, write_js) is None)
    write_js["tool_input"]["content"] = json.dumps(mutate(("status",), "OPEN"))
    check("invalid sidecar write blocked", run_guard(root, write_js) is not None)
    write_js["tool_input"]["content"] = "{not json"
    check("unparsable sidecar write blocked", run_guard(root, write_js) is not None)
    write_js["tool_input"]["content"] = json.dumps(mutate(("closure_audit", "primary_status"), "BLOCKED-ON-CREDS"))
    check("sidecar contradicting its handoff blocked", run_guard(root, write_js) is not None)
    other = {"tool_name": "Write", "tool_input": {"file_path": str(root / ".claude" / "settings.json"), "content": "{}"}}
    check("unrelated json untouched", run_guard(root, other) is None)

    # --- the helper writes the sidecar so agents do not hand-write JSON -------------
    def helper(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", str(HOOKS / "handoff_sidecar.py"), *args],
                              text=True, capture_output=True, encoding="utf-8", check=False)

    common = ["--primary", "COMPLETE", "--acceptance", "suite green, 12 checks",
              "--related", "roster and guard", "--why", "NONE", "--next", "open the PR"]
    result = helper("write", str(md), *common, "--unfinished", "retry upload", "PROBLEMS.md")
    written = json.loads(js.read_text(encoding="utf-8")) if js.exists() else {}
    check("helper writes a valid sidecar", result.returncode == 0 and hs.validate_sidecar(written) == [],
          result.stdout + result.stderr)
    check("helper derives session id from file name", written.get("session_id") == "71b3da3f", written)
    check("helper derives project from folder", written.get("project") == "demo", written)
    check("helper keeps the unfinished pair",
          written.get("closure_audit", {}).get("unfinished") == [{"item": "retry upload", "tracker": "PROBLEMS.md"}], written)
    check("helper prints the sidecar path", result.stdout.strip() == str(js), result.stdout)
    check("in-process write returns 0", hs.main(["write", str(md), *common, "--unfinished", "повтор выгрузки", "PROBLEMS.md"]) == 0)
    text = js.read_text(encoding="utf-8")
    check("sidecar is readable UTF-8 with 2-space indent",
          text == json.dumps(json.loads(text), ensure_ascii=False, indent=2) + "\n" and "повтор" in text, text[:120])
    result = helper("write", str(folder / "notes.txt"), *common)
    check("helper refuses a non-.md handoff", result.returncode == 1 and "must end in .md" in result.stderr,
          result.stdout + result.stderr)
    check("helper check passes", helper("check", str(md)).returncode == 0)
    check("in-process check returns 0", hs.main(["check", str(js)]) == 0)
    saved = js.read_text(encoding="utf-8")
    js.write_text(json.dumps(mutate(("closure_audit", "primary_status"), "USER-REDIRECTED")), encoding="utf-8")
    result = helper("check", str(md))
    check("helper check catches a contradiction with the handoff",
          result.returncode == 1 and "sidecar INVALID:\n  - sidecar primary_status" in result.stderr,
          result.stdout + result.stderr)
    js.write_text(saved, encoding="utf-8")

    before = js.read_text(encoding="utf-8")
    result = helper("write", str(md), *common, "--unfinished", "retry upload", "my head")
    check("helper refuses an untracked unfinished item",
          result.returncode == 1 and "sidecar NOT written:\n  - closure_audit.unfinished[0].tracker" in result.stderr,
          result.stdout + result.stderr)
    check("refused write leaves the old sidecar", js.read_text(encoding="utf-8") == before)
    result = helper("write", str(md), *[a if a != "COMPLETE" else "USER-REDIRECTED" for a in common])
    check("helper refuses a sidecar contradicting the handoff", result.returncode == 1, result.stdout + result.stderr)
    result = helper("write", str(md), *common, "--session-id", "deadbeef")
    check("helper refuses to overwrite another session's sidecar", result.returncode == 1, result.stdout + result.stderr)
    result = helper("write", str(md), *common, "--status", "CLOSED")
    check("same session may update its sidecar", result.returncode == 0 and
          json.loads(js.read_text(encoding="utf-8"))["status"] == "CLOSED", result.stdout + result.stderr)
    js.write_text("{}", encoding="utf-8")
    check("helper check fails on an invalid sidecar", helper("check", str(js)).returncode == 1)
    check("read_valid_sidecar: invalid is None", hs.read_valid_sidecar(md) is None)
    check("read_valid_sidecar: missing is None", hs.read_valid_sidecar(folder / "none.md") is None)
    js.write_text(json.dumps(good()), encoding="utf-8")
    check("read_valid_sidecar: valid is the data", hs.read_valid_sidecar(md) == good())
    check("load_sidecar: valid has no errors", hs.load_sidecar(md) == (good(), []))
    js.write_text("{", encoding="utf-8")
    loaded = hs.load_sidecar(md)
    check("load_sidecar: broken JSON is (None, reason)", loaded[0] is None and len(loaded[1]) == 1, loaded)
    check("load_sidecar: missing is (None, [])", hs.load_sidecar(folder / "none.md") == (None, []))
    js.write_text("\ufeff" + json.dumps(good()), encoding="utf-8")
    check("sidecar with a BOM is read", hs.read_valid_sidecar(md) == good())
    js.write_text("{", encoding="utf-8")
    result = helper("write", str(md), *common)
    check("helper repairs a broken sidecar", result.returncode == 0 and hs.read_valid_sidecar(md) is not None,
          result.stdout + result.stderr)
    result = helper("write", str(folder / "absent_71b3da3f.md"), *common)
    check("helper refuses a sidecar without its handoff", result.returncode == 1 and
          not (folder / "absent_71b3da3f.json").exists(), result.stdout + result.stderr)
    flat = root / ".claude" / "handoffs" / "2026-10-28_10-00_71b3da3f.md"
    flat.write_text("# H\n\n" + PROSE_AUDIT, encoding="utf-8")
    result = helper("write", str(flat), *common)
    check("helper needs --project for a flat handoff", result.returncode == 1, result.stdout + result.stderr)
    single = root / ".claude" / "HANDOFF.md"
    single.write_text("# H\n\n" + PROSE_AUDIT, encoding="utf-8")
    result = helper("write", str(single), *common, "--project", "demo")
    check("helper needs --session-id when the name has none", result.returncode == 1, result.stdout + result.stderr)
    result = helper("write", str(single), *common, "--project", "demo", "--session-id", "71b3da3f")
    check("single-file handoff sidecar written with explicit ids", result.returncode == 0, result.stdout + result.stderr)
    check("helper check on a missing sidecar is not checked",
          helper("check", str(folder / "none.md")).returncode == 2)

    # --- roster prefers the sidecar --------------------------------------------------
    js.write_text(json.dumps({**good(), "project": "from-json", "session_id": "71b3da3f-full-id"}), encoding="utf-8")
    if (SCRIPTS / "agent_roster.py").exists():
        roster = load("agent_roster", SCRIPTS / "agent_roster.py")
        sidecar = roster.read_valid_sidecar(md)
        check("roster reads a valid sidecar", sidecar and sidecar["project"] == "from-json", sidecar)
        agent = {"cli": "71b3da3f-full-id", "sessionId": "local_x", "cwd": "", "handoffs": [md]}
        check("roster takes the project from the sidecar", roster.project_of(agent, {}) == "from-json")
        renamed = folder / "2026-10-28_11-00_zzzzzzzz.md"
        renamed.write_text("# H\n", encoding="utf-8")
        hs.sidecar_path(renamed).write_text(json.dumps({**good(), "session_id": "71b3da3f-full-id"}), encoding="utf-8")
        files = roster.index_handoffs([root / ".claude" / "handoffs"], root / "out", dt.datetime(2000, 1, 1))
        check("roster matches a handoff by sidecar session id", renamed in roster.match_handoffs(agent, files))
        stranger = {"cli": "ffffffff-other", "sessionId": "local_y", "cwd": "", "handoffs": []}
        check("roster does not hand the sidecar to another agent", renamed not in roster.match_handoffs(stranger, files))
        js.write_text(json.dumps(mutate(("status",), "OPEN")), encoding="utf-8")
        check("roster ignores an invalid sidecar", roster.read_valid_sidecar(md) is None)
        check("roster falls back to the folder name", roster.project_of(agent, {}) == "demo")
        block = "\n".join(roster.agent_block({**agent, "n": 1, "title": "t", "lastActivity": None,
                                              "handoff_time": None, "transcript": "", "tr": {},
                                              "sidecar": good()}))
        check("takeover text shows the sidecar fields", "COMPLETE" in block and "open the PR" in block, block)

# --- PROBLEMS.md: one parser, one set of status values ---------------------------
TEXT = (
    "# Problems\n\n## Open\n\n"
    "## 2026-10-28 09:30 - PROJ-CANCEL-01 retry\n\n**Status**: arch-decision\n\nbody\n\n"
    "## 2026-10-28 10:00 - PROJ-CANCEL-02 done\n\n**Status**: RESOLVED in abc\n\n"
    "## 2026-10-27 - old plain open\n\nStatus: OPEN\n\n"
    "## 2026-10-26 - no status here\n\ntext\n\n"
    "## 2026-10-25 - blocked\n\n**Status**: BLOCKED-ON-CREDS\n"
)
entries = pm.parse_entries(TEXT)
check("dated headings only", [e["date"] for e in entries] == ["2026-10-28", "2026-10-28", "2026-10-27", "2026-10-26", "2026-10-25"], entries)
check("status token parsed", entries[0]["status"] == "arch-decision", entries[0])
check("status line kept", entries[1]["status_line"].startswith("RESOLVED in abc"), entries[1])
check("plain Status: parsed", entries[2]["status"] == "OPEN", entries[2])
check("missing status is None", entries[3]["status"] is None and entries[3]["status_line"] == "", entries[3])
check("line numbers 1-based", TEXT.split("\n")[entries[0]["line"] - 1].startswith("## 2026-10-28 09:30"), entries[0])
check("body stops at the next heading", "PROJ-CANCEL-02" not in entries[0]["body"], entries[0]["body"])
check("deferral reasons are the five", pm.DEFERRAL_REASONS == {"missing-data", "missing-dep", "arch-decision", "scope-explosion", "inaccessible-repo"})

VERDICTS = {
    "arch-decision": True, "missing_data": True, "RESOLVED": True, "workaround": True, "NOT_A_BUG": True,
    "CLOSED": True, "BLOCKED-ON-CREDS": True, "blocked_x": True, "OPEN": False, "open": False,
    "FIXED": False, "later": False, None: False,
}
for status, ok in VERDICTS.items():
    verdict, reason = pm.validate_entry({"status": status, "line": 3, "heading": "2026-10-28 x"})
    check(f"validate_entry {status!r}", verdict is ok and (reason == "") is ok, (verdict, reason))
check("missing status reason names the field", "Status" in pm.validate_entry({"status": None, "line": 3, "heading": "h"})[1])
long_reason = pm.validate_entry({"status": "S" * 50, "line": 3, "heading": "H" * 80})[1]
check("reason caps heading at 60 and status at 40", "'" + "H" * 60 + "'" in long_reason and "'" + "S" * 40 + "'" in long_reason, long_reason)
check("OPEN reason lists the exceptions", "arch-decision" in pm.validate_entry({"status": "OPEN", "line": 3, "heading": "h"})[1])

for line, closed in {"RESOLVED in abc": True, "CLOSED": True, "fixed by 1a2b": True, "NOT A BUG": True,
                     "WONTFIX": True, "ОТОЗВАНО": True, "arch-decision": False, "WORKAROUND": False, "": False}.items():
    check(f"is_closed {line!r}", pm.is_closed(line) is closed)

check("validator uses the shared parser", validator.parse_problems is pm.parse_entries)
check("validator uses the shared verdict", validator.validate_entry is pm.validate_entry)
today = pm.parse_entries(TEXT)[0]["date"]
opened = guard.tickets_opened_today(TEXT, today)
check("guard lists today's open ticket only", [t[0] for t in opened] == ["PROJ-CANCEL-01"], opened)
check("guard reports the status token", opened and opened[0][1] == "arch-decision", opened)
longest = guard.tickets_opened_today("## 2026-10-28 - PROJ-X-1 " + "t" * 120 + "\n\n**Status**: " + "s" * 60 + "\n", "2026-10-28")[0]
check("guard caps status at 40 and title at 90", len(longest[1]) == 40 and len(longest[2]) == 90, longest)
check("guard reports NO STATUS", guard.tickets_opened_today("## 2026-10-28 - PROJ-X-1 a\n\ntext\n", "2026-10-28")[0][1] == "NO", None)

if failures:
    print(f"{len(failures)} of {checks} checks FAILED:")
    for failure in failures:
        print("  - " + failure)
    raise SystemExit(1)
print(f"all {checks} checks correct")
