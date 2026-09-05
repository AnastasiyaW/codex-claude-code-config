"""Regression proof for the Codex subagent decision-source receipt boundary."""
from __future__ import annotations

import json
import hashlib
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path


HOOK = Path(__file__).resolve().parent.parent / "hooks" / "subagent-evidence-receipt.py"


ROOT = Path(__file__).resolve().parent.parent
GAP_RECEIPT = ROOT / "evals" / "hooks" / "fixtures" / "skill-gap-receipt-pass.md"
UNCHECKED_GAP_RECEIPT = ROOT / "evals" / "hooks" / "fixtures" / "skill-gap-receipt-unchecked.md"
RESEARCH_GAP_RECEIPT = ROOT / "evals" / "hooks" / "fixtures" / "skill-gap-receipt-research-pass.md"
SHALLOW_RESEARCH_GAP_RECEIPT = ROOT / "evals" / "hooks" / "fixtures" / "skill-gap-receipt-research-shallow.md"
LEGACY_CREATE_GAP_RECEIPT = ROOT / "evals" / "hooks" / "fixtures" / "skill-gap-receipt-legacy-create.md"
RESEARCH_SKILL = ROOT / "evals" / "hooks" / "fixtures" / "research-built-skill"
SAMPLE_SKILL = ROOT / "evals" / "hooks" / "fixtures" / "sample-skill" / "SKILL.md"
CONTINUATION = RESEARCH_SKILL / "continuation.json"
REUSED_CONTINUATION = RESEARCH_SKILL / "continuation-reused-eval.json"
TASK_SHA = "a" * 64

sys.path.insert(0, str(HOOK.parent))
SPEC = importlib.util.spec_from_file_location("subagent_evidence_receipt", HOOK)
assert SPEC is not None and SPEC.loader is not None
HOOK_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOOK_MODULE)


def invoke(
    message: str,
    retry: bool = False,
    *,
    route: str = "no-high-confidence-match",
    skills: list[str] | None = None,
    missing_skills: list[str] | None = None,
    task_sha: str = TASK_SHA,
    include_route: bool = True,
) -> dict | None:
    skills = skills or []
    missing_skills = missing_skills or []
    if include_route:
        message = f"Task route: {task_sha}\n{message}"
    with tempfile.TemporaryDirectory(prefix="subagent-receipt-state-") as state_dir:
        session_id, agent_id = "session-1", "agent-1"
        session_key = hashlib.sha256(session_id.encode()).hexdigest()
        agent_key = hashlib.sha256(agent_id.encode()).hexdigest()
        state_path = Path(state_dir) / session_key / "agents" / f"{agent_key}.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text(json.dumps({
            "state_version": 1,
            "task_sha256": task_sha,
            "route": route,
            "client_profile": "codex",
            "required_skills": skills,
            "missing_skills": missing_skills,
        }), encoding="utf-8")
        event = {
            "hook_event_name": "SubagentStop",
            "session_id": session_id,
            "agent_id": agent_id,
            "last_assistant_message": message,
            "stop_hook_active": retry,
            "cwd": str(ROOT),
        }
        env = dict(os.environ)
        env["CODEX_SKILL_CONTRACT_STATE_DIR"] = state_dir
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(event),
            text=True,
            capture_output=True,
            encoding="utf-8",
            check=True,
            env=env,
        )
        return json.loads(result.stdout) if result.stdout.strip() else None


def gap_message(receipt: Path) -> str:
    return (
        f"Skill disposition: GAP_RESOLVED native-cpp-memory -> "
        f"{'native-cpp-memory' if receipt == RESEARCH_GAP_RECEIPT else 'advanced-cpp-engineering'}; "
        f"checklist={receipt}\n"
        "Decision basis: OBSERVED\n"
        f"Evidence: {receipt}\n"
        f"Continuation: RESUMED task-sha256={TASK_SHA} :: completed the original native-memory investigation\n"
        f"Continuation evidence: {CONTINUATION}"
    )


def main() -> int:
    observed = "Verdict: SUPPORTED\nSkill disposition: USED remote-compute-ops\nDecision basis: OBSERVED\nEvidence: python scripts/test_agent_skill_contract.py"
    assert invoke(observed) is None
    primary_doc = "Skill disposition: NO_MATCH\nDecision basis: PRIMARY_DOC\nEvidence: https://developers.openai.com/codex/hooks/"
    assert invoke(primary_doc) is None
    user_constraint = "Skill disposition: NO_MATCH\nDecision basis: USER_CONSTRAINT\nEvidence: user request: do not delete data"
    assert invoke(user_constraint) is None
    no_decision = "Skill disposition: NO_MATCH\nDecision basis: NO_DECISION\nEvidence: N/A"
    assert invoke(no_decision) is None
    gap = gap_message(GAP_RECEIPT)
    assert invoke(gap, route="skill-gap", missing_skills=["native-cpp-memory"]) is None
    researched_gap = gap_message(RESEARCH_GAP_RECEIPT)
    assert invoke(researched_gap, route="skill-gap", missing_skills=["native-cpp-memory"]) is None
    paused = f"Skill disposition: PAUSED_BY_SKILL sample-skill :: {SAMPLE_SKILL}#L3 :: - Stop only when the external approval is observed.\nDecision basis: USER_CONSTRAINT\nEvidence: user request: require external approval"
    assert invoke(paused) is None
    missing = invoke("Verdict: SUPPORTED")
    assert missing and missing["decision"] == "block" and "Decision basis" in missing["reason"]
    missing_disposition = invoke("Decision basis: OBSERVED\nEvidence: python scripts/test_agent_skill_contract.py")
    assert missing_disposition and "Skill disposition" in missing_disposition["reason"]
    generic_pause = invoke("Skill disposition: PAUSED_BY_SKILL x :: no\nDecision basis: OBSERVED\nEvidence: python scripts/test_agent_skill_contract.py")
    assert generic_pause and "local SKILL.md" in generic_pause["reason"]
    wrong_pause_line = invoke(f"Skill disposition: PAUSED_BY_SKILL sample-skill :: {SAMPLE_SKILL}#L3 :: not the cited line\nDecision basis: OBSERVED\nEvidence: {SAMPLE_SKILL}")
    assert wrong_pause_line and "does not match" in wrong_pause_line["reason"]
    malformed_gap = invoke("Skill disposition: GAP_RESOLVED checklist=C:/definitely-not-a-receipt.md\nDecision basis: OBSERVED\nEvidence: C:/definitely-not-a-receipt.md", route="skill-gap", missing_skills=["native-cpp-memory"])
    assert malformed_gap and "<requested>" in malformed_gap["reason"]
    missing_gap_receipt = invoke("Skill disposition: GAP_RESOLVED native-cpp-memory -> new; checklist=C:/definitely-not-a-receipt.md\nDecision basis: OBSERVED\nEvidence: C:/definitely-not-a-receipt.md", route="skill-gap", missing_skills=["native-cpp-memory"])
    assert missing_gap_receipt and "not readable" in missing_gap_receipt["reason"]
    unchecked_gap = invoke(gap_message(UNCHECKED_GAP_RECEIPT), route="skill-gap", missing_skills=["native-cpp-memory"])
    assert unchecked_gap and "Isolated validation/behavior check" in unchecked_gap["reason"]
    shallow_research_gap = invoke(gap_message(SHALLOW_RESEARCH_GAP_RECEIPT).replace("advanced-cpp-engineering", "native-cpp-memory"), route="skill-gap", missing_skills=["native-cpp-memory"])
    assert shallow_research_gap and "Skill path" in shallow_research_gap["reason"]
    legacy_create = invoke(gap_message(LEGACY_CREATE_GAP_RECEIPT).replace("advanced-cpp-engineering", "native-cpp-memory"), route="skill-gap", missing_skills=["native-cpp-memory"])
    assert legacy_create and "BUILD_RESEARCHED" in legacy_create["reason"]
    research_receipt_text = RESEARCH_GAP_RECEIPT.read_text(encoding="utf-8")
    unchecked_live = HOOK_MODULE.research_build_problem(
        research_receipt_text.replace(
            "- [x] Live discovery/registration passed in every intended harness",
            "- [ ] Live discovery/registration passed in every intended harness",
        ),
        "native-cpp-memory",
        ROOT,
    )
    assert unchecked_live and "Live discovery/registration" in unchecked_live
    not_better_receipt = research_receipt_text.replace(
        "evals/hooks/fixtures/research-built-skill/eval.json",
        "evals/hooks/fixtures/research-built-skill/eval-not-better.json",
    )
    not_better_result = HOOK_MODULE.research_build_problem(
        not_better_receipt, "native-cpp-memory", ROOT
    )
    assert not_better_result and "beat the baseline" in not_better_result
    missing_trace_receipt = research_receipt_text.replace(
        "evals/hooks/fixtures/research-built-skill/eval.json",
        "evals/hooks/fixtures/research-built-skill/eval-missing-trace.json",
    )
    missing_trace_result = HOOK_MODULE.research_build_problem(
        missing_trace_receipt, "native-cpp-memory", ROOT
    )
    assert missing_trace_result and "valid case_ids" in missing_trace_result
    prose_eval_receipt = research_receipt_text.replace(
        "evals/hooks/fixtures/research-built-skill/eval.json",
        "evals/hooks/fixtures/research-built-skill/eval-prose-trace.json",
    )
    prose_eval_result = HOOK_MODULE.research_build_problem(
        prose_eval_receipt, "native-cpp-memory", ROOT
    )
    assert prose_eval_result and "valid UTF-8 JSON" in prose_eval_result
    prose_research_receipt = research_receipt_text.replace(
        "evals/hooks/fixtures/research-built-skill/research.json",
        "evals/hooks/fixtures/research-built-skill/research.md",
    )
    prose_research_result = HOOK_MODULE.research_build_problem(
        prose_research_receipt, "native-cpp-memory", ROOT
    )
    assert prose_research_result and "valid JSON" in prose_research_result
    prose_review_receipt = research_receipt_text.replace(
        "evals/hooks/fixtures/research-built-skill/review.json",
        "evals/hooks/fixtures/research-built-skill/review-prose-trace.json",
    )
    prose_review_result = HOOK_MODULE.research_build_problem(
        prose_review_receipt, "native-cpp-memory", ROOT
    )
    assert prose_review_result and "valid UTF-8 JSON" in prose_review_result
    self_review_receipt = research_receipt_text.replace(
        "evals/hooks/fixtures/research-built-skill/review.json",
        "evals/hooks/fixtures/research-built-skill/review-self.json",
    )
    self_review_result = HOOK_MODULE.research_build_problem(
        self_review_receipt, "native-cpp-memory", ROOT
    )
    assert self_review_result and "differ from author_id" in self_review_result
    bad_continuation = HOOK_MODULE.checklist_problem(
        str(RESEARCH_GAP_RECEIPT),
        "native-cpp-memory",
        "native-cpp-memory",
        ROOT,
        "b" * 64,
    )
    assert bad_continuation and "not bound" in bad_continuation
    abandoned_text = research_receipt_text.replace(
        "run the original native-memory investigation through terminal proof",
        "abandon the original task",
    )
    abandoned = HOOK_MODULE._planned_continuation_problem(
        HOOK_MODULE._field(abandoned_text, "Continuation"), TASK_SHA
    )
    assert abandoned and "not abandon" in abandoned
    routed_no_match = invoke(
        "Skill disposition: NO_MATCH\nDecision basis: OBSERVED\nEvidence: python scripts/test_agent_skill_contract.py",
        route="skill-gap",
        missing_skills=["native-cpp-memory"],
    )
    assert routed_no_match and "cannot close" in routed_no_match["reason"]
    routed_gap_pause = invoke(
        f"Skill disposition: PAUSED_BY_SKILL sample-skill :: {SAMPLE_SKILL}#L3 :: - Stop only when the external approval is observed.\nDecision basis: USER_CONSTRAINT\nEvidence: user request: require external approval",
        route="skill-gap",
        missing_skills=["native-cpp-memory"],
    )
    assert routed_gap_pause and "cannot close" in routed_gap_pause["reason"]
    wrong_task_route = invoke(
        f"Task route: {TASK_SHA}\nSkill disposition: USED native-cpp-memory\nDecision basis: OBSERVED\nEvidence: python scripts/test_agent_skill_contract.py",
        route="curated",
        skills=["native-cpp-memory"],
        task_sha="b" * 64,
        include_route=False,
    )
    assert wrong_task_route and "does not match" in wrong_task_route["reason"]
    missing_task_route = invoke(
        "Skill disposition: USED native-cpp-memory\nDecision basis: OBSERVED\nEvidence: python scripts/test_agent_skill_contract.py",
        route="skill-gap",
        missing_skills=["native-cpp-memory"],
        include_route=False,
    )
    assert missing_task_route and "Task route" in missing_task_route["reason"]
    forged_continuation = invoke(
        gap_message(RESEARCH_GAP_RECEIPT).replace(
            str(CONTINUATION), str(RESEARCH_SKILL / "continuation-bad-trace.json")
        ),
        route="skill-gap",
        missing_skills=["native-cpp-memory"],
    )
    assert forged_continuation and "sha256 does not match" in forged_continuation["reason"]
    recycled_continuation = invoke(
        gap_message(RESEARCH_GAP_RECEIPT).replace(str(CONTINUATION), str(REUSED_CONTINUATION)),
        route="skill-gap",
        missing_skills=["native-cpp-memory"],
    )
    assert recycled_continuation and "must not reuse" in recycled_continuation["reason"]
    memory = invoke("Skill disposition: NO_MATCH\nDecision basis: OBSERVED\nEvidence: memory from an earlier assistant")
    assert memory and memory["decision"] == "block" and "memory" in memory["reason"]
    prose = invoke("Skill disposition: NO_MATCH\nDecision basis: PRIMARY_DOC\nEvidence: definitely checked the documentation")
    assert prose and prose["decision"] == "block" and "command, filesystem path, or primary-document URL" in prose["reason"]
    malformed_user = invoke("Skill disposition: NO_MATCH\nDecision basis: USER_CONSTRAINT\nEvidence: do not delete data")
    assert malformed_user and malformed_user["decision"] == "block" and "USER_CONSTRAINT" in malformed_user["reason"]
    repeated = invoke("Verdict: SUPPORTED", retry=True)
    assert repeated and "systemMessage" in repeated and "after one repair pass" in repeated["systemMessage"]
    print("test_subagent_evidence_receipt: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
