# Retrospective — v1-8-9-p0-evidence-core

## Goal

# v1.8.9 P0 Evidence Core Objective  Build the package-local evidence registry and projection kernel against the locked EvidenceEnvelopeV1 contract. Preserve family semantics and existing validators. Do not modify workflow runtime, services, Agent, Notebook, Report, frontend or consumer coverage; never infer missing facts, trust loose files, or report unavailable/blocked evidence as success.  Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749 Branch: workbench-v1.8.9-p0-evidence-core Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-evidence-core Formal line: v1-8-9-p0-evidence-core  Required outcomes: - Strict facade, registry, projection and persistence preserve EvidenceEnvelopeV1 semantics. - Missing, corrupt, unavailable, blocked, tampered and cross-scope evidence fail closed. - Artifact identity and content hash are verified before projection. - Mutation, replay and consumer-side guessing are covered by focused tests.  Boundaries: no workflow runtime, results service, Agent, Notebook, Report, frontend, classification or data-consumer changes; no loose-file trust, dynamic imports, network execution or release claims. Formal state is managed only by scripts/devline_control.py.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/6 (33.3%; 33.3 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-16T09:45:00.000Z `tdd_red_missing_evidence_package`; cause_status: `known`; cause: The focused P0 evidence-envelope test was intentionally run before implementation and collection failed because workbench.evidence.contracts does not exist yet.; resolution: `open`; lesson: Keep the evidence facade absent until the focused RED test is observed, then implement only the smallest package-local surface needed to turn the test green.
- #3 2026-08-16T09:49:00.000Z `canonical_float_roundtrip_regression`; cause_status: `known`; cause: The first implementation run had 11 focused failures because canonical JSON folds typed float slots such as degrees_of_freedom to integers before the locked C0 decoder reads them; a second test failure exposed the same issue while loading persisted packets.; resolution: `resolved`; lesson: Canonical content hashing must keep wire bytes canonical while re-typing C0 float-only fields before strict decoding.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `evidence-canonical-float-roundtrip`: occurrences=1; cause_status: `known`; root cause: The first implementation run had 11 focused failures because canonical JSON folds typed float slots such as degrees_of_freedom to integers before the locked C0 decoder reads them; a second test failure exposed the same issue while loading persisted packets.; solution: `resolved`
- `evidence-core-tdd-red-before-implementation`: occurrences=1; cause_status: `known`; root cause: The focused P0 evidence-envelope test was intentionally run before implementation and collection failed because workbench.evidence.contracts does not exist yet.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `evidence-canonical-float-roundtrip`: line experience occurrence(s)=1
- `evidence-core-tdd-red-before-implementation`: line experience occurrence(s)=1

## Future guidance

- Canonical content hashing must keep wire bytes canonical while re-typing C0 float-only fields before strict decoding.
- Keep evidence projection read-only and provenance-preserving; treat focused green, integration, browser, and release evidence as separate gates.
- Keep the evidence facade absent until the focused RED test is observed, then implement only the smallest package-local surface needed to turn the test green.

## Event index

- #1: `506f6f53-4530-4f6a-a246-aa63e0f72065` | 2026-08-16T09:28:53.751Z | STATE_CHANGE/line_started | incident=`9f8442bb-de5e-4d93-a16e-ebea37362a5f` | lesson_key=`frozen-context-before-start` | event_sha256=`c60d83d83a53acfe3024cfbc3512a6c4af9bad2692cb6b04047bb32ddc832ecb`
- #2: `00000000-0000-4000-8000-000000000001` | 2026-08-16T09:45:00.000Z | FAILURE/tdd_red_missing_evidence_package | incident=`00000000-0000-4000-8000-000000000002` | lesson_key=`evidence-core-tdd-red-before-implementation` | event_sha256=`55912fa09bd3d69e75bf83fcc881a0971f159b6b0a905eb2c2d6a649d306e138`
- #3: `00000000-0000-4000-8000-000000000003` | 2026-08-16T09:49:00.000Z | FAILURE/canonical_float_roundtrip_regression | incident=`00000000-0000-4000-8000-000000000004` | lesson_key=`evidence-canonical-float-roundtrip` | event_sha256=`cb69c87597967fd347f01e9cab17755e69752bd2927c9fca7072c75a129abde5`
- #4: `00000000-0000-4000-8000-000000000005` | 2026-08-16T09:50:00.000Z | GATE/provider_catalog_contract_lock_regression | incident=`00000000-0000-4000-8000-000000000006` | lesson_key=`provider-catalog-regression-boundary` | event_sha256=`3dc2c0596962404947b1537f7e580dee032d471e4ecb354fbbc06f1fbc1ebeac`
- #5: `00000000-0000-4000-8000-000000000007` | 2026-08-16T09:51:00.000Z | REVIEW/spec_quality_self_review | incident=`00000000-0000-4000-8000-000000000008` | lesson_key=`evidence-core-spec-quality-review` | event_sha256=`5144703740c9a1959243e8ff87e8e07fb068d03e412f127e0ef8ab3d2db2036e`
- #6: `00000000-0000-4000-8000-000000000009` | 2026-08-16T09:52:00.000Z | STATE_CHANGE/line_completed_with_known_gates | incident=`00000000-0000-4000-8000-000000000010` | lesson_key=`evidence-core-completed-with-known-gates` | event_sha256=`723a8ffcd02b5a7d5bd1630eed34b798bfd596f1065abfb06cff9eed31ac2ce0`
