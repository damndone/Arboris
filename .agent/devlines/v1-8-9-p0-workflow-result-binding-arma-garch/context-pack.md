# Frozen Context Pack

Line: `v1-8-9-p0-workflow-result-binding-arma-garch`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# Workbench v1.8.9 P0 workflow result-binding objective

## Objective

Close the workflow truth boundary exposed by the real ARMA/GARCH workflow.
The estimation stage must not apply the coefficient-only OLS binding contract
to a model family whose authoritative result is an artifact-backed time-series
packet. Every admitted model family must declare a typed result-binding
strategy, and an undeclared or incomplete strategy must fail closed.

The implementation must remain extensible: adding a model family should add a
validated binding adapter and its contract tests, not modify a fixed sequence
of estimator-specific branches. No coefficient values may be invented merely
to satisfy a legacy binding shape.

## Required outcomes

1. Preserve the existing strict coefficient binding for coefficient-based
   families, including source IDs, input identity, bounded fields, and payload
   digest.
2. Add a typed artifact-backed binding strategy for
   `time_series.arma_garch` that binds the model result to its declared
   artifact references, production child, validation summary, input IDs and
   model identity without manufacturing `coefficients`.
3. Reject an unknown model result shape, missing required artifact reference,
   foreign model identity, malformed child/validation metadata, or an
   undeclared family strategy with `MODEL_RESULT_INVALID` and no persisted
   model-result fallback.
4. Prove the strategy through a direct RED/GREEN contract test and the real
   orchestrator ARMA/GARCH report-admission regression. Existing diagnostics,
   lineage and Report evidence must continue to consume the authoritative
   family result.
5. Keep the change limited to result-binding and its tests. Do not weaken
   server-owned evidence, Report ownership, Agent/Notebook authority,
   statistical estimators, or release gates.

## Acceptance boundary

Focused package tests, the real ARMA/GARCH workflow regression, compileall,
diff check and formal devline verification are required. Browser, external
provider, multi-worker, host identity, full repository gate, merge, push, tag
and release remain explicit follow-up gates.

## Boundary
- Affected paths: `backend/workbench/engine/registry.py`
- Allowed paths: `backend/workbench/engine/stages/estimation.py`, `backend/workbench/engine/result_binding.py`, `backend/workbench/engine/packs/arma_garch/declaration.py`, `backend/workbench/engine/packs/ets/declaration.py`, `backend/workbench/engine/packs/anova/runtime.py`, `backend/workbench/engine/packs/linear_mixed_effects/declaration.py`, `backend/workbench/engine/packs/v186_model_families/runtime.py`, `tests/test_v189_workflow_result_binding.py`, `tests/test_v189_evidence_report_boundary.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-workflow-result-binding-arma-garch-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-workflow-result-binding-arma-garch.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-workflow-result-binding-arma-garch-handoff.md`
- Protected paths: `backend/workbench/evidence`, `backend/workbench/services/results_service.py`, `backend/workbench/report_view_model.py`, `backend/workbench/agent`, `frontend`, `scripts/gate.sh`, `.agent/devlines`
- Dependencies: `v1-8-9-p0-workflow-truth-core`, `v1-8-9-p0-evidence-report-remediation-10`
- Tests: `cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_workflow_result_binding.py -q`, `cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_evidence_report_boundary.py -q -k arma_garch_report_admission_valid_real_workflow_renders_owner_document`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench/engine`, `git diff --check`
- Known gates: `browser-NOT-VERIFIED`, `real-provider-NOT-VERIFIED`, `multi-worker-and-host-identity-NOT-VERIFIED`, `full-repository-gate-NOT-VERIFIED`, `no-merge-push-tag`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_markdown":"# Global Development Rules\n\nGenerated from repeated devline events. Mandatory rules have appeared at least three times.\n\n- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)\n","global_rules_markdown_sha256":"b619424541a214099df16821c0642f4b2ddb9ee498f66cce7dece275b1117fe5","global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"7d2646296aff49c2c92e83e53f6ad44990aec4280746ec5cf7d9f40b3ab87598"}
```

## Mandatory global development rules
# Global Development Rules

Generated from repeated devline events. Mandatory rules have appeared at least three times.

- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)

## Selected historical lessons
### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-5-a5-model-packet-lineage-label (2026-08-01T22:24:00.000Z)

Completed formal devline v1-8-5-a5-model-packet-lineage-label; final_state=COMPLETED; failure_lesson_keys=model-packet-downstream-boundary

### wo-a-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-agent; final_state=CLOSED; failure_lesson_keys=filesystem-persistence-capability-bypass
