# Frozen Context Pack

Line: `v1-8-3-cf4-recommendation-authority-guard`
Baseline SHA: `a53be8e384c1bdc7bd71a31adc4fa151900fcbe2`

## Objective
Close the P1 recommendation authority gap at the Notebook write seam. A
capability-bound option may produce NotebookOptionRevision@1.2 only when its
recommendation is RecommendationDecisionV11 and the service can validate that
decision against a persisted server-owned FeasibilityDecision or
ComparisonDecision. Legacy RecommendationDecision@1.0 must fail closed before
any option, decision, Draft, or materialization write. Preserve the existing
legacy path for unbound options. Add focused regression tests and update only
the affected capability-bound expectations; do not synthesize a server
decision from Agent claims and do not open execution.

## Boundary
- Affected paths: `backend/workbench/agent/notebook/service.py`, `tests/test_capability_recommendation_guard.py`, `tests/test_capability_notebook_binding.py`
- Allowed paths: `backend/workbench/agent/notebook/service.py`, `tests/test_capability_recommendation_guard.py`, `tests/test_capability_notebook_binding.py`
- Protected paths: `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/agent/notebook/store.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/contracts/agent/notebook_option.py`, `backend/workbench/capability_factory/notebook_catalog.py`, `backend/workbench/app.py`, `frontend/src/notebook/NotebookSurface.tsx`, `frontend/src/notebook/notebook.css`
- Dependencies: none
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_capability_recommendation_guard.py tests/test_capability_notebook_binding.py tests/test_notebook_recommendation.py tests/test_no_exercise_specific_naming.py`
- Known gates: `capability-bound V1.2 options require persisted server-owned V1.1 source decision`, `legacy V1.0 recommendation cannot mint a capability-bound V1.2 option`, `guard runs before any option or decision append; unbound legacy options remain compatible`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
