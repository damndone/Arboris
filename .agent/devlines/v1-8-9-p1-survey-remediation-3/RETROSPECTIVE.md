# Retrospective — v1-8-9-p1-survey-remediation-3

## Goal

# Workbench v1.8.9 Survey remediation-3 objective  ## Objective  Close the independent code-quality review blockers against remediation-2/doc tip 9328c3f3c1e96845042be735a3ecd789d0ea1496 without changing root, other worktrees, completed Survey formal lines, or the Survey statistical engine. Make Agent-facing low-level projections closed typed schemas and make Notebook receipt projection use an explicit declared allowlist.  ## Required behavior  - _bounded_persisted_model_facts, _bounded_regression_table, and   _public_requested_model_coefficients emit a field only when its source key   exists and its bounded validator returns a valid typed value. Missing source   fields disappear; no synthetic None, [], empty nested dictionaries, or empty   placeholder cells are emitted. Invalid declared fields fail closed with   typed status/reason where the projection contract requires a result. - Pure-function probes and real Agent workflow probes cover sparse valid   packets, invalid declared metadata, missing optional fields, and preservation   of typed Survey provenance/design/replicate/coefficient metadata. - _public_operation_artifact_result and committed Notebook receipt reads use an   explicit typed allowlist per declared artifact family. Server-owned   provenance, Survey design/replicate fields, coefficients, and existing   declared statistical fields survive bounded validation. raw_rows and unknown   extras never enter the Agent packet or LLM context; invalid declared packets   are typed unavailable or omit only the invalid optional field. - Preserve Survey falsey/fail-closed semantics, the shared   OLS/Logit/Probit/Poisson variance engine, ordinary/replicate weights,   exposure/FPC behavior, Report projection, and Notebook receipt boundaries. - Record the remediation-2 handoff digest mismatch without editing its old   events. The new line must have state_chain_mismatch=0; freeze the final   handoff before the final CLI state event, make that event reference the   exact handoff digest, and perform no post-closeout doc-only commit. Owned   unresolved findings must be 0.  ## Scope  Only these product/test/document paths are in scope:  - backend/workbench/agent/context_tools.py - tests/test_agent_context_tools.py - tests/test_agent_reads_v187_results.py - docs/superpowers/objectives/2026-08-20-v1.8.9-p1-survey-remediation-3-objective.md - docs/superpowers/plans/2026-08-20-survey-remediation-3.md - docs/superpowers/handoff/2026-08-20-v1.8.9-p1-survey-remediation-3-handoff.md  Do not modify root files, other worktrees, the completed v1-8-9-p1-survey-remediation-2 events/Context Pack, any older Survey line, backend/workbench/survey, backend/workbench/report_view_model.py, central integration, browser/provider/host paths, or release machinery.  ## Baseline and gates  - Exact baseline: 9328c3f3c1e96845042be735a3ecd789d0ea1496 - Dependency: v1-8-9-p1-survey-remediation-2 - The old remediation-2 final event records handoff digest   ee3cf0551255e0d15567adf5ed210d238d757ec13826e2cfc8834614e02f8760;   the later doc-only EOF commit changed that handoff without changing old   events. This historical digest mismatch is a known GAP and must be   recorded, not repaired in place. - Central admitted Notebook/Report, browser, provider, host, full-gate, and   release/merge/tag/push acceptance remain NOT VERIFIED. - Known foreign-owner Agent fixtures and admitted Report receipt failures   remain outside this line.

## Final status

COMPLETED

## Metrics

- Failure frequency: 6/21 (28.6%; 28.6 per 100 events)
- Repeat rate: 0/6 (0.0%)
- Recurrence rate: 0/6 (0.0%)
- MTTR: median=1142000 ms (sample=6; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/8 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #4 2026-08-20T03:16:00.000Z `closed_projection_red`; cause_status: `known`; cause: The new pure probes reproduce the review blockers: sparse model facts emit absent None fields, coefficient projections reinsert invalid numeric None placeholders, and Notebook artifact projection forwards unknown nested fields through the generic bounded recursion.; resolution: `open`; lesson: Run sparse and invalid declared probes before touching the shared Agent projection seam.
- #9 2026-08-20T03:30:00.000Z `nested_typed_allowlist_red`; cause_status: `known`; cause: The added P7 nested coefficient-estimands probe exposed one remaining typed allowlist gap, and the empty declared label probe exposed that the shared bounded label helper still treated an empty string as valid.; resolution: `accepted`; lesson: Exercise nested typed families and falsey declared fields before declaring a closed projection green.

## All errors

- None recorded.

## All gaps

- #3 2026-08-20T03:10:01.000Z `remediation_2_handoff_digest_mismatch`; cause_status: `known`; cause: The remediation-2 closing event records the handoff digest before the later doc-only EOF normalization commit; the current handoff digest differs while the old event stream remains intentionally unchanged.; resolution: `accepted`; lesson: Freeze the handoff before the formal closing event and do not make a post-closeout documentation-only commit.
- #10 2026-08-20T03:42:00.000Z `agent_context_foreign_owner_boundary`; cause_status: `known`; cause: The full Agent context suite retains eleven failures in pre-existing foreign-owner or synthetic fixture paths outside the survey remediation-3 ownership boundary.; resolution: `accepted`; lesson: Do not expand a low-level projection repair into unrelated foreign-owner fixture admission behavior.
- #11 2026-08-20T03:42:01.000Z `admitted_report_boundary_not_verified`; cause_status: `known`; cause: The selected Report view/export boundaries passed, but the broader admitted central Report/Notebook cutover was not executed in this remediation line.; resolution: `accepted`; lesson: Keep package-local projection evidence separate from admitted central integration evidence.
- #12 2026-08-20T03:42:02.000Z `central_external_release_boundaries_not_verified`; cause_status: `known`; cause: This line verifies owned pure/Agent/Notebook/Report and Survey regression seams only; central integration, browser acceptance, external provider, host, full gate, release, merge, tag, and push were not performed.; resolution: `accepted`; lesson: State the real verification boundary instead of promoting package-local green evidence to release readiness.

## All waste

- None recorded.

## Root causes and solutions

- `admitted-central-boundary`: occurrences=1; cause_status: `known`; root cause: The selected Report view/export boundaries passed, but the broader admitted central Report/Notebook cutover was not executed in this remediation line.; solution: `accepted`
- `central-external-release-boundary`: occurrences=1; cause_status: `known`; root cause: This line verifies owned pure/Agent/Notebook/Report and Survey regression seams only; central integration, browser acceptance, external provider, host, full gate, release, merge, tag, and push were not performed.; solution: `accepted`
- `closed-projection-red-before-fix`: occurrences=1; cause_status: `known`; root cause: The new pure probes reproduce the review blockers: sparse model facts emit absent None fields, coefficient projections reinsert invalid numeric None placeholders, and Notebook artifact projection forwards unknown nested fields through the generic bounded recursion.; solution: `open`
- `foreign-owner-suite-boundary`: occurrences=1; cause_status: `known`; root cause: The full Agent context suite retains eleven failures in pre-existing foreign-owner or synthetic fixture paths outside the survey remediation-3 ownership boundary.; solution: `accepted`
- `handoff-digest-freeze-order`: occurrences=1; cause_status: `known`; root cause: The remediation-2 closing event records the handoff digest before the later doc-only EOF normalization commit; the current handoff digest differs while the old event stream remains intentionally unchanged.; solution: `accepted`
- `nested-allowlist-and-empty-label-red`: occurrences=1; cause_status: `known`; root cause: The added P7 nested coefficient-estimands probe exposed one remaining typed allowlist gap, and the empty declared label probe exposed that the shared bounded label helper still treated an empty string as valid.; solution: `accepted`

## Added tests

- No test evidence recorded.

## New rules

- `admitted-central-boundary`: line experience occurrence(s)=1
- `central-external-release-boundary`: line experience occurrence(s)=1
- `closed-projection-red-before-fix`: line experience occurrence(s)=1
- `foreign-owner-suite-boundary`: line experience occurrence(s)=1
- `handoff-digest-freeze-order`: line experience occurrence(s)=1
- `nested-allowlist-and-empty-label-red`: line experience occurrence(s)=1

## Future guidance

- Do not expand a low-level projection repair into unrelated foreign-owner fixture admission behavior.
- Exercise nested typed families and falsey declared fields before declaring a closed projection green.
- Freeze the handoff before the formal closing event and do not make a post-closeout documentation-only commit.
- Keep package-local projection evidence separate from admitted central integration evidence.
- Run sparse and invalid declared probes before touching the shared Agent projection seam.
- State the real verification boundary instead of promoting package-local green evidence to release readiness.
- Treat source presence and typed validation as separate admission conditions at every public projection seam.

## Event index

- #1: `06819495-df0c-4cf0-9937-c89eda383223` | 2026-08-20T03:03:34.181Z | STATE_CHANGE/line_started | incident=`3b2f11ef-96d7-4cff-b3b0-fefc687eef59` | lesson_key=`frozen-context-before-start` | event_sha256=`34a4a0d2f62dd602c755185e14aa54c0166056de0d5d0c8e1c4e7d1d7a9fba97`
- #2: `f1e2d3c4-b5a6-4789-8abc-def012345678` | 2026-08-20T03:10:00.000Z | REVIEW/code_quality_not_compliant | incident=`e2d3c4b5-a6f7-4890-bcde-f0123456789a` | lesson_key=`closed-projection-review-blocker` | event_sha256=`93cc1c4087491672a8a39a283e4766b68db833d1d2ad17be82b337ac563f29cd`
- #3: `a4b5c6d7-e8f9-4012-9345-6789abcdef01` | 2026-08-20T03:10:01.000Z | GAP/remediation_2_handoff_digest_mismatch | incident=`b5c6d7e8-f901-4234-a567-89abcdef0123` | lesson_key=`handoff-digest-freeze-order` | event_sha256=`a5ba69f4db8f73e08c7cbbb055f182372430876cf4851d0be93f85ed16d93416`
- #4: `c6d7e8f9-0123-4456-879a-bcdef0123456` | 2026-08-20T03:16:00.000Z | FAILURE/closed_projection_red | incident=`d7e8f901-2345-4678-9abc-def012345678` | lesson_key=`closed-projection-red-before-fix` | event_sha256=`3d457322a3433d8609f6260b4c22f346844d7ab0279d30961da978e22da018c0`
- #5: `e8f90123-4567-489a-bcde-f0123456789a` | 2026-08-20T03:16:01.000Z | STATE_CHANGE/red_probes_observed | incident=`f9012345-6789-4abc-def0-123456789abc` | lesson_key=`remediation-3-red-state-continuity` | event_sha256=`9ee10decf1e97e59ad01098b29719226bc90b3fcc4758d3dc182d693257ae76a`
- #6: `01234567-89ab-4cde-f012-3456789abcde` | 2026-08-20T03:24:00.000Z | GATE/focused_closed_projection_green | incident=`12345678-9abc-4def-0123-456789abcdef` | lesson_key=`focused-closed-projection-green` | event_sha256=`822485b930025508ceca86ad9be4034d3f7f3f7ca97849feb82be589c3e81d16`
- #7: `23456789-abcd-4ef0-1234-56789abcdef0` | 2026-08-20T03:24:01.000Z | STATE_CHANGE/focused_projection_green | incident=`3456789a-bcde-4f01-2345-6789abcdef01` | lesson_key=`remediation-3-green-state-continuity` | event_sha256=`6a47044334ad6f4166b2d9bcd44d0816661feec6ef1fc09f9386cc5afdba636a`
- #8: `56789abc-def0-4123-4567-89abcdef0123` | 2026-08-20T03:30:01.000Z | STATE_CHANGE/nested_allowlist_red_observed | incident=`789abcde-f012-4345-6789-abcdef012345` | lesson_key=`nested-allowlist-state-continuity` | event_sha256=`58727be739e28f8de34bfe0f5d4ae87ee93cf38090425f6d2610dc14a9ec30d7`
- #9: `89abcdef-0123-4456-789a-bcdef0123456` | 2026-08-20T03:30:00.000Z | FAILURE/nested_typed_allowlist_red | incident=`9abcdef0-1234-4567-89ab-cdef01234567` | lesson_key=`nested-allowlist-and-empty-label-red` | event_sha256=`979e6115957a6db68d40201588dee2009e4613c4edabf6892e7c9f2ea38aa56a`
- #10: `abcdef01-2345-4678-9abc-def012345678` | 2026-08-20T03:42:00.000Z | GAP/agent_context_foreign_owner_boundary | incident=`bcdef012-3456-4789-abcd-ef0123456789` | lesson_key=`foreign-owner-suite-boundary` | event_sha256=`d4dd6d96b000f1519e301b4393cb08061e8fd6f1625a111b4d15924b83ee345d`
- #11: `bcdef012-3456-4789-abcd-ef0123456789` | 2026-08-20T03:42:01.000Z | GAP/admitted_report_boundary_not_verified | incident=`cdef0123-4567-489a-bcde-f0123456789a` | lesson_key=`admitted-central-boundary` | event_sha256=`8dea538efd2e6b4f1df300fc890e6262780d566740c4b516d690a2d303cfec61`
- #12: `cdef0123-4567-489a-bcde-f0123456789a` | 2026-08-20T03:42:02.000Z | GAP/central_external_release_boundaries_not_verified | incident=`def01234-5678-49ab-cdef-0123456789ab` | lesson_key=`central-external-release-boundary` | event_sha256=`3ec992d21bee6061cdaaddafcbe1b16694b1a24f48dcbd03034fd288e0416122`
- #13: `def01234-5678-49ab-cdef-0123456789ab` | 2026-08-20T03:42:03.000Z | GATE/owned_regression_green | incident=`ef012345-6789-4abc-def0-123456789abc` | lesson_key=`owned-regression-green` | event_sha256=`7e9cd45a6dec3f66c76b2378e2dd0c4007f88541edfae3edc178db72da288693`
- #14: `ef012345-6789-4abc-def0-123456789abc` | 2026-08-20T03:42:04.000Z | STATE_CHANGE/owned_regression_green_state | incident=`f0123456-789a-4bcd-ef01-23456789abcd` | lesson_key=`regression-green-state-continuity` | event_sha256=`14bd51b94cf9340b5254a581b1ebe59ad25921b1f4e731e781bb7e21fda9c155`
- #15: `f1234567-89ab-4cde-f012-3456789abcde` | 2026-08-20T03:50:00.000Z | STATE_CHANGE/formal_handoff_closed | incident=`01234567-89ab-4cde-f012-3456789abcde` | lesson_key=`exact-tip-handoff-closeout` | event_sha256=`3c1e02637a69fce77cafaab2e37412d1eb3c34d12524f3a18a3dcd8d7de26ded`
- #16: `12345678-9abc-4def-0123-456789abcdef` | 2026-08-20T03:55:00.000Z | GATE/closed_projection_red_resolved | incident=`d7e8f901-2345-4678-9abc-def012345678` | lesson_key=`closed-projection-red-before-fix` | event_sha256=`1d697776e69b3dde676c1ea44a35b01db458634c09c053944c0e54e3f3f4be06`
- #17: `3456789a-bcde-4f01-2345-6789abcdef01` | 2026-08-20T03:55:02.000Z | GATE/remediation_2_handoff_digest_gap_resolved | incident=`b5c6d7e8-f901-4234-a567-89abcdef0123` | lesson_key=`handoff-digest-freeze-order` | event_sha256=`f96986625e903a8c53cbe4e760c584620e52474e3c540e6d974a84232244c1b0`
- #18: `456789ab-cdef-4012-3456-789abcdef012` | 2026-08-20T03:55:03.000Z | GATE/foreign_owner_boundary_recorded | incident=`bcdef012-3456-4789-abcd-ef0123456789` | lesson_key=`foreign-owner-suite-boundary` | event_sha256=`dcc5be84302ee0cc2a91012f4838322b63abd9fa1e2546dd788402d6748c0e28`
- #19: `6789abcd-ef01-4234-5678-9abcdef01234` | 2026-08-20T03:55:05.000Z | GATE/central_release_boundary_recorded | incident=`def01234-5678-49ab-cdef-0123456789ab` | lesson_key=`central-external-release-boundary` | event_sha256=`b11949b3558a6a10308d8eb9427a75335d984549a6dde29a12889596065b6400`
- #20: `789abcde-f012-4345-6789-abcdef012345` | 2026-08-20T03:55:01.000Z | GATE/nested_typed_allowlist_red_resolved | incident=`9abcdef0-1234-4567-89ab-cdef01234567` | lesson_key=`nested-allowlist-and-empty-label-red` | event_sha256=`8f5e486ddd7bfef82b3b51b2d18e06408257d1f6d12b0e9046cdd14f5fc2d14b`
- #21: `abcdef01-2345-4678-9abc-def012345679` | 2026-08-20T03:55:04.000Z | GATE/admitted_boundary_recorded | incident=`cdef0123-4567-489a-bcde-f0123456789a` | lesson_key=`admitted-central-boundary` | event_sha256=`d5608a462c96ca3266e2b314ff3f99facff487794d6b62b9b944feed0bfd3cce`
