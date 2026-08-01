# Frozen Context Pack

Line: `v1-8-5-project-memory-candidate-scope`
Baseline SHA: `025b918eeca68456106488e1c12869766028d128`

## Objective
# v1.8.5 project-memory candidate scope objective

## Objective

Close the local domain-memory mutation boundary so candidate creation and the
legacy approval endpoint cannot silently operate on the global memory service
or on an unselected project. In the local runtime, candidate creation must be
authorized by the current project's persisted settings, and candidate approval
must use the current project's candidate store. The existing review endpoint
and the setting confirmation lifecycle remain unchanged.

## Contract

- Local candidate creation requires `project_root`, an enabled project library,
  and `candidate_generation_enabled=true`.
- Local candidate approval requires `project_root` and an enabled project
  library, but does not require candidate generation to remain enabled; users
  must still be able to review candidates that were created before generation
  was disabled.
- The server, not request-body preferences or overrides, decides these local
  permissions. Request-body preference fields remain accepted only for the
  non-local compatibility seam.
- Candidate scope must match the server-derived project scope. A request must
  never choose a different scope through its JSON payload.
- No analysis execution, agent execution, automatic approval, or frontend
  behavior is added.

## Verification

- Red tests demonstrate that local create/approve currently bypass the project
  identity and project settings.
- Green tests cover project-scoped create, create denial when generation is
  disabled, approval using the selected project's store, and missing-project
  fail-closed behavior.
- Run only the focused memory-route tests, `git diff --check`, and the frontend
  typecheck if source boundaries remain unchanged. Do not claim browser or full
  gate evidence from this slice.

## Boundaries

Allowed implementation paths are recorded by the formal development-line
manifest. The parent v1.8.5 design, frontend, storage journal format, and
execution/agent routes are protected.

## Boundary
- Affected paths: `backend/workbench/http/memory_routes.py`, `tests/test_domain_memory_routes.py`
- Allowed paths: `backend/workbench/http/memory_routes.py`, `tests/test_domain_memory_routes.py`, `docs/superpowers/specs/2026-08-01-v1.8.5-project-memory-candidate-scope-objective.md`
- Protected paths: `backend/workbench/domain_memory/store.py`, `backend/workbench/domain_memory/local_runtime.py`, `frontend/src`, `docs/superpowers/specs/2026-07-31-v1.8.5-typed-memory-and-model-family-design.md`
- Dependencies: none
- Tests: `pytest -q tests/test_domain_memory_routes.py -k candidate`, `git diff --check`
- Known gates: `browser acceptance is not covered by this slice`, `full gate is not covered by this slice`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-5-a2-memory-settings-management (2026-08-01T12:19:00.000Z)

Completed formal devline v1-8-5-a2-memory-settings-management; final_state=COMPLETED; failure_lesson_keys=memory-library-management-safe-identification, memory-retrieval-storage-failure-is-503, notebook-memory-server-owned-settings, preference-store-reject-symlink-ancestor, preference-write-complete-before-replace, tdd-red-a2-local-preferences-confirmation

### v1-8-5-a1-local-memory-bootstrap (2026-08-01T11:27:52.000Z)

Completed formal devline v1-8-5-a1-local-memory-bootstrap; final_state=COMPLETED; failure_lesson_keys=tdd-red-local-memory-bootstrap

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-5-a3-memory-candidate-review (2026-08-01T19:33:01.000Z)

Completed formal devline v1-8-5-a3-memory-candidate-review; final_state=COMPLETED; failure_lesson_keys=candidate-governance-needs-server-queue-and-settings-owner, candidate-readiness-transition-required

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required
