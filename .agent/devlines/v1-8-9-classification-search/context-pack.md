# Frozen Context Pack

Line: `v1-8-9-classification-search`
Baseline SHA: `afc7649c81eb54ee8adcb89edc6be14fc8378d6f`

## Objective
# Workbench v1.8.9 Classification Search Objective

## Objective

Complete the remaining P1 classification-ML search boundary in the exact
v1.8.9 integration candidate. Replace the declaration-only bounded-search
contract with a typed, deterministic, resource-bounded executor that evaluates
candidate parameter sets using development-only cross-fitted OOF metrics. The
executor must preserve the existing holdout seal, fold-local preprocessing,
model adapter parameter validation, fail-closed behavior, and evidence identity
bindings. It must remain composable so future model families and search
strategies can be added without changing the central workflow contract.

## Required outcomes

1. Unknown and invalid parameters are rejected before fitting.
2. Trial count and declared time/CPU budgets are enforced; a budget breach is
   an explicit unavailable/blocked result, never a partial success presented as
   selected.
3. Each trial records a deterministic parameter identity, OOF metric, status,
   and failure reason when applicable.
4. Selection uses only development OOF results; final holdout remains sealed
   until the single final model is selected.
5. Existing Logistic Regression and Random Forest behavior remains compatible.
6. Tests prove RED/GREEN behavior, deterministic selection, parameter
   validation, budget enforcement, and holdout non-access.

## Exact baseline

- baseline SHA: `afc7649c81eb54ee8adcb89edc6be14fc8378d6f`
- candidate worktree: `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-hardening-integration`

## Boundaries

- affected paths: `backend/workbench/predictive_research/classification_protocol.py`, `backend/workbench/predictive_research/classification_search.py`, `tests/predictive_research/test_classification_search_v189.py`, `tests/test_v189_classification_production.py`
- allowed paths: `backend/workbench/predictive_research/classification_protocol.py`, `backend/workbench/predictive_research/classification_search.py`, `tests/predictive_research/test_classification_search_v189.py`, `tests/test_v189_classification_production.py`
- protected paths: `backend/workbench/agent`, `backend/workbench/evidence`, `backend/workbench/services/results_service.py`, `backend/workbench/http`, `frontend/src`
- tests: focused classification search tests, existing classification protocol/production tests
- known gates: browser/provider/host full gate/release remain NOT VERIFIED

## Boundary
- Affected paths: `backend/workbench/predictive_research/classification_protocol.py`, `backend/workbench/predictive_research/classification_search.py`, `tests/predictive_research/test_classification_search_v189.py`, `tests/test_v189_classification_production.py`
- Allowed paths: `backend/workbench/predictive_research/classification_protocol.py`, `backend/workbench/predictive_research/classification_search.py`, `tests/predictive_research/test_classification_search_v189.py`, `tests/test_v189_classification_production.py`
- Protected paths: `backend/workbench/agent`, `backend/workbench/evidence`, `backend/workbench/services/results_service.py`, `backend/workbench/http`, `frontend/src`
- Dependencies: none
- Tests: `PYTHONPATH=backend:tests .venv/bin/pytest tests/predictive_research/test_classification_search_v189.py tests/predictive_research/test_classification_protocol_v189.py tests/test_v189_classification_production.py -q`
- Known gates: `browser_acceptance_NOT_VERIFIED`, `provider_acceptance_NOT_VERIFIED`, `host_full_gate_NOT_VERIFIED`, `release_NOT_VERIFIED`

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
