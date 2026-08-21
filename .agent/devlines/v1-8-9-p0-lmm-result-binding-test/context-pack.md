# Frozen Context Pack

Line: `v1-8-9-p0-lmm-result-binding-test`
Baseline SHA: `10f9c8ebd57989b39e3c35f9ecd23f2b8d67abcf`

## Objective
# Workbench v1.8.9 P0 LMM result-binding test contract

Update the LMM execution-admission test double to satisfy the current explicit
result-binding-key contract while preserving the test's assertion that handled
input blocks do not fall back to the generic lifecycle.

Required outcomes:

- the stub handler declares the registered result strategy required by the
  production registry;
- the test reaches its intended LMM input-block branch;
- no production registry or result persistence behavior is changed.

## Boundary
- Affected paths: `tests/engine/test_lmm_execution_admission.py`
- Allowed paths: `tests/engine/test_lmm_execution_admission.py`, `docs/superpowers/objectives/2026-08-21-v1.8.9-p0-lmm-result-binding-test-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-lmm-result-binding-test.md`
- Protected paths: `backend/workbench/engine`, `backend/workbench/agent`, `backend/workbench/evidence`, `frontend`
- Dependencies: none
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest tests/engine/test_lmm_execution_admission.py -q --disable-warnings`
- Known gates: `browser/provider/full host/release remain separate`

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

### v1-8-5-a5-model-packet-lineage-label (2026-08-01T22:24:00.000Z)

Completed formal devline v1-8-5-a5-model-packet-lineage-label; final_state=COMPLETED; failure_lesson_keys=model-packet-downstream-boundary

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### wo-a-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-agent; final_state=CLOSED; failure_lesson_keys=filesystem-persistence-capability-bypass
