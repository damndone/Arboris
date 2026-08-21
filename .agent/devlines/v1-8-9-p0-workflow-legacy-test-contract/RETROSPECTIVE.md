# Retrospective — v1-8-9-p0-workflow-legacy-test-contract

## Goal

# Workbench v1.8.9 P0 workflow legacy-test contract migration  Migrate legacy Agent workflow/data-management tests to the current fail-closed workflow scope and server-owned metadata contracts without weakening runtime authority.  Required outcomes:  - generic and natural-language workflow fixtures include the active-head scope   required by the compiler; - missing-value filters use confirmed metadata registry input rather than   bypassing the data-consumer trust boundary; - multi-step workflow tests continue to prove composition, derived columns,   survey design propagation, and execution behavior under the current typed   admission contract; - no production authority, metadata, or execution boundary is relaxed.

## Final status

STARTED

## Metrics

- Failure frequency: 2/4 (50.0%; 50.0 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: N/A (sample=0; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T06:08:39.972Z `workflow_legacy_contract_red`; cause_status: `known`; cause: The owned legacy Agent workflow tests still omit active_head_run_id from compiler preconditions, and missing-value subset tests have no confirmed server-owned metadata registry. The exact scoped suite fails before the intended composition, derived-column, survey-design, and execution assertions can run.; resolution: `open`; lesson: Migrate fixtures to the current server-owned scope and metadata admission contracts while retaining the original behavioral assertions.
- #3 2026-08-21T06:19:44.987Z `workflow_data_operation_artifact_registry_gap`; cause_status: `known`; cause: The data.rename workflow adapter persists its derived data and recipe in the public artifact index but does not admit those result artifacts into the active server-owned workflow artifact registry before a dependent model.genesis step consumes the produced_dataset binding.; resolution: `open`; lesson: A public artifact-index row is not sufficient evidence for a workflow dependency; every producer result must be admitted into the active receipt-bound server registry before downstream consumption.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `workflow-data-operation-registry-gap`: occurrences=1; cause_status: `known`; root cause: The data.rename workflow adapter persists its derived data and recipe in the public artifact index but does not admit those result artifacts into the active server-owned workflow artifact registry before a dependent model.genesis step consumes the produced_dataset binding.; solution: `open`
- `workflow-legacy-contract-red`: occurrences=1; cause_status: `known`; root cause: The owned legacy Agent workflow tests still omit active_head_run_id from compiler preconditions, and missing-value subset tests have no confirmed server-owned metadata registry. The exact scoped suite fails before the intended composition, derived-column, survey-design, and execution assertions can run.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `workflow-data-operation-registry-gap`: line experience occurrence(s)=1
- `workflow-legacy-contract-red`: line experience occurrence(s)=1

## Future guidance

- A public artifact-index row is not sufficient evidence for a workflow dependency; every producer result must be admitted into the active receipt-bound server registry before downstream consumption.
- Migrate fixtures to the current server-owned scope and metadata admission contracts while retaining the original behavioral assertions.

## Event index

- #1: `7aaa3174-ea55-4516-92c9-8590049f48af` | 2026-08-21T06:04:08.136Z | STATE_CHANGE/line_started | incident=`c8ccbc1a-f328-4395-bc31-81e12d273e08` | lesson_key=`frozen-context-before-start` | event_sha256=`2db6c983348e91c0a5180bbf73246b29589e1bb63bd02fabb1eb9d331656ea5e`
- #2: `a1b2c3d4-e5f6-4789-a012-3456789abcde` | 2026-08-21T06:08:39.972Z | FAILURE/workflow_legacy_contract_red | incident=`b2c3d4e5-f6a7-4890-b123-456789abcdef` | lesson_key=`workflow-legacy-contract-red` | event_sha256=`ef36099a3b32cf3ea3a67f4be92bcd23878d28a3f7e2a80212ec1c41fdedf92c`
- #3: `c3f4a5b6-7890-4cde-8f12-3456789abcde` | 2026-08-21T06:19:44.987Z | FAILURE/workflow_data_operation_artifact_registry_gap | incident=`d4e5f607-8901-4abc-9def-0123456789ab` | lesson_key=`workflow-data-operation-registry-gap` | event_sha256=`045c26c8695937171cfa0d7a2997b4100a9a6c4efc639230909b8fcb8400257d`
- #4: `e5f60718-9012-4abc-9def-0123456789ab` | 2026-08-21T06:20:02.259Z | GATE/workflow_legacy_scoped_suite_residual | incident=`d4e5f607-8901-4abc-9def-0123456789ab` | lesson_key=`scoped-suite-gate-boundary` | event_sha256=`9e09b6fbec437a2f5691d95466d5c599dc8512a8d8358cfbb83fdeced5f60b20`
