# Frozen Context Pack

Line: `v1-8-3-integration-acceptance`
Baseline SHA: `a5cae68720c90a243441a41fe8b86f3343d7b28f`

## Objective
# v1.8.3 capability runtime integration objective

Implement the remaining local, design-scoped v1.8.3 product integration:

1. connect the server-owned capability authority to the production application
   bootstrap and execution gateway without introducing test keys, unsigned
   fallbacks, or a weaker containment fallback;
2. expose the admitted `model.custom` path through the existing Notebook,
   proposal/risk authorization, Draft, Run, Graph, and artifact contracts;
3. run a controlled local fixture through adapter generation and independent
   validation evidence, including the experimental -> verified -> approved
   promotion rules, while keeping author-supplied self-tests non-authoritative;
4. connect dependency bundle assembly and its server-owned build/scan receipt
   to the actual execution gateway handoff, with offline analysis execution.

The implementation must preserve fail-closed behavior when the host cannot
prove native containment. It may make the explicitly authorized local profile
observable as experimental, but it must not claim production admission without
real authority and containment evidence. No host Workbench environment may be
modified by dynamic package installation.

## Boundary
- Affected paths: `backend/workbench/app.py`, `backend/workbench/agent/trace.py`, `backend/workbench/agent/tools.py`, `backend/workbench/agent/operations.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/capability_factory`, `backend/workbench/http/notebook_routes.py`, `frontend/src/notebook`, `frontend/src/lineage/drafts`, `tests`
- Allowed paths: `backend/workbench/app.py`, `backend/workbench/capability_factory`, `backend/workbench/http/notebook_routes.py`, `frontend/src/notebook`, `frontend/src/lineage/drafts`, `tests`
- Protected paths: `.agent/devlines`, `docs/superpowers/specs`, `docs/superpowers/plans`, `scripts/devline_control.py`, `backend/workbench/native_containment`, `backend/workbench/engine/registry.py`
- Dependencies: `v1-8-3-b1-native-containment`, `v1-8-3-cf3b-adapter-validation`, `v1-8-3-cf4-model-custom-integration`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_capability_*.py tests/test_custom_capability_*.py tests/test_notebook_*.py tests/test_pipeline_drafts_*.py`, `cd frontend && npm run typecheck && npm test -- --run`, `bash scripts/gate.sh`
- Known gates: `Managed macOS sandbox-exec may report NATIVE_CONTAINMENT_RESOURCE_LIMIT_UNAVAILABLE; keep unsupported fail-closed and do not substitute a weaker host fallback.`, `New worktrees require bash scripts/link-shared-deps.sh <absolute-path> before valid gates.`, `Do not pipe tsc output to tail when reading the exit code.`, `Dependency fetch/build/analysis must not install packages into the Workbench host and analysis must run offline.`

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

### integration-v1-7-3 (2026-07-20T17:43:14.000Z)

Completed formal devline integration-v1-7-3; final_state=CLOSED; failure_lesson_keys=c1-c2-execution-boundary, cross-boundary-fixture-parity, declared-owner-no-test-shadowing, entrypoint-contract-coverage, runtime-contract-assembly, versioned-result-visible-reader-adapter
