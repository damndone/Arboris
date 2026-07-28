# Frozen Context Pack

Line: `v1-8-4-agent-evidence-loop`
Baseline SHA: `36fce68ba74b1f929931fea7f4e4402438084ef1`

## Objective
v1.8.4 Agent Evidence Loop

Implement the bounded, evidence-backed completion loop for the existing
Workbench Agent. After a user-confirmed typed operation finishes, the Agent
must be able to discover that operation and read only the bounded,
server-selected result tables needed to answer the user's question, with
artifact identifiers and provenance in every response.

The work must also repair the current Notebook inspection-round failure and
the confirmed model.rerun execution path when their existing contracts are
otherwise satisfied. Figure interpretation may use only a server-owned
numeric chart packet or a declared visual packet; it must refuse when neither
is available.

Non-goals: raw-data browsing, arbitrary file access, automatic execution,
network/package installation, a weaker containment fallback, and any
exercise- or dataset-specific behavior.

Acceptance: focused regression tests prove bounded result access,
operation-result discoverability, evidence citations, refusal on unavailable
evidence, a repaired planning round, and a confirmed rerun. A Workbench UI
test must show Agent proposal -> confirmation -> completed operation ->
evidence-backed user answer.

## Boundary
- Affected paths: `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/context_compiler.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/agent/operations.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/http/agent_routes.py`, `frontend/src/notebook`, `tests`, `docs/superpowers/scope-v1.8.4-agent-evidence-loop.txt`
- Allowed paths: `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/context_compiler.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/agent/operations.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/http/agent_routes.py`, `frontend/src/notebook`, `tests/test_agent_context_tools.py`, `tests/test_agent_workflow_integration.py`, `tests/test_agent_proposal_operations.py`, `tests/test_notebook_planning_agent.py`, `tests/test_notebook_routes.py`, `tests/test_agent_arma_garch_proposal.py`, `docs/superpowers/scope-v1.8.4-agent-evidence-loop.txt`
- Protected paths: `.agent/devlines`, `docs/superpowers/specs`, `docs/superpowers/plans`, `scripts/devline_control.py`, `backend/workbench/native_containment`, `backend/workbench/engine/registry.py`
- Dependencies: `v1-8-3-integration-acceptance`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_agent_context_tools.py tests/test_agent_workflow_integration.py tests/test_agent_proposal_operations.py tests/test_notebook_planning_agent.py tests/test_notebook_routes.py`, `cd frontend && npm run typecheck && npm test -- --run`, `browser: Agent proposal -> confirmation -> evidence-backed answer`
- Known gates: `New worktrees require bash scripts/link-shared-deps.sh <absolute-path> before valid gates.`, `Do not pipe tsc output to tail when reading the exit code.`, `No raw-data browsing or unbounded artifact reads; result access is server-bounded and provenance-cited.`, `Managed macOS sandbox-exec may reject containment; preserve fail-closed behavior and do not introduce weaker fallback.`

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
