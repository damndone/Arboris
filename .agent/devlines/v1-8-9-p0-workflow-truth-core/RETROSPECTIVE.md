# Retrospective — v1-8-9-p0-workflow-truth-core

## Goal

# v1.8.9 P0 Workflow Truth Objective  Build typed persisted workflow outputs and family-aware post-estimation on the existing workflow runtime. Preserve stale detection, idempotency, append-only state, Graph lineage and historical produced_dataset reads. Do not add model families, a second workflow runtime, arbitrary code, frontend behavior, or provider authority. Unknown family/operation/output combinations and execution requests without a server-bound admission receipt fail closed. Completion evidence is committed through the locked persistence port, never projected by consumers at read time.  Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749 Branch: workbench-v1.8.9-p0-workflow-truth Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-workflow-truth Formal line: v1-8-9-p0-workflow-truth-core  Required outcomes: - Typed output bindings remain backward-readable from produced_dataset. - Model branches, source commitments, term groups and artifact identities survive resume. - One server-owned admission/evidence-completion port rejects stale, duplicate, cross-scope, client-compiled and receipt-less requests before side effects. - Family-aware post-estimation has explicit bounded registrations and stable fail-closed errors.  Boundaries: no frontend, predictive research, data operations, workflow contracts, Notebook, Agent routes, new model families, provider authority, arbitrary code or release claims. Formal state is managed only by scripts/devline_control.py.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/7 (42.9%; 42.9 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-16T09:37:43.000Z `typed_output_round_trip`; cause_status: `known`; cause: baseline WorkflowStepState persists only the legacy produced_dataset field and drops typed output bindings and lineage on restore; resolution: `open`; lesson: Make typed output and bounded lineage first-class persisted state before wiring resume consumers.

## All errors

- #3 2026-08-16T09:51:40.000Z `retry_admission_reservation`; cause_status: `known`; cause: the first admission implementation left an active record visible after a failed step, so the documented retry path was rejected as a duplicate; resolution: `resolved`; lesson: Append an explicit abort transition and exclude aborted reservations from duplicate admission checks.

## All gaps

- #6 2026-08-16T09:53:39.000Z `shared_acceptance_not_verified`; cause_status: `external`; cause: this lane does not own the shared compiler cutover, browser acceptance, external provider reachability, or release integration; resolution: `open`; lesson: Do not promote lane-local focused evidence into a shared or released acceptance claim.

## All waste

- None recorded.

## Root causes and solutions

- `retry-admission-reservation`: occurrences=1; cause_status: `known`; root cause: the first admission implementation left an active record visible after a failed step, so the documented retry path was rejected as a duplicate; solution: `resolved`
- `shared-gates-not-verified`: occurrences=1; cause_status: `external`; root cause: this lane does not own the shared compiler cutover, browser acceptance, external provider reachability, or release integration; solution: `open`
- `typed-output-persistence`: occurrences=1; cause_status: `known`; root cause: baseline WorkflowStepState persists only the legacy produced_dataset field and drops typed output bindings and lineage on restore; solution: `open`

## Added tests

- `tests/test_v189_workflow_truth.py`
- `tests/test_workflow_resume.py`

## New rules

- `retry-admission-reservation`: line experience occurrence(s)=1
- `shared-gates-not-verified`: line experience occurrence(s)=1
- `typed-output-persistence`: line experience occurrence(s)=1

## Future guidance

- Append an explicit abort transition and exclude aborted reservations from duplicate admission checks.
- Do not promote lane-local focused evidence into a shared or released acceptance claim.
- Keep lane acceptance claims separate from shared, browser, provider, and release gates.
- Make typed output and bounded lineage first-class persisted state before wiring resume consumers.

## Event index

- #1: `88edecb2-9e65-45d7-bd1d-dbcb00135056` | 2026-08-16T09:28:53.746Z | STATE_CHANGE/line_started | incident=`2ab8e635-7c4f-4066-9707-434269899ea7` | lesson_key=`frozen-context-before-start` | event_sha256=`41585faadab673216ec6729a1e6f2623fc7a2ea55ab875d68ec028b8f69e72e4`
- #2: `665efe98-4200-4a77-8474-03f2d924fb28` | 2026-08-16T09:37:43.000Z | FAILURE/typed_output_round_trip | incident=`2f6dc2cf-e4de-4f62-a8cd-1d68e8065ae1` | lesson_key=`typed-output-persistence` | event_sha256=`de21b088d85ee79ebb6a7ff10b45c527858cfca2cb6d503de96bc0e6a58349d3`
- #3: `3fda1e83-9513-4aa5-a1c4-3d21a663f8e1` | 2026-08-16T09:51:40.000Z | ERROR/retry_admission_reservation | incident=`d1d0d3c9-ecc8-4c25-bd36-95553619fa20` | lesson_key=`retry-admission-reservation` | event_sha256=`3c979d3fb3cda1eea494452ab2b3f4894f9e6f288c9600dd3069899ea0535837`
- #4: `9d3e0121-b21a-4f43-8e41-8da417e51848` | 2026-08-16T09:53:39.000Z | REVIEW/spec_quality_self_review | incident=`9077b16d-0f58-4e5c-9379-19de0ab45ae9` | lesson_key=`spec-quality-self-review` | event_sha256=`40ee14e5d05c4fc0b2bcbd71f434f5db33306c23865676854004b2f75a55e7aa`
- #5: `a8fa8c30-fd42-4247-baf6-425d162746d6` | 2026-08-16T09:53:39.000Z | GATE/focused_workflow_truth | incident=`e7d486d2-b587-4c92-9bd6-534047055da4` | lesson_key=`focused-workflow-truth-gate` | event_sha256=`85df422e3e32eb840c70ceb1be837c53c00330ac74c4b1ff7d976a1ff8c142f4`
- #6: `31ad5089-1845-436f-8e1a-15302c7f963c` | 2026-08-16T09:53:39.000Z | GAP/shared_acceptance_not_verified | incident=`446ac88a-7682-4d16-a1b1-b8f654dfee95` | lesson_key=`shared-gates-not-verified` | event_sha256=`50d5b93c0879526e44f379d5372d6327a11138b7a8a45793e235f2bac1f4edb2`
- #7: `ac2c14bc-137a-4d82-8050-b7a7fc35a9d7` | 2026-08-16T09:53:39.000Z | STATE_CHANGE/line_completed | incident=`fd94cc1d-fe63-4727-8cd3-473c2a2286f1` | lesson_key=`formal-lane-completion` | event_sha256=`b126ba3d87c8a3d1bd2f6dca0757da59ac4a4ce638e0c4a8f9aba39171b903c8`
