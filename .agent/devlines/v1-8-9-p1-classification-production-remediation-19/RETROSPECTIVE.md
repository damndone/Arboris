# Retrospective — v1-8-9-p1-classification-production-remediation-19

## Goal

# Workbench v1.8.9 P1 classification production remediation-19 objective  - Exact baseline: \`9cd2cef028ac8ee308862045f03000dd651d4630\`. - Formal line: \`v1-8-9-p1-classification-production-remediation-19\`. - Target worktree: \`/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p1-classification-production\`. - Scope: close the independent quality-review P1 in the Workbench-owned   generic artifact download Range/If-Range ordering boundary.  ## Required outcome  1. When the \`Range\` header is present, strictly parse it before applying the    existing \`If-Range\` gate. Present-but-empty and malformed values must always    return the existing explicit malformed-range \`400\`, including with a stale    \`If-Range\` value; they must never silently downgrade to a full \`200\`. 2. A syntactically valid Range with a stale \`If-Range\` must retain the existing    full-download \`200\` semantics. A valid Range with a matching or absent    \`If-Range\` must retain the existing partial response semantics. 3. A missing \`Range\` header must continue to return an ordinary full \`200\`    download and must explicitly have no \`Content-Range\` header. 4. Preserve same-FD bounded streaming, compatibility headers, cleanup,    integrity/TOCTOU checks, strict parser grammar and satisfiability semantics,    and all classification contracts without regression.  ## Allowed paths  - \`backend/workbench/http/runs_routes.py\` - \`tests/test_v189_classification_production.py\` - \`docs/superpowers/objectives/2026-08-20-v1.8.9-p1-classification-production-remediation-19-objective.md\` - \`docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-production-remediation-19-handoff.md\` - \`.agent/devlines/v1-8-9-p1-classification-production-remediation-19/**\` (only through \`scripts/devline_control.py\`)  ## Protected boundaries  - The repository root checkout and every other worktree are out of scope. - Do not reset, checkout, delete, or overwrite existing user work. - Existing remediation-18 and earlier formal records, Context Packs,   retrospectives, objectives, and handoffs are immutable. - \`backend/workbench/repository/file_integrity.py\`, classification   list/index/consumer seams, central Agent/Notebook/Report consumers, and   unrelated artifact integrity/security boundaries are unchanged. - Do not push, merge, tag, or modify release state.  ## Verification contract  - TDD RED then GREEN for stale \`If-Range\` plus empty, invalid, and valid Range   regressions, with an explicit no-Range \`Content-Range\` absence assertion. - Focused production Range/stream/cleanup/integrity/TOCTOU tests. - Full \`tests/test_v189_classification_production.py\`. - Classification contract suites:   \`tests/predictive_research/test_classification_contracts_v189.py\`,   \`tests/predictive_research/test_classification_protocol_v189.py\`,   \`tests/predictive_research/test_classification_leakage_v189.py\`, and   \`tests/predictive_research/test_classification_consumers_v189.py\`. - \`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench/http/runs_routes.py backend/workbench/repository/file_integrity.py\`. - \`git diff --check\` against the exact baseline. - Formal \`verify\`, CLI-generated \`retrospective\`, formal GATE events, and a   scoped commit with exact HEAD and source digests.  ## Known gates  Inherited fixture/environment gates, central Agent/Notebook/Report integration, browser-visible acceptance, external-provider calls, host/full gate, performance, release, merge, push, and tag verification remain \`NOT VERIFIED\` unless explicitly rerun and evidenced in this line.

## Final status

COMPLETED

## Metrics

- Failure frequency: 4/13 (30.8%; 30.8 per 100 events)
- Repeat rate: 1/4 (25.0%)
- Recurrence rate: 1/3 (33.3%)
- MTTR: median=0 ms (sample=4; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/7 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T05:15:02.000Z `stale_if_range_red`; cause_status: `known`; cause: The artifact route applies the stale If-Range fallback before invoking the strict Range parser, so present empty and malformed Range values return a full response.; resolution: `open`; lesson: Parse every present Range value before applying If-Range freshness fallback.

## All errors

- #3 2026-08-20T05:15:02.000Z `formal_event_missing_identity_red`; cause_status: `known`; cause: The first temporary formal event object omitted the mandatory event_id and incident_id fields and the CLI rejected it before appending.; resolution: `resolved`; lesson: Validate the complete formal event identity before invoking the append command.
- #9 2026-08-20T05:16:48.000Z `formal_event_invalid_incident_id`; cause_status: `known`; cause: The first diff-check GATE event object used an incident identifier with an invalid UUID shape and the CLI rejected it before appending.; resolution: `resolved`; lesson: Use validator-shaped UUID identities in every formal event source.
- #11 2026-08-20T05:18:30.000Z `formal_event_unknown_stage`; cause_status: `known`; cause: The first completion event used a non-contract stage label and the CLI rejected it before appending.; resolution: `resolved`; lesson: Use the formal event stage vocabulary when appending terminal state changes.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `formal-event-identity-before-append`: occurrences=2; cause_status: `known`; root cause: The first temporary formal event object omitted the mandatory event_id and incident_id fields and the CLI rejected it before appending.; solution: `resolved`
- `formal-event-stage-before-closeout`: occurrences=1; cause_status: `known`; root cause: The first completion event used a non-contract stage label and the CLI rejected it before appending.; solution: `resolved`
- `range-if-range-order`: occurrences=1; cause_status: `known`; root cause: The artifact route applies the stale If-Range fallback before invoking the strict Range parser, so present empty and malformed Range values return a full response.; solution: `open`

## Added tests

- `tests/predictive_research/test_classification_contracts_v189.py; tests/predictive_research/test_classification_protocol_v189.py; tests/predictive_research/test_classification_leakage_v189.py; tests/predictive_research/test_classification_consumers_v189.py`
- `tests/test_v189_classification_production.py`
- `tests/test_v189_classification_production.py -k range or stream or cleanup or mutation or symlink`
- `tests/test_v189_classification_production.py::test_generic_artifact_download_parses_present_range_before_stale_if_range`

## New rules

- `formal-event-identity-before-append`: line experience occurrence(s)=2
- `formal-event-stage-before-closeout`: line experience occurrence(s)=1
- `range-if-range-order`: line experience occurrence(s)=1

## Future guidance

- Parse every present Range value before applying If-Range freshness fallback.
- Use the formal event stage vocabulary when appending terminal state changes.
- Use validator-shaped UUID identities in every formal event source.
- Validate the complete formal event identity before invoking the append command.

## Event index

- #1: `e4cc6629-eed9-4ce1-8d1b-a1b538484992` | 2026-08-20T05:14:04.619Z | STATE_CHANGE/line_started | incident=`9abd3d08-2eb1-4a8b-8266-9a4a5e5b9164` | lesson_key=`frozen-context-before-start` | event_sha256=`ba75a84ca57ea09157a640bd1e0ca604f903bc2ef534bcbbfaa87804097b7565`
- #2: `2f3a7b11-5d44-4ec0-9c3d-7c6b2a8f1e55` | 2026-08-20T05:15:02.000Z | FAILURE/stale_if_range_red | incident=`6d8f2c44-91ab-4e77-b5c0-3a6f1d9e8240` | lesson_key=`range-if-range-order` | event_sha256=`2539769fd6f7b4c219d1c531e043f472ebeac2ef10cd69df10d4fe7e24957a55`
- #3: `8b1e4d62-7f39-4c50-a9d1-2e6f8b3c5a74` | 2026-08-20T05:15:02.000Z | ERROR/formal_event_missing_identity_red | incident=`4c7a2e91-5d36-4b80-9f13-6e8a2c5d7b04` | lesson_key=`formal-event-identity-before-append` | event_sha256=`ab0512992c425d1017e34c749bfe9db5b6efcacd97d3bba5b7a53c3ea3a4d65c`
- #4: `a6d4f1b8-2c93-4e57-8a10-6f3b9d2c7e41` | 2026-08-20T05:15:44.000Z | GATE/tdd_green | incident=`9e2c5a7b-1d46-4f80-b3a9-6c8e2d5f7a10` | lesson_key=`range-if-range-order` | event_sha256=`73ff622c40ace47500d9c3e634ad57888c7e460bb2ce688ecb4d486a04da919d`
- #5: `c1f7a4e9-6b28-4d53-8a10-2e6c9b5d7f40` | 2026-08-20T05:16:20.000Z | GATE/focused_suite_green | incident=`7d2a5f8c-4e91-6b30-9f73-1c5a8e2d6b40` | lesson_key=`classification-production-focused-suite` | event_sha256=`b165aa73bcbbf8a279ee9c885132a3ed4bc53fd900f03ecdc331b515adc14871`
- #6: `e5b2c8a1-7d34-4f69-9c20-6a3e8b5d1f72` | 2026-08-20T05:16:20.000Z | GATE/production_suite_green | incident=`2f7a4c9e-1b63-5d80-8a24-6c9e3b5d7f10` | lesson_key=`classification-production-suite` | event_sha256=`79cea12359f4fd867d018ae1588357ccfd41c7b1115093192a455b3a7351b8db`
- #7: `f8c3a1e6-5b27-4d90-8f14-2c6a9e3b7d50` | 2026-08-20T05:16:20.000Z | GATE/classification_contracts_green | incident=`6e2b9a4c-7f31-5d80-1a63-8c5e2d9b4f70` | lesson_key=`classification-contract-boundary` | event_sha256=`00de402dbc7de074a23841a656195af2a59b9671ffd0d8b626f87556837fe85a`
- #8: `b7e4c1a9-6d32-4f80-8e15-2c9a5b7d3f60` | 2026-08-20T05:16:48.000Z | GATE/compileall_green | incident=`1c6e9a4b-7f32-5d80-2a64-8b9e3c5f7d10` | lesson_key=`classification-static-integrity` | event_sha256=`50b8effdae9e88c575e85e5c7018e6ad4574677e06d890543fd310a7b14a5946`
- #9: `f2a8c5d1-7e34-4b90-9c26-5a1d8f3e6b70` | 2026-08-20T05:16:48.000Z | ERROR/formal_event_invalid_incident_id | incident=`5c7a2e9f-1d46-4b80-a3e6-8f2c4d9b7e10` | lesson_key=`formal-event-identity-before-append` | event_sha256=`25448c4bf9c6e81ecc15d7b9008d6a43e143896e6af428e871cbd53dd75f2375`
- #10: `d9a4c7e1-5b36-4f80-8c12-6e2a9d3f7b50` | 2026-08-20T05:16:48.000Z | GATE/diff_check_green | incident=`8f2c5a7e-1d46-4b90-6c3a-9e5d7f20a1c4` | lesson_key=`classification-static-integrity` | event_sha256=`d7c137d91f555f38d8ca05c9497f5493329b3670a39b717698a17d38e99f655b`
- #11: `c5f1a8d2-7e34-4b90-9a26-1d7f3e5b8c40` | 2026-08-20T05:18:30.000Z | ERROR/formal_event_unknown_stage | incident=`7a2e9c5f-1d46-4b80-6c3a-8e5d7f20a1c4` | lesson_key=`formal-event-stage-before-closeout` | event_sha256=`aaecb49f16ce289ebc582cd03a4584d0794284df58940f64bdf35871ef0fd12a`
- #12: `e1a6c4f8-2b79-4d50-9c3e-7f15a8b2d604` | 2026-08-20T05:18:30.000Z | STATE_CHANGE/remediation_19_completed | incident=`4b8e2d6f-1a73-4c90-5e27-9d3f6b8a1c50` | lesson_key=`remediation-19-formal-closeout` | event_sha256=`137c49829115027d1599860c39d908ebeeefa4a43193fb8d56a4bb4b1f5a1372`
- #13: `a9c4e7f1-2d68-4b50-8c13-6e5a1f9d3b70` | 2026-08-20T05:19:20.000Z | GATE/stale_if_range_red_resolved | incident=`6d8f2c44-91ab-4e77-b5c0-3a6f1d9e8240` | lesson_key=`range-if-range-order` | event_sha256=`2bf7afec205aebfe6893324c5cfa869a89d292a6a3410879b275e7b3759ea0da`
