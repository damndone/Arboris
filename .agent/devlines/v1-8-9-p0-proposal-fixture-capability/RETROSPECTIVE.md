# Retrospective — v1-8-9-p0-proposal-fixture-capability

## Goal

# Workbench v1.8.9 P0 proposal fixture capability migration  Migrate proposal-operation and navigation fixtures to the server-issued ProposalStore capability required by the v1.8.9 authority boundary.  Required outcomes:  - fixture setup obtains a real server-owned proposal store capability; - proposal creation, revision, confirmation, and navigation tests continue to   prove their audit behavior through the capability path; - no legacy direct mutation bypass is restored and no production authority is   weakened.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/4 (25.0%; 25.0 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T06:12:23.629Z `legacy_proposal_fixture_boundary`; cause_status: `known`; cause: The proposal and navigation fixtures still constructed a caller-owned WorkbenchOrchestrator without the server-issued ProposalStore capability, so proposal creation failed closed at the production authority boundary.; resolution: `resolved`; lesson: Test and developer fixtures must enter proposal mutation only through the same server-issued capability path as production routes.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `fixture-capability-boundary`: occurrences=1; cause_status: `known`; root cause: The proposal and navigation fixtures still constructed a caller-owned WorkbenchOrchestrator without the server-issued ProposalStore capability, so proposal creation failed closed at the production authority boundary.; solution: `resolved`

## Added tests

- `tests/test_agent_navigation_fixture.py+tests/test_agent_operation_audit.py+tests/test_agent_proposal_operations.py`

## New rules

- `fixture-capability-boundary`: line experience occurrence(s)=1

## Future guidance

- Test and developer fixtures must enter proposal mutation only through the same server-issued capability path as production routes.

## Event index

- #1: `49608a63-c85a-4473-9e9f-60612ceff5df` | 2026-08-21T06:04:16.851Z | STATE_CHANGE/line_started | incident=`f1bd41fc-a846-4546-b647-2521f08ee4f5` | lesson_key=`frozen-context-before-start` | event_sha256=`926a4508e48e296235ad9d85d4fbdca6af3cf694f5e10bfc58efd87ad1aa46dc`
- #2: `f4df8f7e-5f1a-4b0a-9b6e-0f2f3d4c5a61` | 2026-08-21T06:12:23.629Z | FAILURE/legacy_proposal_fixture_boundary | incident=`a1c2d3e4-f5a6-4789-9012-b3c4d5e6f708` | lesson_key=`fixture-capability-boundary` | event_sha256=`94b6e6c9ed45ef3f92a2518607d474133682d2e890b3fdf4674667d95f8a080c`
- #3: `c4d5e6f7-a8b9-4c0d-1e2f-3a4b5c6d7e80` | 2026-08-21T06:12:47.266Z | GATE/scoped_capability_gate | incident=`b2c3d4e5-f6a7-4890-0123-c4d5e6f70819` | lesson_key=`scoped-fixture-capability-gate` | event_sha256=`6e67bd0bbd2013e8e12be9dace2e5230c8de1bfb7a9485653616069cc841bcbe`
- #4: `d5e6f7a8-b9c0-4d1e-2f3a-4b5c6d7e8091` | 2026-08-21T06:13:06.545Z | STATE_CHANGE/line_completed | incident=`c3d4e5f6-a7b8-4901-1234-d5e6f708192a` | lesson_key=`fixture-line-scoped-completion` | event_sha256=`3c4223047aad6ab4e466886f1b0ee8c6c3fc64fb97120a8ea3e6f23020282b2f`
