# Retrospective — v1-8-9-p0-notebook-workflow-admission-contract-migration

## Goal

# Workbench v1.8.9 P0 Notebook and Workflow Admission Contract Migration  ## Objective  Align historical Notebook and Agent workflow tests with the server-owned compiler/admission contract. A workflow or Notebook option must carry a valid scope (including active-head identity) and a server compilation record before execution; tests must not bypass this by supplying incomplete synthetic scope or treating a legacy OptionDraft as materializable.  ## Scope  - \`tests/test_lmm_agent_reach_v187.py\` - \`tests/test_notebook_artifact_contract.py\`  ## Acceptance  - Focused tests pass while preserving fail-closed scope and materialization   requirements. - Tests that exercise successful execution create the current typed compiler   and admission records; tests that exercise historical rejection assert the   typed error and do not restore a bypass. - Compile, diff check, formal verify, and retrospective pass.  ## Non-goals  Do not weaken \`WORKFLOW_SCOPE_MISSING\`, Notebook compiler admission, or confirmation binding in production code.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/6 (33.3%; 33.3 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=398710 ms (sample=2; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T07:51:06.600Z `admission_contract_test_migration_red`; cause_status: `known`; cause: The focused suite still exercised a legacy workflow scope and legacy Notebook OptionDraft against server-owned admission gates.; resolution: `open`; lesson: Migrate successful test paths to server-owned typed scope and compiler records, and assert typed rejection for historical paths.

## All errors

- #3 2026-08-21T08:02:24.437Z `typed_fixture_source_records`; cause_status: `known`; cause: The first server-bound Notebook fixture iterations omitted a non-empty model change, used an invalid selector shape, and supplied ambient artifact indexes without server-owned path and fingerprint records.; resolution: `resolved`; lesson: Typed success fixtures must use the same source-bound proposal, materialization, and integrity-registered artifact records as the server path.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `typed-admission-test-fixtures`: occurrences=1; cause_status: `known`; root cause: The focused suite still exercised a legacy workflow scope and legacy Notebook OptionDraft against server-owned admission gates.; solution: `open`
- `typed-fixture-source-records`: occurrences=1; cause_status: `known`; root cause: The first server-bound Notebook fixture iterations omitted a non-empty model change, used an invalid selector shape, and supplied ambient artifact indexes without server-owned path and fingerprint records.; solution: `resolved`

## Added tests

- `tests/test_notebook_artifact_contract.py`

## New rules

- `typed-admission-test-fixtures`: line experience occurrence(s)=1
- `typed-fixture-source-records`: line experience occurrence(s)=1

## Future guidance

- Migrate successful test paths to server-owned typed scope and compiler records, and assert typed rejection for historical paths.
- Typed success fixtures must use the same source-bound proposal, materialization, and integrity-registered artifact records as the server path.

## Event index

- #1: `e30fee43-b646-4d84-8c1f-cad081ea3dec` | 2026-08-21T07:43:16.708Z | STATE_CHANGE/line_started | incident=`dc826616-4d8c-446d-9ea9-48389f59c6eb` | lesson_key=`frozen-context-before-start` | event_sha256=`b748528dd48682ed9f538bba158344a3a11e377ee76272f79ee623db03241d38`
- #2: `3c8d7a5e-0a4e-4d4b-8c2f-5a2d9b1f4e70` | 2026-08-21T07:51:06.600Z | FAILURE/admission_contract_test_migration_red | incident=`6d2e9f1a-7b34-4c58-a901-2e7d6f4b8c13` | lesson_key=`typed-admission-test-fixtures` | event_sha256=`ae320d2ad97c24afbbc0ba62ed7d4cf312e031dea1806c45813072e0e60af325`
- #3: `4d9f6a21-8b37-4c52-ae10-7f6d2b9c4e81` | 2026-08-21T08:02:24.437Z | ERROR/typed_fixture_source_records | incident=`5e1a7c39-2d84-4f60-b9e3-6a2c8d1f7b54` | lesson_key=`typed-fixture-source-records` | event_sha256=`6d8908d6d5990db9f2ddaf96d1ca344f0063043258e2692c943a37f1bb5991ce`
- #4: `6b2e8f41-9c57-4d30-a6b1-7e4c2f9d8a63` | 2026-08-21T08:02:47.130Z | GATE/focused_admission_migration_green | incident=`7c3f9a52-1d68-4e20-b7a4-6f2c8d9e5b31` | lesson_key=`bounded-admission-gate` | event_sha256=`18fdffef7e88601d760b92b58253b9006bd7f3262ec1015c503981a54dbc1c30`
- #5: `8e4a1c63-7b29-4f50-a6d2-9c5e3b8f1a74` | 2026-08-21T08:03:18.555Z | STATE_CHANGE/line_completed | incident=`9f5b2d74-6c38-4e10-a7d1-8f3c5b2e9a64` | lesson_key=`formal-line-completion` | event_sha256=`c16ebc6704eacc8a15a92fa8900455eed71301af2df4714514b8b594c24b3ca3`
- #6: `a1c7e4f9-2b58-4d30-8e63-5f9a1c7b2d84` | 2026-08-21T08:04:24.020Z | GATE/admission_contract_migration_resolved | incident=`6d2e9f1a-7b34-4c58-a901-2e7d6f4b8c13` | lesson_key=`typed-admission-test-fixtures` | event_sha256=`55e397e9129356a2a5b6db9e6bde0a53c02e39950c7cb289f51e9b6f64324cf1`
