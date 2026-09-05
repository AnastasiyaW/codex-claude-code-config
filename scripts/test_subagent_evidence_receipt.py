"""Regression proof for the Codex subagent decision-source receipt boundary."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


HOOK = Path(__file__).resolve().parent.parent / "hooks" / "subagent-evidence-receipt.py"


ROOT = Path(__file__).resolve().parent.parent
GAP_RECEIPT = ROOT / "evals" / "hooks" / "fixtures" / "skill-gap-receipt-pass.md"
UNCHECKED_GAP_RECEIPT = ROOT / "evals" / "hooks" / "fixtures" / "skill-gap-receipt-unchecked.md"
SAMPLE_SKILL = ROOT / "evals" / "hooks" / "fixtures" / "sample-skill" / "SKILL.md"


def invoke(message: str, retry: bool = False) -> dict | None:
    event = {
        "hook_event_name": "SubagentStop",
        "last_assistant_message": message,
        "stop_hook_active": retry,
        "cwd": str(ROOT),
    }
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(result.stdout) if result.stdout.strip() else None


def main() -> int:
    observed = "Verdict: SUPPORTED\nSkill disposition: USED remote-compute-ops\nDecision basis: OBSERVED\nEvidence: python scripts/test_agent_skill_contract.py"
    assert invoke(observed) is None
    primary_doc = "Skill disposition: NO_MATCH\nDecision basis: PRIMARY_DOC\nEvidence: https://developers.openai.com/codex/hooks/"
    assert invoke(primary_doc) is None
    user_constraint = "Skill disposition: NO_MATCH\nDecision basis: USER_CONSTRAINT\nEvidence: user request: do not delete data"
    assert invoke(user_constraint) is None
    no_decision = "Skill disposition: NO_MATCH\nDecision basis: NO_DECISION\nEvidence: N/A"
    assert invoke(no_decision) is None
    gap = f"Skill disposition: GAP_RESOLVED native-cpp-memory -> advanced-cpp-engineering; checklist={GAP_RECEIPT}\nDecision basis: OBSERVED\nEvidence: {GAP_RECEIPT}"
    assert invoke(gap) is None
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
    malformed_gap = invoke("Skill disposition: GAP_RESOLVED checklist=C:/definitely-not-a-receipt.md\nDecision basis: OBSERVED\nEvidence: C:/definitely-not-a-receipt.md")
    assert malformed_gap and "<requested>" in malformed_gap["reason"]
    missing_gap_receipt = invoke("Skill disposition: GAP_RESOLVED old -> new; checklist=C:/definitely-not-a-receipt.md\nDecision basis: OBSERVED\nEvidence: C:/definitely-not-a-receipt.md")
    assert missing_gap_receipt and "not readable" in missing_gap_receipt["reason"]
    unchecked_gap = invoke(f"Skill disposition: GAP_RESOLVED native-cpp-memory -> advanced-cpp-engineering; checklist={UNCHECKED_GAP_RECEIPT}\nDecision basis: OBSERVED\nEvidence: {UNCHECKED_GAP_RECEIPT}")
    assert unchecked_gap and "Isolated validation/behavior check" in unchecked_gap["reason"]
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
