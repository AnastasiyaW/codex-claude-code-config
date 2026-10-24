Case: public-privacy-scan-existing-markers-20261024
Verdict: PASS
Baseline cause: Removing the private literals from hook defaults and fixtures, while allowing only the two immutable Google Fonts metadata files declared in the manifest, keeps the marker scan strict for all agent-authored source and stops false positives from third-party credits.
Owner boundary: scripts/sync_public_config.py
Reproducer: ["python", "scripts/test_sync_public_config.py"]
After result: The exact focused command passed both assertions; the strict indexed scan is clean with two exact Google Fonts metadata exemptions, and all four hook self-tests passed.
Reviewer: /root/harness_public_release_reviewer

Evidence reviewed: malformed exemptions fail, ordinary source markers still reject, and the exemption is limited to two declared immutable third-party metadata paths.
