# Frozen Context Pack

Line: `v1-8-3-mem2-domain-memory`
Baseline SHA: `1c735fa231ded18110f1f819f722c7df7addb6a1`

## Objective
Implement MEM2 as a scoped, append-only cross-project domain-memory control plane. Define immutable bounded content revisions, redacted source-access bindings and validity, candidate and approval/current-grant records, independent default-off use/iteration preferences, and deterministic fail-closed retrieval. The package may emit local bounded trace contracts and an unmounted HTTP adapter, but must not modify the shared Context Compiler, Core Trace, application mounting, Notebook mounting, capability ranking/admission, authorization, dependency installation, code execution, or dispatch paths. Memory may provide only current-evidence-checked hints and must never become an authority source or execution trigger. Prove namespace isolation, CAS approval, stale/revoked/deleted/tainted-source exclusion, redaction, boundedness, idempotent append-only persistence, default-off semantics, and no exercise-specific naming.

## Boundary
- Affected paths: `backend/workbench/domain_memory/root_resolver.py`, `frontend/src/notebook/domainMemoryContracts.ts`, `frontend/src/notebook/domainMemoryApi.ts`, `frontend/src/notebook/DomainMemoryControls.tsx`, `frontend/src/notebook/DomainMemoryEntryList.tsx`, `frontend/src/notebook/DomainMemoryControls.notebook.test.tsx`, `frontend/src/notebook/DomainMemoryEntryList.notebook.test.tsx`
- Allowed paths: `backend/workbench/domain_memory/root_resolver.py`, `frontend/src/notebook/domainMemoryContracts.ts`, `frontend/src/notebook/domainMemoryApi.ts`, `frontend/src/notebook/DomainMemoryControls.tsx`, `frontend/src/notebook/DomainMemoryEntryList.tsx`, `frontend/src/notebook/DomainMemoryControls.notebook.test.tsx`, `frontend/src/notebook/DomainMemoryEntryList.notebook.test.tsx`
- Protected paths: `backend/workbench/agent/context_compiler.py`, `backend/workbench/agent/trace.py`, `backend/workbench/app.py`, `backend/workbench/capability_factory/execution_authorization.py`, `backend/workbench/capability_factory/dispatch.py`, `frontend/src/notebook/NotebookSurface.tsx`, `frontend/src/notebook/notebook.css`
- Dependencies: `1c735fa231ded18110f1f819f722c7df7addb6a1`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_domain_memory_contracts.py tests/test_domain_memory_root_resolver.py tests/test_domain_memory_scope.py tests/test_domain_memory_source_access.py tests/test_domain_memory_store.py tests/test_domain_memory_candidate_store.py tests/test_domain_memory_preferences.py tests/test_domain_memory_retrieval.py tests/test_domain_memory_context_injection.py tests/test_domain_memory_routes.py tests/test_domain_memory_trace.py tests/test_no_exercise_specific_naming.py`
- Known gates: `No shared integration seam is modified; route adapter remains unmounted`, `Domain memory use and iteration remain independently default-off`, `Every retrieval rechecks scope, approval, validity, source access, ACL and boundedness`, `Memory cannot alter recommendation, capability admission, authorization, dependency installation, code execution or dispatch`, `Native Linux/Darwin canaries are unavailable on this host and are not claimed by this line`

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
