# Frozen Context Pack

Line: `v1-8-9-p1-classification-ml-core`
Baseline SHA: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`

## Objective
# Workbench v1.8.9 — P1 Classification ML Core Objective

Implement a model-agnostic, fail-closed classification capability and prove
the extension seam with Logistic Regression and Random Forest adapters. The
core must make class mapping, information-set availability, IID/group/temporal
split safety, fold-local preprocessing, isolated holdout evaluation, metrics,
calibration, baselines, controls, explanations and decision policy explicit
typed artifacts. It must preserve provenance and evidence boundaries so a
consumer can report facts without recomputing or turning model ranking into a
decision.

This is a package-local Wave B contribution. It may use only public Contract
Lock facades and must not modify central Agent/Notebook routing, the central
Report mount, the section registry, or any sibling line's private modules.
Provider and renderer declarations are contributions only; discovery and
natural-language Agent/Notebook cutover belong to the later single-writer
cutover line.

## Safety and correctness requirements

- Unknown feature availability, unsupported structure, invalid label mapping,
  insufficient class/group/period support and unjustified temporal safety fail
  closed with typed reasons.
- Learned preprocessing, resampling, calibration, threshold selection and
  tuning are fold-local and cannot inspect sealed holdout labels or predictions.
- Holdout access is one-time, predeclared and auditable; DecisionPolicy is
  separate from model selection and unknown costs produce scenarios only.
- Metrics preserve denominator, weighting, sample scope, numerical method,
  evaluation design, uncertainty and validation level. Undefined values are
  unavailable/insufficient, never zero-filled.
- Explanations are predictive/descriptive, not causal; subgroup and shift
  claims remain bounded by support and the release plan.
- Logistic and Random Forest share one adapter/protocol. Adding a fixture model
  must not require compiler/runtime/consumer family branches.

## Explicit non-goals and gates

- No central Agent/Notebook/Report/UI mount or route cutover.
- No online scoring service or external provider benchmark.
- C1 P0 package integration, real supervisor wiring, browser acceptance, full
  release gate, merge, push and tag are `NOT VERIFIED` for this line.

## Boundary
- Affected paths: `backend/workbench/predictive_research/classification_contracts.py`, `backend/workbench/predictive_research/classification_adapters.py`, `backend/workbench/predictive_research/classification_metrics.py`, `backend/workbench/predictive_research/classification_protocol.py`, `backend/workbench/predictive_research/classification_explanations.py`, `backend/workbench/predictive_research/schema.py`, `backend/workbench/predictive_research/consumer_projection.py`, `backend/workbench/predictive_research/graph_persistence.py`, `backend/workbench/predictive_research/split_kernel.py`, `backend/workbench/predictive_research/preprocessing.py`, `backend/workbench/predictive_research/persistence.py`, `backend/workbench/predictive_research/__init__.py`, `backend/workbench/prediction.py`, `backend/workbench/providers/builtin/classification_ml.json`, `frontend/src/report/ClassificationEvidence.tsx`, `frontend/src/report/ClassificationEvidence.test.tsx`, `tests/predictive_research/test_classification_contracts_v189.py`, `tests/predictive_research/test_classification_protocol_v189.py`, `tests/predictive_research/test_classification_leakage_v189.py`, `tests/predictive_research/test_classification_consumers_v189.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-classification-ml-core.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-p1-classification-ml-core-handoff.md`
- Allowed paths: `backend/workbench/predictive_research/classification_contracts.py`, `backend/workbench/predictive_research/classification_adapters.py`, `backend/workbench/predictive_research/classification_metrics.py`, `backend/workbench/predictive_research/classification_protocol.py`, `backend/workbench/predictive_research/classification_explanations.py`, `backend/workbench/predictive_research/schema.py`, `backend/workbench/predictive_research/consumer_projection.py`, `backend/workbench/predictive_research/graph_persistence.py`, `backend/workbench/predictive_research/split_kernel.py`, `backend/workbench/predictive_research/preprocessing.py`, `backend/workbench/predictive_research/persistence.py`, `backend/workbench/predictive_research/__init__.py`, `backend/workbench/prediction.py`, `backend/workbench/providers/builtin/classification_ml.json`, `frontend/src/report/ClassificationEvidence.tsx`, `frontend/src/report/ClassificationEvidence.test.tsx`, `tests/predictive_research/test_classification_contracts_v189.py`, `tests/predictive_research/test_classification_protocol_v189.py`, `tests/predictive_research/test_classification_leakage_v189.py`, `tests/predictive_research/test_classification_consumers_v189.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-classification-ml-core.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-p1-classification-ml-core-handoff.md`
- Protected paths: `backend/workbench/agent`, `backend/workbench/evidence`, `frontend/src/report/ReportView.tsx`, `frontend/src/workbench/registry/sectionRegistry.ts`
- Dependencies: `v1-8-9-contract-lock`, `v1-8-9-p0-workflow-truth-core`, `v1-8-9-p0-evidence-core`, `v1-8-9-p0-agent-compiler-core`
- Tests: `classification backend focused suites`, `ClassificationEvidence renderer test`, `frontend typecheck`, `compileall`, `git-diff-check`
- Known gates: `p0-c1-compatibility-not-verified`, `real-host-supervisor-not-verified`, `agent-notebook-report-cutover-not-verified`, `browser-provider-full-gate-release-not-verified`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none
