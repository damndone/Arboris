# Frozen Context Pack

Line: `v1-8-9-p1-classification-ml-core`
Baseline SHA: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`

## Objective
# v1.8.9 P1 Classification ML Core Objective

Implement a model-agnostic classification contract and prove it with Logistic
and Random Forest adapters. Enforce explicit class mapping, information-set
availability, safe split profiles, fold-local preprocessing, isolated final
holdout, baselines and negative controls, calibrated metrics, bounded tuning,
explanation caveats and DecisionPolicy separation. Publish package-local
provider and renderer contributions without central Agent/Notebook/UI cutover.

## Formal baseline and scope

- Plan Lock: `f3836408cf15c3e7380823e5c1b303b4467c7aec`
- C0 wave lock: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`
- Formal line: `v1-8-9-p1-classification-ml-core`
- Worktree: `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-wave-a`
- Branch: `workbench-v1.8.9-wave-a`

This line owns only the classification package, additive prediction entrypoint,
package-local provider and unmounted renderer contribution listed in its Work
Order. Existing Data Consumer Core changes in the same Wave A worktree are
protected and remain untouched.

## Explicit non-goals

- No central Agent/Notebook routing, Context Compiler, workflow runtime,
  evidence core, report mount, canonical section registry or Data Consumer Core
  changes.
- No arbitrary provider execution, raw dict model selection, silent fallback,
  holdout exploration, browser acceptance, external provider benchmark,
  dependency installation, full release gate, commit, merge, push or tag.
- Only Logistic Regression and Random Forest are completion adapters; additional
  model support remains an extension seam fixture, not a completion claim.

## Boundary
- Affected paths: `backend/workbench/predictive_research/classification_contracts.py`, `backend/workbench/predictive_research/classification_adapters.py`, `backend/workbench/predictive_research/classification_metrics.py`, `backend/workbench/predictive_research/classification_protocol.py`, `backend/workbench/predictive_research/classification_explanations.py`, `backend/workbench/predictive_research/schema.py`, `backend/workbench/predictive_research/consumer_projection.py`, `backend/workbench/predictive_research/graph_persistence.py`, `backend/workbench/predictive_research/split_kernel.py`, `backend/workbench/predictive_research/preprocessing.py`, `backend/workbench/predictive_research/persistence.py`, `backend/workbench/predictive_research/__init__.py`, `backend/workbench/prediction.py`, `backend/workbench/providers/builtin/classification_ml.json`, `frontend/src/report/ClassificationEvidence.tsx`, `frontend/src/report/ClassificationEvidence.test.tsx`, `tests/predictive_research/test_classification_contracts_v189.py`, `tests/predictive_research/test_classification_protocol_v189.py`, `tests/predictive_research/test_classification_leakage_v189.py`, `tests/predictive_research/test_classification_consumers_v189.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-classification-ml-core.md`, `docs/superpowers/handoff/2026-08-15-v1.8.9-p1-classification-ml-core-handoff.md`
- Allowed paths: `backend/workbench/predictive_research/classification_contracts.py`, `backend/workbench/predictive_research/classification_adapters.py`, `backend/workbench/predictive_research/classification_metrics.py`, `backend/workbench/predictive_research/classification_protocol.py`, `backend/workbench/predictive_research/classification_explanations.py`, `backend/workbench/predictive_research/schema.py`, `backend/workbench/predictive_research/consumer_projection.py`, `backend/workbench/predictive_research/graph_persistence.py`, `backend/workbench/predictive_research/split_kernel.py`, `backend/workbench/predictive_research/preprocessing.py`, `backend/workbench/predictive_research/persistence.py`, `backend/workbench/predictive_research/__init__.py`, `backend/workbench/prediction.py`, `backend/workbench/providers/builtin/classification_ml.json`, `frontend/src/report/ClassificationEvidence.tsx`, `frontend/src/report/ClassificationEvidence.test.tsx`, `tests/predictive_research/test_classification_contracts_v189.py`, `tests/predictive_research/test_classification_protocol_v189.py`, `tests/predictive_research/test_classification_leakage_v189.py`, `tests/predictive_research/test_classification_consumers_v189.py`, `docs/superpowers/objectives/2026-08-15-v1.8.9-p1-classification-ml-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-classification-ml-core.md`, `docs/superpowers/handoff/2026-08-15-v1.8.9-p1-classification-ml-core-handoff.md`
- Protected paths: `backend/workbench/contracts`, `backend/workbench/agent`, `backend/workbench/evidence`, `backend/workbench/providers/builtin/contract_fixture.json`, `frontend/src/report/ReportView.tsx`, `frontend/src/workbench/registry/sectionRegistry.ts`, `backend/workbench/data_profile.py`, `backend/workbench/data_operation_manifest.py`, `backend/workbench/filter_ast.py`, `backend/workbench/data_operations.py`, `backend/workbench/metadata.py`, `backend/workbench/http/data_operation_routes.py`, `backend/workbench/data_context_egress.py`, `backend/workbench/providers/builtin/data_consumer.json`, `frontend/src/lineage/dataOperationManifest.ts`, `frontend/src/lineage/dataOperations.ts`, `frontend/src/lineage/detail/sections/DataOperationsSection.tsx`, `frontend/src/lineage/detail/sections/DataOperationsSection.test.tsx`, `tests/test_v189_data_profile.py`, `tests/test_v189_data_operation_manifest.py`, `tests/test_v189_context_egress.py`, `tests/test_v189_filter_ast.py`, `tests/test_data_operation_routes.py`, `tests/contracts/test_v189_contract_lock.py`, `docs/superpowers/objectives/2026-08-15-v1.8.9-p1-data-consumer-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-data-consumer-core.md`, `docs/superpowers/handoff/2026-08-15-v1.8.9-p1-data-consumer-core-handoff.md`, `docs/superpowers/objectives/2026-08-15-v1.8.9-consumer-projection-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-consumer-projection-core.md`, `.agent/devlines/v1-8-9-p1-data-consumer-core`, `scripts/gate.sh`
- Dependencies: `v1-8-9-contract-lock`, `v1-8-9-p0-workflow-truth-core`, `v1-8-9-p0-evidence-core`, `v1-8-9-p0-agent-compiler-core`
- Tests: `cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/predictive_research/test_classification_contracts_v189.py ../tests/predictive_research/test_classification_protocol_v189.py ../tests/predictive_research/test_classification_leakage_v189.py ../tests/predictive_research/test_classification_consumers_v189.py -q`, `cd frontend && npm test -- --run src/report/ClassificationEvidence.test.tsx && npm run typecheck`
- Known gates: `Only Logistic Regression and Random Forest are completion adapters; central cutover and browser acceptance are deferred`, `C1 P0 dependency handoffs/retrospectives are absent in this Wave A worktree; C1 compatibility remains NOT VERIFIED`, `Provider benchmark, browser acceptance, full release gate, merge, push and tag are NOT VERIFIED/not performed`

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
