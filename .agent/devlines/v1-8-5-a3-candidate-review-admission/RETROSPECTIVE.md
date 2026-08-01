# Retrospective — v1-8-5-a3-candidate-review-admission

## Goal

# v1.8.5 A3 — Candidate Review Admission Objective  Parent scope authority: \`2026-07-31-v1.8.5-typed-memory-and-model-family-design.md\`. This is one narrow completion slice, not a new version plan.  ## Objective  When a user has explicitly enabled bounded candidate generation and the curator accepts a de-identified \`AcceptedAnalysisSummary\`, the persisted candidate must enter \`needs_review\` directly. It must then be actionable by the existing explicit review API and Settings queue. It must never become an approved memory, modify a Draft, run analysis, or acquire any new authority.  ## Scope  - Change only the curator's initial candidate status so its idempotent first   write is reviewable. - Preserve the store's existing \`proposed -> needs_review\` transition for   other controlled producers and preserve all stale-revision checks. - Add red-first regressions proving: curator output is reviewable; a visible   review endpoint can approve/reject it without an out-of-band test   transition; disabled iteration emits nothing; repeated generation is   idempotent; candidate review never exposes execution.  ## Explicit non-scope  - No new automatic candidate source, LLM summarizer, analysis hook, memory   target, browser redesign, or authorization surface. - No change to candidate-generation preferences, approval semantics, runtime   retrieval, default application, provenance, or model execution.  ## Evidence  Run the focused curator/review/local-runtime tests, naming gate, and relevant frontend queue test; record the red failure and final verification through the formal development-line CLI. Browser evidence, if obtained, is review-queue visibility only and is distinct from analysis execution.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/8 (12.5%; 12.5 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: median=1066000 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #4 2026-08-01T20:46:05.000Z `tdd_red_curator_candidate_not_reviewable`; cause_status: `known`; cause: CuratorRuntime writes the first candidate revision as proposed, while the existing explicit review service accepts approval only from needs_review.; resolution: `accepted`; lesson: A curator that has passed its bounded eligibility gates must emit a reviewable candidate state; it must not leave a dead-end pending state for the UI.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `curator-output-must-enter-explicit-review-state`: occurrences=1; cause_status: `known`; root cause: CuratorRuntime writes the first candidate revision as proposed, while the existing explicit review service accepts approval only from needs_review.; solution: `accepted`

## Added tests

- `A3 targeted regression and independent review approval`
- `A3 targeted: 37 backend passed; frontend review queue 2 passed; TypeScript passed`
- `pytest tests/test_memory_curator_containment.py tests/test_memory_review_routes.py tests/test_memory_review_service.py -q: 5 failed, 3 passed; all failures assert proposed versus needs_review`
- `pytest tests/test_memory_curator_containment.py::test_curator_upgrades_a_matching_legacy_proposal_to_explicit_review -q: MemoryCandidateStoreConflict candidate revision was reused`

## New rules

- `curator-output-must-enter-explicit-review-state`: line experience occurrence(s)=1

## Future guidance

- A curator that has passed its bounded eligibility gates must emit a reviewable candidate state; it must not leave a dead-end pending state for the UI.
- Lifecycle compatibility must prove both exact legacy progression and rejection of same-id content conflicts.
- When a deterministic append-only candidate lifecycle changes state, test and implement compatible progression for an existing prior-state record.

## Event index

- #1: `5b7846c6-953d-4704-9ea8-b6b332b566a7` | 2026-08-01T20:44:28.740Z | STATE_CHANGE/line_started | incident=`dc9f87ab-7e0d-4275-8477-1e1c346824fe` | lesson_key=`frozen-context-before-start` | event_sha256=`7493a81d04291ae7e7a23b30333a9067fce3fd570a23ff9253f7e767c2cdaff6`
- #2: `9622d527-c4c9-438c-ba49-36d88fad1272` | 2026-08-01T20:45:17.340Z | STATE_CHANGE/context_rescope_required | incident=`5197848f-e888-4329-8ba9-65f65d86fb15` | lesson_key=`context-pack-rescope` | event_sha256=`5a9e33812a477b268dc91231c98509c0b4be07a9ac7245de8d536ce8cf0d2959`
- #3: `f04dfdda-449c-4cf2-a1ad-a3d349802a5c` | 2026-08-01T20:45:17.343Z | STATE_CHANGE/context_rescoped | incident=`c7b0af5d-b4f2-48b2-af4e-04678913a9c6` | lesson_key=`context-pack-rescope` | event_sha256=`28a4564526fa5d28172ccab4e1702726dff7777cf0495172bce5c6ace0691199`
- #4: `b5583c0b-7d61-4c7d-a18e-4cb5ae8b439d` | 2026-08-01T20:46:05.000Z | FAILURE/tdd_red_curator_candidate_not_reviewable | incident=`deed2e65-2c0c-4ce4-a6df-52b6ed913807` | lesson_key=`curator-output-must-enter-explicit-review-state` | event_sha256=`70805c82a197d1a86e476b8932b3409b9ac3edbc9e962d6035a6fee5aabf95ea`
- #5: `5a926c52-d312-49a7-9cf5-555733db5d1f` | 2026-08-01T20:58:48.000Z | REVIEW/a3_legacy_candidate_upgrade_changes_required | incident=`7a61b746-4d51-465c-a091-a777d41ffc72` | lesson_key=`curator-lifecycle-changes-require-persisted-upgrade-compatibility` | event_sha256=`537f58c94ef4ba82ec163ed9e4980959af9238b7df7e543693c32b5893230de7`
- #6: `c4d439af-470c-446c-a6e7-ece2c80a9909` | 2026-08-01T21:03:51.000Z | GATE/a3_candidate_review_admission_gate_passed | incident=`deed2e65-2c0c-4ce4-a6df-52b6ed913807` | lesson_key=`curator-output-must-enter-explicit-review-state` | event_sha256=`d58eb1074f7f3b8d2111ee380e659ebd352d5b98baea7ffd450e9ca8f8b4743f`
- #7: `e11e7b8a-093e-4680-ae67-64dce6d023dc` | 2026-08-01T21:03:51.000Z | REVIEW/a3_legacy_candidate_upgrade_review_approved | incident=`7a61b746-4d51-465c-a091-a777d41ffc72` | lesson_key=`curator-lifecycle-changes-require-persisted-upgrade-compatibility` | event_sha256=`17450b3c8bbd83c726e195a15421febc0bbea1dd246ba146d4c71d388dd0f97b`
- #8: `11c7bd6b-92f1-4ea0-95a5-42f807137e1f` | 2026-08-01T21:03:51.000Z | STATE_CHANGE/a3_candidate_review_admission_completed | incident=`8ae8a8c7-9d85-483f-80f5-73461a02c6d7` | lesson_key=`close-candidate-review-admission-at-verified-boundary` | event_sha256=`1627a0a7cb963f6a8180d11a4a026b3cfeca2d83b52228e3ffb5a286e3b3d981`
