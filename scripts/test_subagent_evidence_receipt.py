"""Regression proof for the Codex subagent decision-source receipt boundary."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


HOOK = Path(__file__).resolve().parent.parent / "hooks" / "subagent-evidence-receipt.py"


def invoke(message: str, retry: bool = False) -> dict | None:
    event = {
        "hook_event_name": "SubagentStop",
        "last_assistant_message": message,
        "stop_hook_active": retry,
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
    observed = "Verdict: SUPPORTED\nDecision basis: OBSERVED\nEvidence: python scripts/test_agent_skill_contract.py"
    assert invoke(observed) is None
    primary_doc = "Decision basis: PRIMARY_DOC\nEvidence: https://developers.openai.com/codex/hooks/"
    assert invoke(primary_doc) is None
    user_constraint = "Decision basis: USER_CONSTRAINT\nEvidence: user request: do not delete data"
    assert invoke(user_constraint) is None
    no_decision = "Decision basis: NO_DECISION\nEvidence: N/A"
    assert invoke(no_decision) is None
    missing = invoke("Verdict: SUPPORTED")
    assert missing and missing["decision"] == "block" and "Decision basis" in missing["reason"]
    memory = invoke("Decision basis: OBSERVED\nEvidence: memory from an earlier assistant")
    assert memory and memory["decision"] == "block" and "memory" in memory["reason"]
    prose = invoke("Decision basis: PRIMARY_DOC\nEvidence: definitely checked the documentation")
    assert prose and prose["decision"] == "block" and "command, filesystem path, or primary-document URL" in prose["reason"]
    malformed_user = invoke("Decision basis: USER_CONSTRAINT\nEvidence: do not delete data")
    assert malformed_user and malformed_user["decision"] == "block" and "USER_CONSTRAINT" in malformed_user["reason"]
    repeated = invoke("Verdict: SUPPORTED", retry=True)
    assert repeated and "systemMessage" in repeated and "after one repair pass" in repeated["systemMessage"]
    print("test_subagent_evidence_receipt: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
