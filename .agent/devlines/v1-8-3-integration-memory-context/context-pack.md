# Frozen Context Pack

Line: `v1-8-3-integration-memory-context`
Baseline SHA: `3198ad1eba7dd3518a6d2900df716ceafda3c107`

## Objective
Complete the v1.8.3 integration slice in the fixed worktree. Connect the already
implemented domain-memory control plane to the existing Notebook planning context,
Core Agent Trace, and HTTP application assembly. Expose only bounded,
non-authoritative memory hints and explicit opt-in controls; keep memory default-off,
keep iteration separate from retrieval, and do not add any route that executes code,
starts analysis, grants capability admission, or bypasses proposal/risk authorization.
Mount the existing memory control/review router through server-owned state, and add
minimal Notebook presentation for controls, bounded hints, and explicit review queue.
Prove disabled-by-default, hash/freshness separation, ref-only trace payloads,
route mounting, and no-automatic-execution behavior with focused backend/frontend tests.

## Boundary
- Affected paths: `tests/test_agent_trace_decision_chain.py`
- Allowed paths: `tests/test_agent_trace_decision_chain.py`
- Protected paths: `backend/workbench/capability_factory/execution_authorization.py`, `backend/workbench/capability_factory/dispatch.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/domain_memory/store.py`, `backend/workbench/domain_memory/review_service.py`, `frontend/src/notebook/DomainMemoryControls.tsx`, `frontend/src/notebook/DomainMemoryEntryList.tsx`, `frontend/src/notebook/DomainMemoryReviewQueue.tsx`
- Dependencies: none
- Tests: `PYTHONPATH=backend .venv/bin/pytest -q tests/test_memory_integration_context.py tests/test_memory_integration_trace.py tests/test_memory_integration_mount.py`, `cd frontend && npm run test -- --run src/notebook/NotebookSurface.memory.notebook.test.tsx src/notebook/NotebookRouteView.memory.notebook.test.tsx`, `cd frontend && npx tsc --noEmit`
- Known gates: `memory use is default-off and never changes freshness_dependency_fingerprint`, `Core Trace accepts only versioned ref-only domain-memory payloads`, `macOS native containment remains host-dependent and is not claimed by this line`, `no automatic execution surface is added; proposal/risk authorization remains required`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### integration-v1-7-3 (2026-07-20T17:43:14.000Z)

Completed formal devline integration-v1-7-3; final_state=CLOSED; failure_lesson_keys=c1-c2-execution-boundary, cross-boundary-fixture-parity, declared-owner-no-test-shadowing, entrypoint-contract-coverage, runtime-contract-assembly, versioned-result-visible-reader-adapter
