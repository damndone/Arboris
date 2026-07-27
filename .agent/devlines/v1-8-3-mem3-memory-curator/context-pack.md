# Frozen Context Pack

Line: `v1-8-3-mem3-memory-curator`
Baseline SHA: `158831a8ce16d3f4c227c0c4aa5c19caa2cbbf9d`

## Objective
Implement MEM3 as a candidate-only curator and explicit governance layer on top of the completed MEM2 contracts. Accept only bounded, de-identified analysis summaries at an explicit review point; enforce independent iteration preference, completeness, policy, scope, and idempotency gates; generate pending candidates only; detect duplicates, supersession, and conflicts without semantic authority; and require explicit user review to approve, reject, stale, archive, revoke, restore, or resolve conflicts. Add crash-recoverable review-job records and unmounted review API/UI adapters. The curator and scheduler must have no raw-data, filesystem-scan, shell, network, dependency, capability-runtime, recommendation, authorization, or dispatch access. Reuse MEM2 stores and contracts, preserve default-off controls, and do not modify shared Agent, Core Trace, app, Notebook mounting, or execution seams.

## Boundary
- Affected paths: `backend/workbench/domain_memory`, `backend/workbench/http/memory_routes.py`, `frontend/src/notebook`, `tests`
- Allowed paths: `backend/workbench/domain_memory/curator_contracts.py`, `backend/workbench/domain_memory/curator_eligibility.py`, `backend/workbench/domain_memory/curator_runtime.py`, `backend/workbench/domain_memory/conflicts.py`, `backend/workbench/domain_memory/review_service.py`, `backend/workbench/domain_memory/review_scheduler.py`, `backend/workbench/domain_memory/candidate_store.py`, `backend/workbench/domain_memory/service.py`, `backend/workbench/domain_memory/store.py`, `backend/workbench/domain_memory/trace_contracts.py`, `backend/workbench/http/memory_routes.py`, `frontend/src/notebook/domainMemoryContracts.ts`, `frontend/src/notebook/domainMemoryApi.ts`, `frontend/src/notebook/DomainMemoryControls.tsx`, `frontend/src/notebook/DomainMemoryEntryList.tsx`, `frontend/src/notebook/DomainMemoryReviewQueue.tsx`, `frontend/src/notebook/DomainMemoryControls.notebook.test.tsx`, `frontend/src/notebook/DomainMemoryReviewQueue.notebook.test.tsx`, `tests/test_memory_curator_contracts.py`, `tests/test_memory_curator_eligibility.py`, `tests/test_memory_curator_containment.py`, `tests/test_memory_candidate_store.py`, `tests/test_memory_conflicts.py`, `tests/test_memory_review_service.py`, `tests/test_memory_review_scheduler.py`, `tests/test_memory_review_routes.py`, `tests/test_memory_review_trace.py`
- Protected paths: `backend/workbench/agent/context_compiler.py`, `backend/workbench/agent/trace.py`, `backend/workbench/app.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/capability_factory/execution_authorization.py`, `backend/workbench/capability_factory/dispatch.py`, `frontend/src/notebook/NotebookSurface.tsx`, `frontend/src/notebook/notebook.css`
- Dependencies: `158831a8ce16d3f4c227c0c4aa5c19caa2cbbf9d`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_memory_curator_contracts.py tests/test_memory_curator_eligibility.py tests/test_memory_curator_containment.py tests/test_memory_candidate_store.py tests/test_memory_conflicts.py tests/test_memory_review_service.py tests/test_memory_review_scheduler.py tests/test_memory_review_routes.py tests/test_memory_review_trace.py tests/test_no_exercise_specific_naming.py`
- Known gates: `Curator consumes only bounded de-identified summaries and emits candidates, never official memory or execution`, `Iteration remains independently default-off; no hidden background writes`, `Review lifecycle uses explicit user decision, CAS, stale/archive/revoke semantics, and conflict records`, `Shared Agent, Core Trace, app, Notebook mounting, capability authority, authorization, and dispatch paths remain protected`, `Native Linux/Darwin canaries are unavailable on this host and are not claimed by this line`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### wo-a-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-agent; final_state=CLOSED; failure_lesson_keys=filesystem-persistence-capability-bypass

### local-contained-execution (2026-07-20T17:44:54.000Z)

Completed formal devline local-contained-execution; final_state=CLOSED; failure_lesson_keys=none

### v173-c2-native-acceptance (2026-07-20T16:55:33.000Z)

Completed formal devline v173-c2-native-acceptance; final_state=CLOSED; failure_lesson_keys=c2-runtime-trust-identity

### wo-a-live-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-live-agent; final_state=CLOSED; failure_lesson_keys=none
