# Frozen Context Pack

Line: `v1-8-5-a3-candidate-review-admission`
Baseline SHA: `f3b5a15858855dfeb64aa18d6a6e3df2ea11a4d5`

## Objective
# v1.8.5 A3 — Candidate Review Admission Objective

Parent scope authority: `2026-07-31-v1.8.5-typed-memory-and-model-family-design.md`.
This is one narrow completion slice, not a new version plan.

## Objective

When a user has explicitly enabled bounded candidate generation and the
curator accepts a de-identified `AcceptedAnalysisSummary`, the persisted
candidate must enter `needs_review` directly. It must then be actionable by
the existing explicit review API and Settings queue. It must never become an
approved memory, modify a Draft, run analysis, or acquire any new authority.

## Scope

- Change only the curator's initial candidate status so its idempotent first
  write is reviewable.
- Preserve the store's existing `proposed -> needs_review` transition for
  other controlled producers and preserve all stale-revision checks.
- Add red-first regressions proving: curator output is reviewable; a visible
  review endpoint can approve/reject it without an out-of-band test
  transition; disabled iteration emits nothing; repeated generation is
  idempotent; candidate review never exposes execution.

## Explicit non-scope

- No new automatic candidate source, LLM summarizer, analysis hook, memory
  target, browser redesign, or authorization surface.
- No change to candidate-generation preferences, approval semantics, runtime
  retrieval, default application, provenance, or model execution.

## Evidence

Run the focused curator/review/local-runtime tests, naming gate, and relevant
frontend queue test; record the red failure and final verification through the
formal development-line CLI. Browser evidence, if obtained, is review-queue
visibility only and is distinct from analysis execution.

## Boundary
- Affected paths: `backend/workbench/domain_memory/curator_runtime.py`, `tests/test_memory_curator_containment.py`, `tests/test_memory_review_routes.py`, `tests/test_memory_review_service.py`, `docs/superpowers/specs/2026-08-01-v1.8.5-a3-candidate-review-admission-objective.md`
- Allowed paths: `backend/workbench/domain_memory/curator_runtime.py`, `tests/test_memory_curator_containment.py`, `tests/test_memory_review_routes.py`, `tests/test_memory_review_service.py`, `docs/superpowers/specs/2026-08-01-v1.8.5-a3-candidate-review-admission-objective.md`
- Protected paths: `docs/superpowers/specs/2026-07-31-v1.8.5-typed-memory-and-model-family-design.md`, `backend/workbench/domain_memory/candidate_store.py`, `backend/workbench/domain_memory/review_service.py`, `backend/workbench/http/memory_routes.py`, `frontend/src/notebook/DomainMemoryReviewQueue.tsx`, `.agent/development/global_rules.md`
- Dependencies: `v1-8-5-a3-memory-candidate-review`, `v1-8-5-b3-recipe-default-materialization`
- Tests: `tests/test_memory_curator_containment.py`, `tests/test_memory_review_routes.py`, `tests/test_no_exercise_specific_naming.py`, `frontend/src/notebook/DomainMemoryReviewQueue.notebook.test.tsx`
- Known gates: `Use LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 under the Chinese repository path.`, `Use formal FMS event enums only; append material red, review, and gate events through this CLI.`, `Browser review-queue evidence is distinct from analysis execution and provider evidence.`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-5-a2-memory-settings-management (2026-08-01T12:19:00.000Z)

Completed formal devline v1-8-5-a2-memory-settings-management; final_state=COMPLETED; failure_lesson_keys=memory-library-management-safe-identification, memory-retrieval-storage-failure-is-503, notebook-memory-server-owned-settings, preference-store-reject-symlink-ancestor, preference-write-complete-before-replace, tdd-red-a2-local-preferences-confirmation

### v1-8-3-document-authority-consolidation (2026-07-26T03:30:00.000Z)

Completed formal devline v1-8-3-document-authority-consolidation; final_state=COMPLETED; failure_lesson_keys=none
