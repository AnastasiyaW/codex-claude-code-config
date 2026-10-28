---
name: ml-research-lab
description: Machine-learning research loop for dataset curation, fine-tuning, evaluation, inference deployment, experiment tracking, and model explainability. Use when working on ML experiments, training data, model benchmarks, RunPod/GPU runs, classifier quality, vLLM/GGUF serving, SHAP-style model explanations, or research-to-code iterations. Do not use for a simple code edit that has no ML dataset, metric, model, or experiment artifact.
---

# ML Research Lab

Use this skill as the compact router for ML work. It is derived from an audit of
`synthetic-sciences/openscience` at commit `531467c`, but does not require running
OpenScience or loading its full 250+ skill set.

## Operating Loop

1. Freeze the question as a measurable hypothesis.
2. Identify dataset provenance, labels, splits, leakage risks, and regeneration cost.
3. Pick the smallest baseline that can disprove the idea.
4. Define metrics before training. For release claims, require train/val/test split,
   no test-set model selection, and multi-seed proof when cost permits.
5. Run or wire experiment tracking before long jobs start.
6. Save artifacts: config, command, data manifest, metrics JSON/CSV, logs, model hash,
   and a short conclusion.
7. Compare against baseline, then keep/discard the change from evidence.

## Domain Routing

- Dataset or scrape cleanup: start from data quality, deduplication, leakage checks,
  train/eval splits, and regeneration notes.
- Classical classifier or tabular baseline: use scikit-learn-style pipelines with
  preprocessing inside the pipeline and stratified splits for classification.
- Model debugging or trust: add SHAP/explainability for feature importance, leakage,
  bias/proxy features, and misclassified samples.
- LLM fine-tuning: prefer JSONL chat format, data validation, LoRA/QLoRA baseline,
  and tracked runs before scaling.
- Single-GPU fast LoRA/QLoRA: consider Unsloth only after checking hardware, CUDA,
  model support, and export target.
- Large or production inference: use vLLM for high-throughput GPU serving, GGUF or
  llama.cpp for local/Apple/CPU-friendly deployment, and TensorRT-LLM only when the
  NVIDIA production optimization cost is justified.
- Research write-up: report method, dataset, exact metric formula, baseline source,
  limitations, and failure cases.

## Verification Gates

- Data gate: schema valid, duplicates/leakage checked, split manifest saved.
- Metric gate: exact metric formula named; if benchmarked, original baseline source
  and benchmark code checked.
- Runtime gate: command/log path and environment captured; GPU memory and errors
  checked for long runs.
- Tracking gate: metrics are retrievable as JSON/CSV or a dashboard link plus local
  export.
- Deployment gate: latency, throughput, memory, and OOM behavior measured before
  claiming production readiness.

## Adoption Boundary

Do not import broad external skill collections wholesale. Use the inventory script
`${CLAUDE_PLUGIN_ROOT}/scripts/openscience_skill_inventory.py` to rank candidates, inspect the relevant
source skill manually, then promote only compact workflows or deterministic scripts
that improve our own tests.
