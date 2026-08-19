# Retrospective — v1-8-9-p0-workflow-truth-remediation-4

## Goal

# v1.8.9 P0 Workflow Truth Remediation 4 Objective  Close the remaining write-surface and run-lineage gaps found by the remediation-3 review. Every report, post-estimation and model helper that can create or register a formal artifact must require the same admitted workflow receipt; completion must reject artifacts from another run even when their metadata looks valid; the public EvidencePersistencePort must be a server-issued capability; and the workflow lock must protect the actual directory/inode used for writes rather than a stale path.  Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749 Remediation line: v1-8-9-p0-workflow-truth-remediation-4 Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-workflow-truth  Required outcomes:  - \`_execute_workflow_report\`, joint/white post-estimation and every other   write-capable helper are receipt-gated or fail closed before any write; - completion binds artifact run identity to the admitted target/run/branch,   not merely project path, registry row and expected output; - EvidencePersistencePort construction/admission requires the server host   capability and cannot be created by a caller; - workflow lock and all writes share one stable admitted FD/inode; replacing   the path cannot split the lock domain; - existing 86 focused cases and prior TOCTOU/path/restart protections remain; - no helper or legacy compatibility alias can produce formal evidence outside   the admitted route.  Keep C0 contracts and the package-local boundary. Do not modify shared cutover, central catalog, frontend, provider wiring, or protected paths.

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

- #2 2026-08-16T16:10:00.000Z `tdd_red_workflow_remediation_4`; cause_status: `known`; cause: Remediation-3 independent review red probes reproduced seven remediation-4 gaps: direct EvidencePersistencePort construction, cross-run completion artifact acceptance, receipt-less joint/White helpers, receipt-less post-estimation persistence, receipt-less report persistence, and workflow directory replacement splitting the write path from the admitted lock inode.; resolution: `open`; lesson: Every write-capable helper must enforce the same server-issued receipt before any read or write, completion must bind to the admitted target run, and the lock must validate the exact directory inode used for appends.

## All errors

- #3 2026-08-16T16:09:00.000Z `pytest_selector_error`; cause_status: `known`; cause: The first focused red-test command used an invalid pytest -k expression and pytest stopped before collecting tests.; resolution: `resolved`; lesson: Validate the test selector before interpreting a red/green result and record command errors in the formal event stream.

## All gaps

- #6 2026-08-16T12:42:00.000Z `workflow4_host_integration_dependency`; cause_status: `external`; cause: The real server host endpoint and the shared Agent and Notebook callers are outside this remediation line and have not been wired here.; resolution: `open`; lesson: The next integration line must obtain the host-owned workflow evidence directory FD, pass it through the HTTP and Notebook execution boundary, and verify shared Agent and Notebook behavior before enabling execution.

## All waste

- None recorded.

## Root causes and solutions

- `test-selector-command-error`: occurrences=1; cause_status: `known`; root cause: The first focused red-test command used an invalid pytest -k expression and pytest stopped before collecting tests.; solution: `resolved`
- `workflow-remediation-4-red-before-fix`: occurrences=1; cause_status: `known`; root cause: Remediation-3 independent review red probes reproduced seven remediation-4 gaps: direct EvidencePersistencePort construction, cross-run completion artifact acceptance, receipt-less joint/White helpers, receipt-less post-estimation persistence, receipt-less report persistence, and workflow directory replacement splitting the write path from the admitted lock inode.; solution: `open`
- `workflow4-host-integration-dependency`: occurrences=1; cause_status: `external`; root cause: The real server host endpoint and the shared Agent and Notebook callers are outside this remediation line and have not been wired here.; solution: `open`

## Added tests

- `tests/test_v189_workflow_truth.py`

## New rules

- `test-selector-command-error`: line experience occurrence(s)=1
- `workflow-remediation-4-red-before-fix`: line experience occurrence(s)=1
- `workflow4-host-integration-dependency`: line experience occurrence(s)=1

## Future guidance

- A real host handle must be an explicit integration input; local tests may use an explicit temporary handle but must not stand in for production authority.
- Every write-capable helper must enforce the same server-issued receipt before any read or write, completion must bind to the admitted target run, and the lock must validate the exact directory inode used for appends.
- The next integration line must obtain the host-owned workflow evidence directory FD, pass it through the HTTP and Notebook execution boundary, and verify shared Agent and Notebook behavior before enabling execution.
- Validate the test selector before interpreting a red/green result and record command errors in the formal event stream.

## Event index

- #1: `e4b46e8e-b145-4c33-bc51-3845ad68062e` | 2026-08-16T12:10:50.393Z | STATE_CHANGE/line_started | incident=`b6106b42-debf-46f7-9e86-61507234b849` | lesson_key=`frozen-context-before-start` | event_sha256=`4d4b1046ea332c1d2e5d5c15e6db7c81ac318a1a310181b3daec8dd5a910e5fd`
- #2: `5b8f0f20-4f04-4d7f-9edb-1e4b8d0a6f11` | 2026-08-16T16:10:00.000Z | FAILURE/tdd_red_workflow_remediation_4 | incident=`c1d4e6f8-0a2b-4c6d-8e10-f2a4b6c8d0e2` | lesson_key=`workflow-remediation-4-red-before-fix` | event_sha256=`dcfe5c68233b25b22b9d1e871349259563660602e8ecb2100a1d8e89e32e595b`
- #3: `2c6e8a10-4d3f-4b5e-9c71-f3a5d7b9e1c3` | 2026-08-16T16:09:00.000Z | ERROR/pytest_selector_error | incident=`d2f4b6a8-c0e2-4f6a-8b1c-3d5e7f9a1b2c` | lesson_key=`test-selector-command-error` | event_sha256=`7582c3996039a2d8dbafcb279b01f56e3b201fcb954b1db58be30ed0c347744f`
- #4: `7f1b3d5e-9a2c-4f6d-8b0e-1c3a5e7d9f20` | 2026-08-16T12:40:00.000Z | REVIEW/workflow4_self_review | incident=`2d4f6a8c-0e1b-3d5f-7a9c-2e4b6d8f0a1c` | lesson_key=`workflow-remediation-4-host-boundary` | event_sha256=`ed6dfbb5b6658be04b4969db83d9af645cb885bb9dd384e201824253a936e6d8`
- #5: `8a2c4e6f-0b1d-3f5a-7c9e-2b4d6f8a0c1e` | 2026-08-16T12:41:00.000Z | GATE/workflow4_focused_gate | incident=`3e5f7a9c-1b2d-4f6a-8c0e-3b5d7f9a1c2e` | lesson_key=`workflow-remediation-4-focused-gate` | event_sha256=`57d5419f88b1111e3e856629248fa51df9ff9fb4cc2d1bd9c9443e6d0c0cc2ea`
- #6: `9b3d5f7a-1c2e-4f6b-8d0a-3c5e7f9b1d2a` | 2026-08-16T12:42:00.000Z | GAP/workflow4_host_integration_dependency | incident=`4f6a8c0e-2b4d-6f8a-0c1e-3d5f7a9b1c2e` | lesson_key=`workflow4-host-integration-dependency` | event_sha256=`9781530c9d201589fd891a285c3898a0c72cadaa2b578f7286b2e21e1b6bde07`
- #7: `0c2e4a6f-8b1d-3f5c-7a9e-2d4b6f8c0e1a` | 2026-08-16T12:44:00.000Z | STATE_CHANGE/workflow4_line_completed | incident=`5a7c9e1b-3d5f-7a9c-1e2b-4d6f8a0c2e4b` | lesson_key=`workflow-remediation-4-handoff-boundary` | event_sha256=`9a6ca2acb753658ba2d14366d08e4e3489e88ca71f1e802aaed9ea8a75d0643c`
