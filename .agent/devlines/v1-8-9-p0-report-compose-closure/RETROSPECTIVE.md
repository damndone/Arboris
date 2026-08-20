# Retrospective — v1-8-9-p0-report-compose-closure

## Goal

# Workbench v1.8.9 P0 Report Compose Closure Objective  ## Objective  Close the remaining workflow-runtime report composition boundary on the exact v1.8.9 hardening candidate \`f1905b23527f239f6161b939d93822e9de9303f0\`. \`report.compose\` must produce HTML, PDF, and XLSX only through a typed, receipt-bound workflow report writer. The writer must use the existing server-owned workflow evidence port, formal output targets, artifact hashes, and completion registry; a caller-owned mapping must never be accepted as a report authority or write path.  ## Required outcomes  1. A valid admitted \`report.compose\` step emits its declared HTML, PDF, and    XLSX artifacts and completes through the same server artifact registry as    other workflow outputs. 2. Report output bytes are written through held formal output targets and are    recorded with the active workflow receipt, exact run identity, producer    step, input collection, and content digest. 3. Replaying an identical existing output is deterministic; replacing,    rebinding, changing the run root, using another receipt, or supplying a    raw mapping fails closed before an unbound write. 4. Existing C0 Report evidence writers remain strict and unchanged: this    workflow report writer is a separate typed capability over the workflow    evidence port, not a second Report evidence authority. 5. Focused workflow/runtime regressions and the relevant v1.8.9 security    tests pass; stale fixtures are migrated to the current canonical artifact    record contract rather than weakening the production reader.  ## Exact baseline  - baseline SHA: \`f1905b23527f239f6161b939d93822e9de9303f0\` - branch: \`workbench-v1.8.9-hardening-integration\` - worktree: \`/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-hardening-integration\`  ## Safety boundaries  - Do not loosen \`ReportDocumentWriterV1\`, \`ReportEvidenceWriterV1\`, or   \`EvidenceProjectionV1\` ownership checks. - Do not restore raw model-result, raw-report-mapping, or path-based fallback   authority. - Do not change the C0/C1/C2 host resolver contract in this line. - Do not claim browser, provider, full-host-gate, merge, tag, or release   acceptance from this focused implementation line.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/5 (40.0%; 40.0 per 100 events)
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

- #2 2026-08-20T08:01:31.494Z `report_compose_fixture_red`; cause_status: `known`; cause: The report.compose regression reached the canonical artifact reader with a legacy fixture index that omitted code_version and config_hash, so the focused test was blocked before report rendering.; resolution: `resolved`; lesson: Migrate stale fixtures to the canonical artifact record contract instead of weakening the production reader.

## All errors

- None recorded.

## All gaps

- #4 2026-08-20T08:05:08.479Z `inherited_workflow_truth_suite_gap`; cause_status: `known`; cause: The broad legacy workflow truth selector still contains model fixtures that fail at current survey-subpopulation or persisted-model-run prerequisites and five formal race probes that call the intentionally strict raw-mapping report API.; resolution: `accepted`; lesson: Keep inherited model and legacy race-fixture migration separate from the report.compose closure; never relax the strict writer to make old callers pass.

## All waste

- None recorded.

## Root causes and solutions

- `report-compose-canonical-fixture`: occurrences=1; cause_status: `known`; root cause: The report.compose regression reached the canonical artifact reader with a legacy fixture index that omitted code_version and config_hash, so the focused test was blocked before report rendering.; solution: `resolved`
- `separate-inherited-workflow-suite`: occurrences=1; cause_status: `known`; root cause: The broad legacy workflow truth selector still contains model fixtures that fail at current survey-subpopulation or persisted-model-run prerequisites and five formal race probes that call the intentionally strict raw-mapping report API.; solution: `accepted`

## Added tests

- `tests/test_workflow_runtime.py report.compose typed-writer probes`
- `tests/test_workflow_runtime.py tests/test_v189_workflow_truth.py`
- `tests/test_workflow_runtime.py::test_report_collection_exports_one_complete_artifact_pack`

## New rules

- `report-compose-canonical-fixture`: line experience occurrence(s)=1
- `separate-inherited-workflow-suite`: line experience occurrence(s)=1

## Future guidance

- Keep inherited model and legacy race-fixture migration separate from the report.compose closure; never relax the strict writer to make old callers pass.
- Migrate stale fixtures to the canonical artifact record contract instead of weakening the production reader.

## Event index

- #1: `556adfc2-e31f-442b-a41c-decc61262c92` | 2026-08-20T07:39:11.883Z | STATE_CHANGE/line_started | incident=`4c20158a-ce01-44e5-b629-413496b9226e` | lesson_key=`frozen-context-before-start` | event_sha256=`d2b060e5fb56919adff84ebf2df6ece2e1a45278abf0fd81e6d8e301dfa61f2c`
- #2: `d1f7a8c2-3b4e-4d5f-9a6b-7c8d9e0f1a2b` | 2026-08-20T08:01:31.494Z | FAILURE/report_compose_fixture_red | incident=`b2c3d4e5-f6a7-4890-abcd-ef0123456789` | lesson_key=`report-compose-canonical-fixture` | event_sha256=`9c5566d5d20d5ec746f73c69a8b51521e66d9d481f3ccc56aad0c95b30a04f1c`
- #3: `e2f8a9b3-4c5d-4e6f-a7b8-9c0d1e2f3a4b` | 2026-08-20T08:02:52.347Z | GATE/report_compose_typed_writer_green | incident=`c3d4e5f6-a7b8-4901-bcde-f0123456789a` | lesson_key=`workflow-report-typed-capability` | event_sha256=`3b6f9dce3cc4bfb00e73240d9255e58ccde0e2dac96ca239ba808d244c86302c`
- #4: `f3a9b0c4-5d6e-4f7a-b8c9-0d1e2f3a4b5c` | 2026-08-20T08:05:08.479Z | GAP/inherited_workflow_truth_suite_gap | incident=`d4e5f6a7-b8c9-4012-def0-123456789abc` | lesson_key=`separate-inherited-workflow-suite` | event_sha256=`5e79b24ca7c4cb79a1410a16a6d2bf9e2150e43ce25c3640215d08447f8d598a`
- #5: `a4b0c5d6-7e8f-4012-9345-6a7b8c9d0e1f` | 2026-08-20T08:05:47.083Z | STATE_CHANGE/report_compose_closure_completed | incident=`e5f6a7b8-c9d0-4123-ef45-6789abcdef01` | lesson_key=`focused-report-compose-closeout` | event_sha256=`26f2e65a338e9a86ec5c412d59b36e8cd18dc58a3666d38cab01e8cfe98657cd`
