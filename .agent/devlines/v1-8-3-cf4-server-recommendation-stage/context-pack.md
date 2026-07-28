# Frozen Context Pack

Line: `v1-8-3-cf4-server-recommendation-stage`
Baseline SHA: `4c799aff2e5c0a89eebf8f370371e54d3fd2e6dd`

## Objective
Replace the production Agent-to-Notebook recommendation handoff with a
server-owned feasibility stage. The Agent may supply candidate drafts and
bounded evidence, but the Workbench service must revalidate every candidate,
persist a typed FeasibilityDecision covering the complete cohort, and derive
RecommendationDecisionV11 from that persisted source before constructing any
capability-bound V1.2 option. Ignore Agent blocked_reason as authority. If
multiple candidates are all structurally feasible and no independent
comparison exists, preserve an insufficient_evidence outcome rather than
choosing a winner. Wire the existing Notebook proposal route to this stage;
manual legacy draft behavior remains unchanged and no execution surface is
added.

## Boundary
- Affected paths: `backend/workbench/agent/notebook/service.py`, `backend/workbench/http/notebook_routes.py`, `tests/test_capability_server_recommendation.py`, `tests/test_notebook_routes.py`
- Allowed paths: `backend/workbench/agent/notebook/service.py`, `backend/workbench/http/notebook_routes.py`, `tests/test_capability_server_recommendation.py`, `tests/test_notebook_routes.py`
- Protected paths: `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/agent/notebook/store.py`, `backend/workbench/contracts/agent/notebook_option.py`, `backend/workbench/capability_factory/notebook_catalog.py`, `backend/workbench/app.py`, `frontend/src/notebook/NotebookSurface.tsx`, `frontend/src/notebook/notebook.css`
- Dependencies: none
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_capability_server_recommendation.py tests/test_notebook_routes.py tests/test_notebook_recommendation.py tests/test_capability_recommendation_guard.py tests/test_no_exercise_specific_naming.py`
- Known gates: `Agent claims do not populate trusted feasibility outcomes; each candidate is revalidated by Workbench service`, `complete candidate cohort is persisted before RecommendationDecisionV11`, `multiple feasible candidates without comparison produce insufficient_evidence; no execution is opened`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
