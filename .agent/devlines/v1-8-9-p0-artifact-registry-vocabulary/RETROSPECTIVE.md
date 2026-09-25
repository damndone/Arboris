# Retrospective — v1-8-9-p0-artifact-registry-vocabulary

## Goal

# Workbench v1.8.9 P0 Artifact Registry Vocabulary  ## Objective  Make the canonical run artifact registry recognize the already-produced typed \`measurement_advisory\` artifact, including its indexed file/digest and report consumer boundary. Keep the registry closed: accept only explicitly declared producer artifact types, reject forged or unknown types, and preserve fail-closed behavior for invalid records.  ## Scope  - \`backend/workbench/repository/run_repository.py\` - \`backend/workbench/engine/stages/ytype.py\` - \`tests/test_v189_artifact_contracts.py\` - \`tests/test_statistics_api_e2e_v186.py\`  ## Acceptance  - A valid \`measurement_advisory\` artifact can be listed and consumed through   the canonical indexed path with digest verification. - Unknown and forged artifact types remain rejected. - The statistical Report/Agent surface either consumes the typed packet through   the validated index or returns typed unavailable; no raw-file fallback is   restored. - Existing artifact registry and statistics focused tests pass.  ## Boundary  - Affected paths: the four paths above - Allowed paths: the four paths above - Protected paths: evidence authority, Agent/Notebook compiler, unrelated model estimators, release state - Dependencies: current canonical artifact index contract - Tests: \`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -q tests/test_v189_artifact_contracts.py tests/test_statistics_api_e2e_v186.py\` - Known gates: full backend, browser, production host/provider, and release gates remain separate

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/8 (37.5%; 37.5 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/3 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #4 2026-08-21T09:56:01.303Z `tdd_red_measurement_advisory_registry`; cause_status: `known`; cause: The canonical registry vocabulary omitted the producer-emitted measurement_advisory type, so a valid indexed record was rejected before list and summary projection.; resolution: `open`; lesson: Write and observe the behavior-changing registry test before adding a producer artifact type.

## All errors

- #2 2026-08-21T09:52:55.796Z `formal_cli_import_mismatch`; cause_status: `known`; cause: The formal CLI resolved an older editable workbench package and lacked a required context-pack API.; resolution: `resolved`; lesson: Run the formal CLI with the target worktree backend on shared editable environments.

## All gaps

- #5 2026-08-21T09:59:32.852Z `protected_statistics_test_stale_expectation`; cause_status: `known`; cause: The protected statistics end-to-end test retains a dirty migration assertion for the pre-vocabulary unavailable result, while the repaired canonical registry now admits the indexed measurement advisory and the Agent returns a complete typed summary.; resolution: `open`; lesson: Keep protected-line migration tests synchronized with canonical contract changes before using them as a shared scoped gate.

## All waste

- None recorded.

## Root causes and solutions

- `artifact-vocabulary-red-before-fix`: occurrences=1; cause_status: `known`; root cause: The canonical registry vocabulary omitted the producer-emitted measurement_advisory type, so a valid indexed record was rejected before list and summary projection.; solution: `open`
- `formal-cli-editable-path`: occurrences=1; cause_status: `known`; root cause: The formal CLI resolved an older editable workbench package and lacked a required context-pack API.; solution: `resolved`
- `protected-test-contract-stale`: occurrences=1; cause_status: `known`; root cause: The protected statistics end-to-end test retains a dirty migration assertion for the pre-vocabulary unavailable result, while the repaired canonical registry now admits the indexed measurement advisory and the Agent returns a complete typed summary.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `artifact-vocabulary-red-before-fix`: line experience occurrence(s)=1
- `formal-cli-editable-path`: line experience occurrence(s)=1
- `protected-test-contract-stale`: line experience occurrence(s)=1

## Future guidance

- Keep protected-line migration tests synchronized with canonical contract changes before using them as a shared scoped gate.
- Run the formal CLI with the target worktree backend on shared editable environments.
- Write and observe the behavior-changing registry test before adding a producer artifact type.

## Event index

- #1: `0c9b8421-e636-4ea8-8ad8-1ee1199281aa` | 2026-08-21T09:48:23.470Z | STATE_CHANGE/line_started | incident=`8b660d86-f617-4b00-864d-c5f4dcdf7ba2` | lesson_key=`frozen-context-before-start` | event_sha256=`3143cf36ead41a8e5a6e113685aec7b5558b50334ee9f3fdbeae3add2731f90c`
- #2: `e90abfe1-d464-47bb-bcc6-f10dafc47cfa` | 2026-08-21T09:52:55.796Z | ERROR/formal_cli_import_mismatch | incident=`5fe2d543-a3b5-430d-9e2b-e536dcf31bf8` | lesson_key=`formal-cli-editable-path` | event_sha256=`f0ad99452e4b416c9a03f00647c939bae2180f2366abef2655eedc4a633bbd86`
- #3: `4723a491-5c67-4d27-aeb3-c8db2930c9ed` | 2026-08-21T09:53:24.848Z | GATE/baseline_focused_tests | incident=`513be90d-fd14-473f-af7f-c0a32ea2f934` | lesson_key=`focused-baseline-before-change` | event_sha256=`0203e90f5ab9c7102d2062286381751780d2bb6b3e6c3f7d69b45ad4bae7486e`
- #4: `df1e5af9-34c6-4e01-ac0c-b950fb750ed5` | 2026-08-21T09:56:01.303Z | FAILURE/tdd_red_measurement_advisory_registry | incident=`3555b25f-d4f2-48a9-acd7-f5b20ec26515` | lesson_key=`artifact-vocabulary-red-before-fix` | event_sha256=`509ad378c9b3bc98b00fcec1720e871ca5d6f14459e99fd95e11cfed7a280e37`
- #5: `d91a40f1-497f-4cf2-98a3-11c71d3c8ffc` | 2026-08-21T09:59:32.852Z | GAP/protected_statistics_test_stale_expectation | incident=`f24b1f34-e753-4ab7-beb5-67b22f250592` | lesson_key=`protected-test-contract-stale` | event_sha256=`910523828ac2c0dc7d9251aa8ccafe4f6b5e47cb5a807e49fe567c1c32166717`
- #6: `ce1e6c71-e110-4f53-befd-5b86a81b0788` | 2026-08-21T09:59:55.740Z | GATE/artifact_registry_vocabulary_focused_gate | incident=`aeb91285-22ba-4376-b3bd-3211cbdd42c2` | lesson_key=`artifact-registry-producer-alignment` | event_sha256=`a210d82590e8217ee0e56510728202da0435314457c701ea94b217e98d4a7970`
- #7: `1ec9ddf4-9863-43c6-9d91-61627bf3640d` | 2026-08-21T10:01:14.003Z | GATE/formal_context_and_event_verify | incident=`7044f631-1c1a-496e-8403-f6a676463cf4` | lesson_key=`formal-verify-after-gate-record` | event_sha256=`abba05ca9e409144a82648023acf5cd53a43e1739f2bc92943fee886e3503d77`
- #8: `f1a7c3d9-6e2b-4a80-b5c1-9d7e3f2a6b14` | 2026-08-21T10:12:51.627Z | STATE_CHANGE/line_completed | incident=`a8e4c2f0-7b1d-4e9a-836f-2c5d7b0a1e6f` | lesson_key=`artifact-vocabulary-consumer-alignment` | event_sha256=`e52f2d79c43e41b8ed9859a62d57ab57079ddfce273e091a2666f144d995beb8`
