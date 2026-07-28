# Retrospective — v1-8-3-cf3-adapter-validation

## Goal

# v1.8.3 CF3 adapter and validation contract foundation  Implement the first bounded CF3 slice: a generic Adapter contract bound to a CF1 semantic profile and implementation revision, plus validation-case and evidence contracts that distinguish author self-tests from independent oracle evidence. Add an Agent-side proposal binding only if it remains proposal/risk control-plane data. Do not generate, import, execute, or install adapter code; do not access user data, add Agent tools/routes, modify AgentCore, change the custom runtime ABI, or claim statistical validation, model.custom execution, Notebook integration, or capability admission.  The slice must remain generic across algorithms and consumers: every declared operation and consumer slot is explicit, schema and profile digests are bound, validation evidence is append-only and bounded, and E2+ evidence requires an independent oracle reference rather than author-provided expected output.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/7 (42.9%; 42.9 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: median=0 ms (sample=2; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-07-26T14:23:49.000Z `tdd_red_before_modules`; cause_status: `known`; cause: CF3 tests ran before the target modules existed, producing the expected import failures.; resolution: `resolved`; lesson: Write the generic contract tests before adding the CF3 modules.
- #5 2026-07-26T14:36:39.000Z `native_host_sandbox_unavailable`; cause_status: `external`; cause: The macOS host exposes sandbox-exec but rejects sandbox_apply with Operation not permitted; the same test fails on the unchanged CF2 worktree.; resolution: `accepted`; lesson: Treat sandbox_apply refusal as a host capability boundary and preserve fail-closed behavior.

## All errors

- #6 2026-07-26T14:38:11.000Z `event_evidence_digest_correction`; cause_status: `known`; cause: The initial TDD failure event used a placeholder digest instead of the test artifact digest.; resolution: `resolved`; lesson: Verify every event evidence digest before appending the event.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `evidence-digest-verification`: occurrences=1; cause_status: `known`; root cause: The initial TDD failure event used a placeholder digest instead of the test artifact digest.; solution: `resolved`
- `native-containment-host-gate`: occurrences=1; cause_status: `external`; root cause: The macOS host exposes sandbox-exec but rejects sandbox_apply with Operation not permitted; the same test fails on the unchanged CF2 worktree.; solution: `accepted`
- `profile-bound-adapter-contract`: occurrences=1; cause_status: `known`; root cause: CF3 tests ran before the target modules existed, producing the expected import failures.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `evidence-digest-verification`: line experience occurrence(s)=1
- `native-containment-host-gate`: line experience occurrence(s)=1
- `profile-bound-adapter-contract`: line experience occurrence(s)=1

## Future guidance

- Keep executable references as digests and require independent oracle provenance before source eligibility.
- Treat sandbox_apply refusal as a host capability boundary and preserve fail-closed behavior.
- Verify every event evidence digest before appending the event.
- Write the generic contract tests before adding the CF3 modules.

## Event index

- #1: `cc1ed700-e355-4edf-99dd-8346e2ecf02c` | 2026-07-26T14:17:54.219Z | STATE_CHANGE/line_started | incident=`0beb3af1-ef7b-4143-a1f9-7cc6dc5a487f` | lesson_key=`frozen-context-before-start` | event_sha256=`a8af346f416bf0cf9778a426bf2638c60a6927c14382c28ac7d5f561e64531e5`
- #2: `0a4f9420-cfe6-4ad8-b96c-a5bfbd3731c1` | 2026-07-26T14:23:49.000Z | FAILURE/tdd_red_before_modules | incident=`d4d1304d-4c6c-4c2f-8d47-bb87aebba001` | lesson_key=`profile-bound-adapter-contract` | event_sha256=`be1ba86fada81e4a796e8730c6ac1460defbf22160cd36af6a0810994e221e9d`
- #3: `a5bc73e9-62b6-4ff1-a013-a9ac0b24dd31` | 2026-07-26T14:25:29.000Z | REVIEW/cf3_contract_boundary_review | incident=`8ccf87f2-7024-4717-a0fa-d36ed78be82c` | lesson_key=`independent-validation-oracle` | event_sha256=`e6909cbe979e3ddc2a15b071f807e6e22e78cf58b24a659d22c5a6b00f65ca07`
- #4: `c115df7f-0f34-4937-b0f3-9d046805c854` | 2026-07-26T14:25:48.000Z | GATE/cf3_targeted_regression_gate | incident=`48b92c2c-9e47-4d35-a0e1-bcf063d34f76` | lesson_key=`targeted-cf3-gate` | event_sha256=`a09256ee08d9170d2d75863b2b752cd4cdb5af3c963fb40a139923d2258eb0cc`
- #5: `9d5dff35-0d70-460a-a4bf-9e91a8e75370` | 2026-07-26T14:36:39.000Z | FAILURE/native_host_sandbox_unavailable | incident=`e2fcdb1d-5fb7-4f46-9e85-b99e7a0ac40d` | lesson_key=`native-containment-host-gate` | event_sha256=`ab545d21560d7a2139cf65941378a544fdf33ba074dbe707ee4464d09bb7c38d`
- #6: `f20c95aa-c30c-4a6c-8b5a-8ce73e89e782` | 2026-07-26T14:38:11.000Z | ERROR/event_evidence_digest_correction | incident=`aa4d23be-e771-4a4e-bd85-59cc3a7c79e4` | lesson_key=`evidence-digest-verification` | event_sha256=`ea0dc52a78f3a0dfa804dea563dbf5fcb7b6d3705d05da36bc317456b9868bd8`
- #7: `d02ed70b-7aab-4f43-9eb3-3dd2ff56f6af` | 2026-07-26T14:39:16.000Z | STATE_CHANGE/cf3_adapter_foundation_completed | incident=`b7d3cfcf-3b38-4af6-b7e4-48c12268aa8c` | lesson_key=`close-cf3-adapter-foundation` | event_sha256=`e8064c3afc6808569f980c6713b602878912972b682064737ee59bb0f4276f2d`
