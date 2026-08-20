# Retrospective — v1-8-9-p1-classification-production-remediation-10

## Goal

# Workbench v1.8.9 P1 Classification Production Remediation 10 Objective  Close the independent-spec-review blocker found after exact baseline \`47a41572ccb7dd8fd497a0829c040ed1df801715\` without changing the completed remediation-9 line, central Agent/Notebook/router/provider behavior, or the report producer.  The real artifacts-list seam must fail closed from the repository reader through \`GET /runs/{run_id}/artifacts\` to \`ReportWorkspace\`. The repository validator must use an explicit allowlist of artifact types already published by the existing canonical artifact producers/registries (including the classification, prediction, report/export, statistical-exploration, time-series/model, LMM, and workflow artifact contracts); it must not accept an arbitrary non-\`unknown\` string. Unknown or forged \`artifact_type\`, missing or null required fields, malformed paths or digests, duplicate identities, and tampered record structure must all produce exactly \`ARTIFACTS_INDEX_INVALID\`. The list route must return HTTP 500 for those invalid indexes, never return \`groups=[]\`/200, and never leak \`JSONDecodeError\` or another raw parser exception.  Add real repository, HTTP, and ReportWorkspace probes for a forged artifact type. Preserve the existing missing-index, malformed-JSON, missing-field, null path/digest, duplicate-id, path-containment, digest-shape, and tampered structure probes. Keep the classification production exact bindings and exact error-code assertions: active project/run/namespace, artifact/digest, split/fold/OOF/holdout, weights, calibration/threshold, receipt, and evidence remain server-owned and are not guessed or recomputed from raw JSON.  The remediation is limited to:  - \`backend/workbench/repository/run_repository.py\` - \`backend/workbench/http/runs_routes.py\` - \`frontend/src/report/ReportWorkspaceContext.tsx\` - \`frontend/src/report/ReportWorkspaceContext.v189.test.tsx\` - \`tests/test_v189_classification_production.py\` - \`tests/test_api.py\` only if focused canonical-index fixtures require direct   contract alignment; its two existing \`-k artifacts\` async fixture failures   remain a known gate unless this fix directly causes them - this objective, the implementation plan, and the new handoff  Required evidence is TDD RED before production changes, then GREEN for the repository/HTTP/ReportWorkspace forged-type probes, classification consumer/protocol/leakage suites, frontend focused suite and typecheck, compileall, diff check, the required \`tests/test_api.py -k artifacts\` known gate, formal verify, and formal retrospective. Browser acceptance, external provider benchmark, central integration/cutover, host full gate, merge, tag, and release remain \`NOT VERIFIED\`.

## Final status

COMPLETED_WITH_KNOWN_GATES

## Metrics

- Failure frequency: 2/6 (33.3%; 33.3 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T00:46:32.000Z `classification_remediation_ten_red`; cause_status: `known`; cause: The repository artifacts-list validator rejects only the literal artifact_type unknown, so a forged artifact_type still crosses the real list seam.; resolution: `accepted`; lesson: Every artifact type must be checked against an explicit canonical allowlist at the repository boundary before HTTP grouping or ReportWorkspace consumption.

## All errors

- #3 2026-08-20T00:49:21.000Z `classification_test_selector_path`; cause_status: `known`; cause: The first requested classification regression command named tests/test_v189_classification_consumers.py, but the repository stores the consumer/protocol/leakage files under tests/predictive_research/.; resolution: `resolved`; lesson: Resolve exact repository test paths before running a formal focused selector and keep command evidence aligned with the frozen worktree layout.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `classification-remediation-ten-red`: occurrences=1; cause_status: `known`; root cause: The repository artifacts-list validator rejects only the literal artifact_type unknown, so a forged artifact_type still crosses the real list seam.; solution: `accepted`
- `classification-selector-path-resolution`: occurrences=1; cause_status: `known`; root cause: The first requested classification regression command named tests/test_v189_classification_consumers.py, but the repository stores the consumer/protocol/leakage files under tests/predictive_research/.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `classification-remediation-ten-red`: line experience occurrence(s)=1
- `classification-selector-path-resolution`: line experience occurrence(s)=1

## Future guidance

- Every artifact type must be checked against an explicit canonical allowlist at the repository boundary before HTTP grouping or ReportWorkspace consumption.
- Resolve exact repository test paths before running a formal focused selector and keep command evidence aligned with the frozen worktree layout.

## Event index

- #1: `5e322a2b-fa1a-4d41-bf9d-cdd13b6bd435` | 2026-08-20T00:45:26.934Z | STATE_CHANGE/line_started | incident=`69b2f33a-0e41-465c-9f4d-3a8cbddc2c77` | lesson_key=`frozen-context-before-start` | event_sha256=`964fb28d33eb28e7b6c6840dd4b1148dc112dedda7a108db219acc2102f2f395`
- #2: `c0a8012e-1d57-4e34-8f8c-0e58dfdf9a10` | 2026-08-20T00:46:32.000Z | FAILURE/classification_remediation_ten_red | incident=`7b2b8a1d-37af-4f93-a07d-5e68d0c7a9f1` | lesson_key=`classification-remediation-ten-red` | event_sha256=`66f461c3c4393aa73a2846bc867251a948d6e5f7002af7cfd508c4d0a49a3cc5`
- #3: `3f1b2458-7ae1-4dfd-b8c4-2a6f39e1d5c7` | 2026-08-20T00:49:21.000Z | ERROR/classification_test_selector_path | incident=`bf1c4b60-13e2-4ab8-9d57-2c6f07e1a395` | lesson_key=`classification-selector-path-resolution` | event_sha256=`e3ed1d013459d333c00e678804c9a6a84fe1c88c7b43edd75f2e1871c5d7149e`
- #4: `b8c1e4a7-2f63-4d90-9a15-7e3b6c0d4f82` | 2026-08-20T00:50:51.000Z | GATE/classification_remediation_ten_api_known_gate | incident=`d04e7b91-5c28-4fa3-a612-8e3d9b0c7f45` | lesson_key=`classification-remediation-ten-api-known-gate` | event_sha256=`e291a11be3da542778024e1222ae9b757320e61191cfc1def7512cdff9cbfe8f`
- #5: `e61a3c8f-4d29-47b0-9c52-7f18e6a2d3b4` | 2026-08-20T00:52:22.000Z | GATE/classification_remediation_ten_green | incident=`4b7e1d92-6c35-4fa8-a018-3d9c5e7b2f64` | lesson_key=`classification-remediation-ten-green` | event_sha256=`46f06ec72d6dc4ece217cdb8ee71def5e03fdfeaaba299f0611e56a7fe492113`
- #6: `f2a7c9e4-1d63-4b80-9f35-6e28a0d7c451` | 2026-08-20T00:52:48.000Z | STATE_CHANGE/classification_remediation_ten_terminal | incident=`6d3a8f1c-9b47-4e20-a5c6-7f28d0b193e4` | lesson_key=`classification-remediation-ten-terminal` | event_sha256=`011e03fce6aa6b8a2e60a6eb400299b5a5721d7b3cde8f13d0acd41d00a67e9d`
