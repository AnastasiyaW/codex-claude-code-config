# Report Context Schema

Create a JSON object with these fields before running `generate_report.py`:

```json
{
  "title": "Page one skips the first results",
  "project": "Example project",
  "generated_at": "2026-07-14",
  "mode": "hunt-and-prove",
  "original_report": "No bug supplied; inspect the codebase for likely correctness defects.",
  "discovery_scope": ["pagination.py", "existing tests and README contract"],
  "candidates": [
    {
      "candidate": "Page one skips the first results",
      "location": "/absolute/path/pagination.py:2",
      "contract": "README and callers treat page numbers as one-based.",
      "trigger": "paginate(items, page=1, per_page=5)",
      "confidence": "high",
      "outcome": "REPRODUCED"
    }
  ],
  "expected": "Page one returns the first five items.",
  "actual": "Page one starts at item six.",
  "environment": "Python 3.13, local test environment",
  "reproduction": "A focused unit test calls paginate(items, page=1, per_page=5).",
  "failure_signal": "Expected [1,2,3,4,5], received [6,7,8,9,10].",
  "root_cause": "The start offset treated a one-based page number as zero-based.",
  "fix_summary": "Changed the offset to (page - 1) * per_page.",
  "why_causal": "The corrected offset directly controls the first returned index.",
  "reproduction_files": [
    {"path": "/absolute/path/test_pagination.py", "line": 1, "summary": "Regression test approved at Gate 1."}
  ],
  "fix_files": [
    {"path": "/absolute/path/pagination.py", "line": 2, "summary": "One-line offset correction approved at Gate 2."}
  ],
  "checks": [
    {"name": "Regression test", "status": "passed", "detail": "Red before, green after."}
  ],
  "reproduce": ["python3 -m unittest -v test_pagination.py"],
  "limitations": ["Fixture covers one-based positive page numbers."],
  "residual_risks": ["Invalid page values require a separate contract decision."],
  "notes": ["No dependencies or public APIs changed."]
}
```

Use absolute paths for files so Codex can render clickable links. Keep command output and exit codes in the evidence JSON; do not manually rewrite them in context.

Use an empty `candidates` list and describe the supplied symptom in `original_report` when a user provides a known bug. For discovery mode, record every candidate approved for testing and use `outcome` values such as `REPRODUCED`, `NOT_REPRODUCED`, or `INCONCLUSIVE`.
