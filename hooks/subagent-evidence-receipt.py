#!/usr/bin/env python3
"""Codex SubagentStop: require one structured decision-source receipt.

This is deliberately a narrow receipt check, not a natural-language fact
checker. Codex exposes the subagent's final message at SubagentStop, so the
hook can require an explicit basis and evidence anchor before accepting a
conclusion. It cannot establish that a cited web page or command is truthful;
the parent and task-specific validators remain responsible for that proof.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from skill_contract_state import load_agent


BASIS_RE = re.compile(
    r"(?mi)^Decision basis:\s*(OBSERVED|PRIMARY_DOC|USER_CONSTRAINT|INCONCLUSIVE|NO_DECISION)\s*$"
)
SKILL_DISPOSITION_RE = re.compile(
    r"(?mi)^Skill disposition:[ \t]*"
    r"(USED|NO_MATCH|GAP_RESOLVED|PAUSED_BY_SKILL)(?:[ \t]+([^\r\n]+))?[ \t]*$"
)
EVIDENCE_RE = re.compile(r"(?mi)^Evidence:\s*(\S.+?)\s*$")
TASK_ROUTE_RE = re.compile(r"(?mi)^Task route:\s*([0-9a-f]{64})\s*$")
CONTINUATION_RE = re.compile(
    r"(?mi)^Continuation:\s*RESUMED\s+task-sha256=([0-9a-f]{64})\s+::\s+(\S.*?)\s*$"
)
CONTINUATION_EVIDENCE_RE = re.compile(r"(?mi)^Continuation evidence:\s*(\S.*?)\s*$")
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|(?:^|\s)[.~]?/)[^\s]+")
SKILL_NAME = r"[a-z0-9][a-z0-9:_-]*"
GAP_DETAIL_RE = re.compile(
    rf"^(?P<requested>{SKILL_NAME})\s+->\s+(?P<resolved>{SKILL_NAME})"
    r"\s*;\s*checklist=(?P<path>\S.+)$"
)
PAUSE_DETAIL_RE = re.compile(
    rf"^(?P<skill>{SKILL_NAME})\s+::\s+(?P<path>.+?SKILL\.md)"
    r"#L(?P<line>[1-9][0-9]*)\s+::\s+(?P<instruction>\S.+)$"
)
COMMAND_RE = re.compile(
    r"\b(?:python(?:3)?|git|rg|pytest|curl|powershell|Get-[A-Za-z]+|"
    r"Test-[A-Za-z]+|Invoke-[A-Za-z]+|docker|systemctl|npm|uv|cargo|go|make)\b",
    re.IGNORECASE,
)
USER_CONSTRAINT_RE = re.compile(
    r"\buser\s+(?:request|message|constraint|instruction)\s*:", re.IGNORECASE
)
STALE_LEAD_RE = re.compile(
    r"\b(?:memory|remember|prior|previous|earlier|assistant|chat)\b", re.IGNORECASE
)


CHECKLIST_BOXES = (
    "Scope matches the original task without narrowing or expansion",
    "Complete SKILL.md read; task-relevant references identified and read",
    "Scripts, dependencies, hooks, tools, permissions, and side effects inspected",
    "Publisher, immutable version/SHA, activity, and license verified",
    "Prompt injection, policy conflicts, duplication, and hidden authority rejected",
    "Isolated validation/behavior check passed with evidence",
)

RESEARCH_BUILD_BOXES = (
    "Real task evidence and current primary sources were synthesized",
    "Accepted and rejected recommendations map to exact skill instructions",
    "Progressive disclosure and bundled scripts, if any, match observed recurring needs",
    "Structural validation and executable assets passed in isolation",
    "With-skill behavior beat the no-skill or prior-version baseline",
    "Trigger positives, near-miss negatives, and held-out task evals passed",
    "Independent fresh-context review passed",
    "Owner, version, source freshness, update triggers, and rollback are recorded",
    "Live discovery/registration passed in every intended harness",
)

PLACEHOLDER_RE = re.compile(r"(?i)^(?:\.\.\.|tbd|todo|n/?a|none|unknown)$")
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
FORBIDDEN_CONTINUATION_RE = re.compile(
    r"(?i)\b(?:abandon|cancel|defer|stop|wait|report[ -]?only|"
    r"брос\w*|отмен\w*|отлож\w*|останов\w*|ждат\w*|только\s+отч[её]т)\b"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _field(text: str, label: str) -> str | None:
    match = re.search(rf"(?mi)^- {re.escape(label)}:\s*(\S.*?)\s*$", text)
    if match is None:
        return None
    value = match.group(1).strip()
    return None if PLACEHOLDER_RE.fullmatch(value) else value


def _has_heading(text: str, heading: str) -> bool:
    return bool(re.search(rf"(?mi)^##+\s+{re.escape(heading)}\s*$", text))


def _section_nonempty(text: str, heading: str) -> bool:
    match = re.search(
        rf"(?msi)^##+\s+{re.escape(heading)}\s*$\s*(.+?)(?=^##+\s|\Z)", text
    )
    return bool(match and match.group(1).strip())


def _record_text(raw_path: str, base_dir: Path, label: str) -> tuple[Path | None, str | None, str | None]:
    path, problem = _local_file(raw_path, base_dir)
    if problem:
        return None, None, f"{label}: {problem}"
    assert path is not None
    content, problem = _read_local(path)
    if problem:
        return None, None, f"{label}: {problem}"
    return path, content, None


def _json_record(raw_path: str, base_dir: Path, label: str) -> tuple[Path | None, dict | None, str | None]:
    path, content, problem = _record_text(raw_path, base_dir, label)
    if problem:
        return None, None, problem
    assert path is not None and content is not None
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None, None, f"{label} must be valid JSON"
    if not isinstance(payload, dict):
        return None, None, f"{label} must be a JSON object"
    return path, payload, None


def _metric(payload: dict, name: str) -> tuple[int, int] | None:
    value = payload.get(name)
    if not isinstance(value, dict):
        return None
    passed, total = value.get("passed"), value.get("total")
    if not isinstance(passed, int) or isinstance(passed, bool):
        return None
    if not isinstance(total, int) or isinstance(total, bool) or total < 1:
        return None
    if passed < 0 or passed > total:
        return None
    return passed, total


def _trace_map(payload: dict, record_path: Path, label: str) -> tuple[dict[str, Path] | None, str | None]:
    traces = payload.get("traces")
    if not isinstance(traces, list) or not traces:
        return None, f"{label} needs non-empty traces"
    result: dict[str, Path] = {}
    for trace in traces:
        if not isinstance(trace, dict):
            return None, f"{label} trace entries must be objects"
        trace_id, raw_path, digest = trace.get("id"), trace.get("path"), trace.get("sha256")
        if not all(isinstance(value, str) and value.strip() for value in (trace_id, raw_path, digest)):
            return None, f"{label} trace needs id, path, and sha256"
        if trace_id in result:
            return None, f"{label} trace ids must be unique"
        trace_path, problem = _local_file(raw_path, record_path.parent)
        if problem:
            return None, f"{label} trace {trace_id}: {problem}"
        assert trace_path is not None
        try:
            observed_digest = hashlib.sha256(trace_path.read_bytes()).hexdigest()
        except OSError:
            return None, f"{label} trace {trace_id} is not readable"
        if not SHA256_RE.fullmatch(digest) or observed_digest != digest:
            return None, f"{label} trace {trace_id} sha256 does not match"
        result[trace_id] = trace_path
    return result, None


def _observation_passed(observation: dict) -> bool | None:
    operator = observation.get("operator")
    actual, expected = observation.get("actual"), observation.get("expected")
    if operator == "eq":
        return actual == expected
    if operator == "ne":
        return actual != expected
    if operator in {"contains", "not_contains", "regex"}:
        if not isinstance(actual, str) or not isinstance(expected, str):
            return None
        if operator == "contains":
            return expected in actual
        if operator == "not_contains":
            return expected not in actual
        try:
            return re.search(expected, actual) is not None
        except re.error:
            return None
    return None


def _trace_cases(
    traces: dict[str, Path],
    label: str,
    expected_kind: str,
    allowed_cohorts: set[str],
    binding: dict[str, object] | None = None,
) -> tuple[dict[str, dict] | None, str | None]:
    """Parse machine-shaped traces and recompute every case result."""
    cases: dict[str, dict] = {}
    for trace_id, trace_path in traces.items():
        try:
            payload = json.loads(trace_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None, f"{label} trace {trace_id} must be valid UTF-8 JSON"
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            return None, f"{label} trace {trace_id} needs schema_version 1"
        if payload.get("kind") != expected_kind:
            return None, f"{label} trace {trace_id} kind must be {expected_kind}"
        if binding and any(payload.get(key) != value for key, value in binding.items()):
            return None, f"{label} trace {trace_id} does not match its record binding"
        producer = payload.get("producer")
        if not isinstance(producer, dict):
            return None, f"{label} trace {trace_id} needs a producer receipt"
        command, exit_code = producer.get("command"), producer.get("exit_code")
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(part, str) or not part.strip() for part in command)
            or not isinstance(exit_code, int)
            or isinstance(exit_code, bool)
        ):
            return None, f"{label} trace {trace_id} needs command[] and integer exit_code"
        if expected_kind != "external-boundary" and exit_code != 0:
            return None, f"{label} trace {trace_id} producer did not exit successfully"
        raw_cases = payload.get("cases")
        if not isinstance(raw_cases, list) or not raw_cases:
            return None, f"{label} trace {trace_id} needs non-empty cases"
        for case in raw_cases:
            if not isinstance(case, dict):
                return None, f"{label} trace {trace_id} cases must be objects"
            case_id, cohort = case.get("id"), case.get("cohort")
            if not isinstance(case_id, str) or not case_id.strip() or case_id in cases:
                return None, f"{label} case ids must be unique and non-empty"
            if cohort not in allowed_cohorts:
                return None, f"{label} case {case_id} has an invalid cohort"
            observations = case.get("observations")
            if not isinstance(observations, list) or not observations:
                return None, f"{label} case {case_id} needs observations"
            observation_ids: set[str] = set()
            passed = True
            for observation in observations:
                if not isinstance(observation, dict):
                    return None, f"{label} case {case_id} observations must be objects"
                observation_id = observation.get("id")
                if (
                    not isinstance(observation_id, str)
                    or not observation_id.strip()
                    or observation_id in observation_ids
                ):
                    return None, f"{label} case {case_id} needs unique observation ids"
                observation_ids.add(observation_id)
                result = _observation_passed(observation)
                if result is None:
                    return None, f"{label} case {case_id} has an invalid observation"
                passed = passed and result
            cases[case_id] = {
                "cohort": cohort,
                "passed": passed,
                "trace_id": trace_id,
                "path": trace_path,
                "producer_exit_code": exit_code,
            }
    return cases, None


def _assertions_problem(payload: dict, cases: dict[str, dict], field: str, label: str) -> str | None:
    assertions = payload.get(field)
    if not isinstance(assertions, list) or len(assertions) < 2:
        return f"{label} needs at least two {field}"
    seen: set[str] = set()
    for assertion in assertions:
        if not isinstance(assertion, dict):
            return f"{label} {field} entries must be objects"
        assertion_id = assertion.get("id")
        refs = assertion.get("case_ids")
        if not isinstance(assertion_id, str) or not assertion_id.strip() or assertion_id in seen:
            return f"{label} {field} needs unique non-empty ids"
        seen.add(assertion_id)
        if "passed" in assertion:
            return f"{label} {field} {assertion_id} must not self-assert passed"
        if not isinstance(refs, list) or not refs or any(ref not in cases for ref in refs):
            return f"{label} {field} {assertion_id} needs valid case_ids"
        if any(not cases[ref]["passed"] for ref in refs):
            return f"{label} {field} {assertion_id} references a failing case"
    return None


def eval_record_problem(
    raw_path: str, resolved: str, skill_version: str, base_dir: Path
) -> str | None:
    path, payload, problem = _json_record(raw_path, base_dir, "Eval record")
    if problem:
        return problem
    assert path is not None and payload is not None
    if payload.get("schema_version") != 2 or payload.get("skill_name") != resolved:
        return "Eval record schema_version 2/skill_name does not match the resolved skill"
    if payload.get("skill_version") != skill_version:
        return "Eval record skill_version does not match SKILL.md"
    metrics: dict[str, tuple[int, int]] = {}
    for name in ("baseline", "candidate", "trigger_positives", "near_miss_negatives", "held_out"):
        value = _metric(payload, name)
        if value is None:
            return f"Eval record needs a valid {name} passed/total metric"
        metrics[name] = value
    base_passed, base_total = metrics["baseline"]
    candidate_passed, candidate_total = metrics["candidate"]
    if base_total < 2 or candidate_total < 2:
        return "Eval baseline and candidate each need at least two objective cases"
    if payload["baseline"].get("kind") not in {"no_skill", "prior_version"}:
        return "Eval baseline kind must be no_skill or prior_version"
    if candidate_passed != candidate_total:
        return "Eval candidate must pass every objective case"
    if candidate_passed * base_total <= base_passed * candidate_total:
        return "Eval candidate must measurably beat the baseline"
    for name in ("trigger_positives", "near_miss_negatives", "held_out"):
        passed, total = metrics[name]
        if total < 2 or passed != total:
            return f"Eval {name} needs at least two cases and a full pass"
    traces, problem = _trace_map(payload, path, "Eval record")
    if problem:
        return problem
    assert traces is not None
    cases, problem = _trace_cases(
        traces,
        "Eval record",
        "skill-eval",
        {"baseline", "candidate", "trigger_positives", "near_miss_negatives", "held_out"},
        {"skill_name": resolved, "skill_version": skill_version},
    )
    if problem:
        return problem
    assert cases is not None
    observed_metrics: dict[str, tuple[int, int]] = {}
    for cohort in ("baseline", "candidate", "trigger_positives", "near_miss_negatives", "held_out"):
        cohort_cases = [case for case in cases.values() if case["cohort"] == cohort]
        observed_metrics[cohort] = (sum(1 for case in cohort_cases if case["passed"]), len(cohort_cases))
    if metrics != observed_metrics:
        return "Eval record metrics do not match recomputed case-level observations"
    problem = _assertions_problem(payload, cases, "assertions", "Eval record")
    if problem:
        return problem
    if payload.get("result") != "PASS":
        return "Eval record result must be PASS"
    return None


def review_record_problem(
    raw_path: str, resolved: str, skill_version: str, base_dir: Path
) -> str | None:
    path, payload, problem = _json_record(raw_path, base_dir, "Independent review")
    if problem:
        return problem
    assert path is not None and payload is not None
    if payload.get("schema_version") != 2 or payload.get("context") != "fresh":
        return "Independent review needs schema_version 2 and context fresh"
    if payload.get("skill_name") != resolved or payload.get("skill_version") != skill_version:
        return "Independent review skill_name/skill_version does not match SKILL.md"
    author, reviewer = payload.get("author_id"), payload.get("reviewer_id")
    if not isinstance(author, str) or not author.strip() or not isinstance(reviewer, str) or not reviewer.strip():
        return "Independent review needs author_id and reviewer_id"
    if author.strip().casefold() == reviewer.strip().casefold():
        return "Independent review reviewer_id must differ from author_id"
    traces, problem = _trace_map(payload, path, "Independent review")
    if problem:
        return problem
    assert traces is not None
    cases, problem = _trace_cases(
        traces,
        "Independent review",
        "skill-review",
        {"acceptance"},
        {"skill_name": resolved, "skill_version": skill_version},
    )
    if problem:
        return problem
    assert cases is not None
    if any(not case["passed"] for case in cases.values()):
        return "Independent review contains a failing acceptance case"
    problem = _assertions_problem(payload, cases, "acceptance_results", "Independent review")
    if problem:
        return problem
    if payload.get("result") != "PASS":
        return "Independent review result must be PASS"
    return None


def research_record_problem(
    raw_path: str, skill_path: Path, skill_text: str, base_dir: Path
) -> str | None:
    path, payload, problem = _json_record(raw_path, base_dir, "Research record")
    if problem:
        return problem
    assert path is not None and payload is not None
    if payload.get("schema_version") != 2:
        return "Research record needs schema_version 2"
    sources = payload.get("sources")
    if not isinstance(sources, list) or len(sources) < 2:
        return "Research record needs at least two per-source primary records"
    source_ids: set[str] = set()
    source_urls: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            return "Research record sources must be objects"
        source_id, url = source.get("id"), source.get("url")
        if not isinstance(source_id, str) or not source_id.strip() or source_id in source_ids:
            return "Research record source ids must be unique and non-empty"
        if not isinstance(url, str) or not URL_RE.fullmatch(url) or url in source_urls:
            return "Research record source URLs must be unique HTTP(S) URLs"
        if source.get("authority") != "primary":
            return f"Research record source {source_id} must be individually marked primary"
        for field in ("title", "publisher", "language"):
            value = source.get(field)
            if not isinstance(value, str) or not value.strip() or PLACEHOLDER_RE.fullmatch(value.strip()):
                return f"Research record source {source_id} needs {field}"
        published = source.get("published_or_updated")
        if not isinstance(published, str) or not (
            DATE_RE.fullmatch(published) or published == "not-stated"
        ):
            return (
                f"Research record source {source_id} needs YYYY-MM-DD or "
                "not-stated published_or_updated"
            )
        accessed = source.get("accessed")
        if not isinstance(accessed, str) or not DATE_RE.fullmatch(accessed):
            return f"Research record source {source_id} needs YYYY-MM-DD accessed"
        source_ids.add(source_id)
        source_urls.add(url)

    local_evidence = payload.get("local_evidence")
    if not isinstance(local_evidence, list) or not local_evidence:
        return "Research record needs non-empty local_evidence"
    evidence_ids: set[str] = set()
    for item in local_evidence:
        if not isinstance(item, dict):
            return "Research record local_evidence entries must be objects"
        item_id, raw_evidence, digest = item.get("id"), item.get("path"), item.get("sha256")
        if not isinstance(item_id, str) or not item_id.strip() or item_id in evidence_ids:
            return "Research record local_evidence ids must be unique"
        evidence_path, evidence_problem = _local_file(str(raw_evidence or ""), path.parent)
        if evidence_problem:
            return f"Research record local evidence {item_id}: {evidence_problem}"
        assert evidence_path is not None
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            return f"Research record local evidence {item_id} needs sha256"
        if hashlib.sha256(evidence_path.read_bytes()).hexdigest() != digest:
            return f"Research record local evidence {item_id} sha256 does not match"
        observation = item.get("observation")
        if not isinstance(observation, str) or not observation.strip():
            return f"Research record local evidence {item_id} needs observation"
        evidence_ids.add(item_id)

    recommendations = payload.get("recommendations")
    if not isinstance(recommendations, list) or len(recommendations) < 2:
        return "Research record needs accepted and rejected recommendations"
    recommendation_ids: set[str] = set()
    decisions: set[str] = set()
    used_sources: set[str] = set()
    skill_lines = skill_text.splitlines()
    for recommendation in recommendations:
        if not isinstance(recommendation, dict):
            return "Research record recommendations must be objects"
        rec_id, decision = recommendation.get("id"), recommendation.get("decision")
        if not isinstance(rec_id, str) or not rec_id.strip() or rec_id in recommendation_ids:
            return "Research record recommendation ids must be unique"
        if decision not in {"accepted", "rejected"}:
            return f"Research record recommendation {rec_id} has an invalid decision"
        refs, local_refs = recommendation.get("source_ids"), recommendation.get("local_evidence_ids")
        if not isinstance(refs, list) or not refs or any(ref not in source_ids for ref in refs):
            return f"Research record recommendation {rec_id} needs valid source_ids"
        if not isinstance(local_refs, list) or not local_refs or any(ref not in evidence_ids for ref in local_refs):
            return f"Research record recommendation {rec_id} needs valid local_evidence_ids"
        rationale = recommendation.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            return f"Research record recommendation {rec_id} needs rationale"
        if decision == "accepted":
            line, exact = recommendation.get("skill_line"), recommendation.get("exact_instruction")
            if not isinstance(line, int) or isinstance(line, bool) or line < 1 or line > len(skill_lines):
                return f"Research record accepted recommendation {rec_id} needs skill_line"
            if not isinstance(exact, str) or skill_lines[line - 1].strip() != exact.strip():
                return f"Research record accepted recommendation {rec_id} does not map to the exact SKILL.md line"
        recommendation_ids.add(rec_id)
        decisions.add(decision)
        used_sources.update(refs)
    if decisions != {"accepted", "rejected"}:
        return "Research record needs both accepted and rejected recommendations"
    if used_sources != source_ids:
        return "Research record must map every primary source to a recommendation"
    return None


def research_build_problem(text: str, resolved: str, base_dir: Path) -> str | None:
    values: dict[str, str] = {}
    for label in (
        "Skill path",
        "Research record",
        "Eval record",
        "Maintenance record",
        "Independent review",
    ):
        value = _field(text, label)
        if value is None:
            return f"BUILD_RESEARCHED needs a non-placeholder {label}"
        values[label] = value

    skill_path, skill_text, problem = _record_text(values["Skill path"], base_dir, "Skill path")
    if problem:
        return problem
    assert skill_path is not None and skill_text is not None
    if skill_path.name != "SKILL.md":
        return "BUILD_RESEARCHED Skill path must name SKILL.md"
    name_match = re.search(r"(?mi)^name:\s*([a-z0-9][a-z0-9-]*)\s*$", skill_text)
    description_match = re.search(r"(?mi)^description:\s*(\S.*?)\s*$", skill_text)
    version_match = re.search(r'(?mi)^\s*version:\s*["\']?([^"\'\r\n]+)["\']?\s*$', skill_text)
    if name_match is None or name_match.group(1) != resolved:
        return "BUILD_RESEARCHED SKILL.md name must exactly match the resolved skill"
    if description_match is None or PLACEHOLDER_RE.fullmatch(description_match.group(1).strip()):
        return "BUILD_RESEARCHED SKILL.md needs a non-placeholder description"
    if version_match is None or not version_match.group(1).strip():
        return "BUILD_RESEARCHED SKILL.md needs a metadata version"
    skill_version = version_match.group(1).strip()
    for heading in ("Gotchas", "Troubleshooting"):
        if not _has_heading(skill_text, heading):
            return f"BUILD_RESEARCHED SKILL.md needs a {heading} section"

    problem = research_record_problem(values["Research record"], skill_path, skill_text, base_dir)
    if problem:
        return problem

    problem = eval_record_problem(values["Eval record"], resolved, skill_version, base_dir)
    if problem:
        return problem

    _, maintenance_text, problem = _record_text(
        values["Maintenance record"], base_dir, "Maintenance record"
    )
    if problem:
        return problem
    assert maintenance_text is not None
    for field in (
        "Owner",
        "Version",
        "Last reviewed",
        "Source freshness",
        "Update triggers",
        "Rollback",
    ):
        if _field(maintenance_text, field) is None:
            return f"Maintenance record needs {field}"
    if not DATE_RE.fullmatch(_field(maintenance_text, "Last reviewed") or ""):
        return "Maintenance record Last reviewed must use YYYY-MM-DD"
    if _field(maintenance_text, "Version") != skill_version:
        return "Maintenance record Version does not match SKILL.md"

    problem = review_record_problem(
        values["Independent review"], resolved, skill_version, base_dir
    )
    if problem:
        return problem

    for label in RESEARCH_BUILD_BOXES:
        if not re.search(rf"(?mi)^- \[[xX]\] {re.escape(label)}\s*$", text):
            return f"BUILD_RESEARCHED box is not checked: {label}"
    return None


def _local_file(raw: str, base_dir: Path) -> tuple[Path | None, str | None]:
    value = raw.strip().strip("`'\"")
    if URL_RE.fullmatch(value):
        return None, "a local readable receipt is required; a URL alone is not proof"
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    try:
        path = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None, f"receipt path is not readable: {value}"
    if not path.is_file():
        return None, f"receipt path is not a file: {value}"
    try:
        if path.stat().st_size > 131_072:
            return None, "receipt file exceeds 128 KiB"
    except OSError:
        return None, f"receipt path is not readable: {value}"
    return path, None


def _read_local(path: Path) -> tuple[str | None, str | None]:
    try:
        return path.read_text(encoding="utf-8"), None
    except (OSError, UnicodeError):
        return None, f"receipt is not readable UTF-8: {path}"


def _planned_continuation_problem(value: str, task_sha256: str | None) -> str | None:
    match = re.fullmatch(r"task-sha256=([0-9a-f]{64})\s+::\s+(\S.*?)\s*", value)
    if match is None:
        return "checklist Continuation must use `task-sha256=<bound digest> :: <exact next action>`"
    if task_sha256 and match.group(1) != task_sha256:
        return "checklist Continuation is not bound to the delegated task"
    if PLACEHOLDER_RE.fullmatch(match.group(2)) or FORBIDDEN_CONTINUATION_RE.search(match.group(2)):
        return "checklist Continuation must resume an owned action, not abandon, defer, or report only"
    return None


def checklist_problem(
    raw_path: str,
    requested: str,
    resolved: str,
    base_dir: Path,
    task_sha256: str | None = None,
) -> str | None:
    path, problem = _local_file(raw_path, base_dir)
    if problem:
        return problem
    assert path is not None
    text, problem = _read_local(path)
    if problem:
        return problem
    assert text is not None
    requested_match = re.search(r"(?mi)^- Requested capability:\s*(\S.*?)\s*$", text)
    candidate_match = re.search(r"(?mi)^- Candidate/source/commit:\s*(\S.*?)\s*$", text)
    decision_match = re.search(
        r"(?mi)^- Decision:\s*(USE_INSTALLED|INSTALL_PINNED|BUILD_RESEARCHED|REJECT)\s*$",
        text,
    )
    continuation_match = re.search(r"(?mi)^- Continuation:\s*(\S.*?)\s*$", text)
    if not requested_match or requested_match.group(1).strip() != requested:
        return "checklist Requested capability must exactly match the routed gap"
    candidate_has_resolved = bool(
        candidate_match
        and re.search(
            rf"(?:^|[^a-z0-9:_-]){re.escape(resolved)}(?:$|[^a-z0-9:_-])",
            candidate_match.group(1),
            re.IGNORECASE,
        )
    )
    if not candidate_has_resolved:
        return "checklist Candidate/source/commit must name the accepted or created skill"
    if not decision_match or decision_match.group(1) == "REJECT":
        return "checklist needs an accepted USE_INSTALLED, INSTALL_PINNED, or BUILD_RESEARCHED decision"
    if not continuation_match:
        return "checklist needs the exact continuation action for the original task"
    problem = _planned_continuation_problem(continuation_match.group(1).strip(), task_sha256)
    if problem:
        return problem
    for label in CHECKLIST_BOXES:
        if not re.search(rf"(?mi)^- \[[xX]\] {re.escape(label)}\s*$", text):
            return f"checklist box is not checked: {label}"
    if decision_match.group(1) == "BUILD_RESEARCHED":
        return research_build_problem(text, resolved, base_dir)
    return None


def _skill_artifact_paths(checklist_path: Path, base_dir: Path) -> tuple[set[Path] | None, str | None]:
    """Collect skill-build artifacts so original-task proof cannot recycle them."""
    text, problem = _read_local(checklist_path)
    if problem:
        return None, problem
    assert text is not None
    result = {checklist_path}
    for label in ("Skill path", "Research record", "Eval record", "Maintenance record", "Independent review"):
        raw = _field(text, label)
        if raw is None:
            continue
        path, path_problem = _local_file(raw, base_dir)
        if path_problem:
            return None, f"{label}: {path_problem}"
        assert path is not None
        result.add(path)
        if label not in {"Research record", "Eval record", "Independent review"}:
            continue
        _, payload, json_problem = _json_record(str(path), base_dir, label)
        if json_problem:
            return None, json_problem
        assert payload is not None
        nested = payload.get("local_evidence") if label == "Research record" else payload.get("traces")
        if not isinstance(nested, list):
            continue
        for item in nested:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                continue
            nested_path, nested_problem = _local_file(item["path"], path.parent)
            if nested_problem:
                return None, f"{label} nested evidence: {nested_problem}"
            assert nested_path is not None
            result.add(nested_path)
    return result, None


def continuation_result_problem(
    message: str, task_sha256: str, checklist_path: str, base_dir: Path
) -> str | None:
    match = CONTINUATION_RE.search(message)
    if match is None:
        return (
            "GAP_RESOLVED needs `Continuation: RESUMED task-sha256=<bound digest> "
            ":: <completed original-task action>`"
        )
    if match.group(1) != task_sha256:
        return "GAP_RESOLVED Continuation is not bound to the delegated task"
    if PLACEHOLDER_RE.fullmatch(match.group(2)) or FORBIDDEN_CONTINUATION_RE.search(match.group(2)):
        return "GAP_RESOLVED must resume the original task, not abandon, defer, or report only"
    evidence_match = CONTINUATION_EVIDENCE_RE.search(message)
    if evidence_match is None:
        return "GAP_RESOLVED needs a local Continuation evidence receipt"
    evidence_path, payload, problem = _json_record(
        evidence_match.group(1), base_dir, "Continuation evidence"
    )
    if problem:
        return problem
    assert evidence_path is not None and payload is not None
    checklist, problem = _local_file(checklist_path, base_dir)
    if problem:
        return problem
    assert checklist is not None
    reserved, problem = _skill_artifact_paths(checklist, base_dir)
    if problem:
        return problem
    assert reserved is not None
    if evidence_path in reserved:
        return "Continuation evidence must be distinct from every skill-build artifact"
    if payload.get("schema_version") != 2 or payload.get("task_sha256") != task_sha256:
        return "Continuation evidence schema_version 2/task_sha256 does not match the delegated task"
    terminal = payload.get("terminal_state")
    outcomes = payload.get("outcomes")
    if terminal not in {"PASS", "BLOCKED_EXTERNAL"}:
        return "Continuation evidence needs terminal_state PASS or BLOCKED_EXTERNAL"
    if not isinstance(outcomes, list) or not outcomes:
        return "Continuation evidence needs non-empty outcomes"
    traces, problem = _trace_map(payload, evidence_path, "Continuation evidence")
    if problem:
        return problem
    assert traces is not None
    overlap = set(traces.values()) & reserved
    if overlap:
        return "Continuation evidence traces must not reuse research, eval, review, or checklist evidence"
    expected_kind = "original-task-execution" if terminal == "PASS" else "external-boundary"
    for trace_id, trace_path in traces.items():
        try:
            trace_payload = json.loads(trace_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return f"Continuation evidence trace {trace_id} must be valid UTF-8 JSON"
        if not isinstance(trace_payload, dict) or trace_payload.get("task_sha256") != task_sha256:
            return f"Continuation evidence trace {trace_id} is not bound to the delegated task"
    cases, problem = _trace_cases(traces, "Continuation evidence", expected_kind, {"outcome"})
    if problem:
        return problem
    assert cases is not None
    seen: set[str] = set()
    for outcome in outcomes:
        if not isinstance(outcome, dict) or not isinstance(outcome.get("id"), str) or not outcome["id"].strip() or outcome["id"] in seen:
            return "Continuation evidence outcomes need unique non-empty ids"
        seen.add(outcome["id"])
        if "passed" in outcome:
            return "Continuation evidence outcomes must not self-assert passed"
        refs = outcome.get("case_ids")
        if not isinstance(refs, list) or not refs or any(ref not in cases for ref in refs):
            return "Continuation evidence outcomes need valid case_ids"
        if any(not cases[ref]["passed"] for ref in refs):
            return "Continuation evidence outcomes reference a failing case"
        if terminal == "PASS" and any(cases[ref]["producer_exit_code"] != 0 for ref in refs):
            return "Continuation evidence PASS needs zero-exit original-task execution"
    if terminal == "BLOCKED_EXTERNAL":
        for field in ("blocker", "recheck"):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                return f"Continuation evidence BLOCKED_EXTERNAL needs {field}"
    return None


def pause_problem(detail: str, base_dir: Path) -> str | None:
    parsed = PAUSE_DETAIL_RE.fullmatch(detail)
    if parsed is None:
        return (
            "PAUSED_BY_SKILL must use `<skill> :: <local SKILL.md>#L<line> :: "
            "<exact instruction>`"
        )
    path, problem = _local_file(parsed.group("path"), base_dir)
    if problem:
        return problem
    assert path is not None
    if path.name != "SKILL.md":
        return "PAUSED_BY_SKILL reference must be a SKILL.md"
    text, problem = _read_local(path)
    if problem:
        return problem
    assert text is not None
    lines = text.splitlines()
    line_number = int(parsed.group("line"))
    if line_number > len(lines):
        return "PAUSED_BY_SKILL line is outside the referenced SKILL.md"
    if parsed.group("instruction").strip() != lines[line_number - 1].strip():
        return "PAUSED_BY_SKILL instruction does not match the referenced SKILL.md line"
    return None


def _bound_route_problem(
    message: str, route: dict | None
) -> tuple[str | None, str | None, list[str], list[str]]:
    if route is None:
        return None, None, [], []
    digest = route.get("task_sha256")
    route_name = route.get("route")
    profile = route.get("client_profile")
    skills = route.get("required_skills")
    missing = route.get("missing_skills")
    if (
        not isinstance(digest, str)
        or not SHA256_RE.fullmatch(digest)
        or route_name not in {"curated", "skill-gap", "no-high-confidence-match", "user-opt-out"}
        or profile not in {"claude", "codex"}
        or not isinstance(skills, list)
        or any(not isinstance(skill, str) or not re.fullmatch(SKILL_NAME, skill) for skill in skills)
        or len(skills) != len(set(skills))
        or not isinstance(missing, list)
        or any(not isinstance(skill, str) or not re.fullmatch(SKILL_NAME, skill) for skill in missing)
        or len(missing) != len(set(missing))
        or set(skills) & set(missing)
        or (route_name == "curated" and (not skills or missing))
        or (route_name == "skill-gap" and (skills or not missing))
        or (route_name in {"no-high-confidence-match", "user-opt-out"} and (skills or missing))
    ):
        return "bound task route is malformed", None, [], []
    marker = TASK_ROUTE_RE.search(message)
    if marker is None:
        return "missing `Task route: <bound task-sha256>`", digest, skills, missing
    if marker.group(1) != digest:
        return "Task route does not match the delegated task", digest, skills, missing
    return None, digest, skills, missing


def _used_skills(detail: str) -> list[str] | None:
    if not detail:
        return None
    values = [item.strip() for item in detail.split(",")]
    if not values or any(not re.fullmatch(SKILL_NAME, item) for item in values):
        return None
    return values


def skill_disposition_problem(
    message: str, base_dir: Path | None = None, route: dict | None = None
) -> str | None:
    base_dir = base_dir or Path.cwd()
    route_problem, task_sha256, expected_skills, missing_skills = _bound_route_problem(message, route)
    if route_problem:
        return route_problem
    route_name = route.get("route") if route else None
    match = SKILL_DISPOSITION_RE.search(message)
    if match is None:
        return "missing a valid Skill disposition receipt"
    kind = match.group(1)
    detail = (match.group(2) or "").strip()
    if kind == "NO_MATCH":
        if detail:
            return "NO_MATCH must not name a skill"
        if expected_skills or missing_skills:
            return "NO_MATCH cannot close a task with routed required or missing skills"
        return None
    if kind == "USED":
        used = _used_skills(detail)
        if used is None:
            return "USED must name comma-separated applied skills"
        if route_name == "user-opt-out":
            return "USED contradicts the task's explicit skill opt-out"
        if missing_skills:
            return "USED cannot close an unresolved routed skill gap"
        if expected_skills and used != expected_skills:
            return "USED skills must exactly match the bound routed skill set"
        return None
    if kind == "PAUSED_BY_SKILL":
        problem = pause_problem(detail, base_dir)
        if problem:
            return problem
        paused_skill = PAUSE_DETAIL_RE.fullmatch(detail).group("skill")  # type: ignore[union-attr]
        if route_name == "user-opt-out":
            return "PAUSED_BY_SKILL contradicts the task's explicit skill opt-out"
        if missing_skills:
            return "PAUSED_BY_SKILL cannot close an unresolved routed skill gap"
        if expected_skills and paused_skill not in expected_skills:
            return "PAUSED_BY_SKILL must name a bound routed skill"
        return None
    parsed = GAP_DETAIL_RE.fullmatch(detail)
    if parsed is None:
        return (
            "GAP_RESOLVED must use `<requested> -> <accepted-or-created>; "
            "checklist=<local receipt path>`"
        )
    if route is not None and parsed.group("requested") not in missing_skills:
        return "GAP_RESOLVED requested capability is not in the bound routed missing-skill set"
    problem = checklist_problem(
        parsed.group("path"),
        parsed.group("requested"),
        parsed.group("resolved"),
        base_dir,
        task_sha256,
    )
    if problem:
        return problem
    if task_sha256:
        return continuation_result_problem(
            message, task_sha256, parsed.group("path"), base_dir
        )
    return None


def is_source_anchor(basis: str, evidence: str) -> bool:
    """Require a source-shaped anchor, not a merely plausible sentence."""
    if basis == "USER_CONSTRAINT":
        return bool(USER_CONSTRAINT_RE.search(evidence))
    return bool(URL_RE.search(evidence) or PATH_RE.search(evidence) or COMMAND_RE.search(evidence))


def receipt_problem(
    message: str, base_dir: Path | None = None, route: dict | None = None
) -> str | None:
    skill_problem = skill_disposition_problem(message, base_dir, route)
    if skill_problem is not None:
        return skill_problem
    basis = BASIS_RE.search(message)
    if basis is None:
        return "missing a valid Decision basis receipt"
    evidence = EVIDENCE_RE.search(message)
    if evidence is None:
        return "missing an Evidence receipt"
    value = evidence.group(1).strip()
    if basis.group(1) == "NO_DECISION":
        if value != "N/A":
            return "NO_DECISION must use Evidence: N/A"
        return None
    if value == "N/A":
        return "a factual decision needs a current evidence anchor"
    lowered = value.casefold()
    if STALE_LEAD_RE.search(lowered):
        return "memory or prior assistant text is not a decision basis"
    if not is_source_anchor(basis.group(1), value):
        if basis.group(1) == "USER_CONSTRAINT":
            return "USER_CONSTRAINT needs `Evidence: user request: <exact constraint>`"
        return "Evidence needs a current command, filesystem path, or primary-document URL"
    return None


def main() -> int:
    try:
        event = json.loads(sys.stdin.read().lstrip("\ufeff"))
    except (json.JSONDecodeError, EOFError):
        return 0
    if not isinstance(event, dict) or event.get("hook_event_name") != "SubagentStop":
        return 0
    message = str(event.get("last_assistant_message") or "")
    event_cwd = event.get("cwd")
    base_dir = Path(str(event_cwd)) if event_cwd else Path.cwd()
    session_id = str(event.get("session_id") or "").strip()
    agent_id = str(event.get("agent_id") or "").strip()
    if not session_id or not agent_id:
        route = None
        problem = "SubagentStop is missing session_id or agent_id for task-bound routing"
    else:
        route = load_agent(session_id, agent_id)
        problem = None if route is not None else "no task-bound route was recorded for this agent_id"
    if problem is None:
        problem = receipt_problem(message, base_dir, route)
    if problem is None:
        return 0
    if event.get("stop_hook_active"):
        print(json.dumps({
            "systemMessage": "Subagent ended without a valid decision-source receipt after one repair pass: " + problem,
        }, ensure_ascii=False))
        return 0
    print(json.dumps({
        "decision": "block",
        "reason": (
            "Before finishing, use the recorded task route and add a compact receipt: "
            "`Task route: <bound task-sha256>`, `Skill disposition: "
            "USED <skill(s)> | NO_MATCH | GAP_RESOLVED <requested> -> "
            "<accepted-or-created>; checklist=<local checked receipt path> | "
            "PAUSED_BY_SKILL <skill> :: <local SKILL.md>#L<line> :: "
            "<exact instruction>`, `Decision basis: OBSERVED | "
            "PRIMARY_DOC | USER_CONSTRAINT | INCONCLUSIVE | NO_DECISION` and "
            "`Evidence: <current command/path/URL, or N/A only for NO_DECISION>`. "
            "For GAP_RESOLVED also add `Continuation: RESUMED task-sha256=<bound "
            "digest> :: <completed original-task action>` and `Continuation evidence: "
            "<local terminal JSON receipt>`. "
            + problem
        ),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
