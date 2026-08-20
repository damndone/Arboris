# Retrospective — v1-8-9-p1-classification-production-remediation-12

## Goal

# Workbench v1.8.9 P1 Classification Production Remediation 12 Objective  Close the P0 artifacts-index integrity evidence gap from exact baseline \`882ae98ace0308ed9d656f092141b8de844f88eb\` without changing the completed remediation-11 line, classification production bindings, Agent/Notebook/Report typed projections, or the report producer.  At the real repository-to-HTTP seam, the artifacts-index validator must verify each indexed artifact path is contained by the run root, resolves to a readable regular file, and has content whose actual SHA-256 equals the indexed digest. Missing, unreadable, non-regular, or digest-mismatched artifact files must fail closed as \`ARTIFACTS_INDEX_INVALID\` with HTTP 500 and no raw exception detail.  An absent or unreadable \`artifacts_index.json\` is resource unavailable and must remain \`ARTIFACTS_INDEX_UNAVAILABLE\` with HTTP 503. Present malformed JSON, unknown artifact type, duplicate/path/digest/schema violations, and artifact content integrity violations are invalid and must remain \`ARTIFACTS_INDEX_INVALID\` with HTTP 500. The unreadable-index and unreadable-regular-artifact probes must use controlled monkeypatching where needed; they must not rely on root chmod behavior.  The valid formal-output fixture must create real artifact bytes and compute its actual SHA-256. Preserve all existing fail-closed shape/type/path/digest tests, classification production bindings, and Agent/Notebook/Report typed projection coverage. Keep the two existing \`tests/test_api.py -k artifacts\` async fixture failures as a known gate and do not modify the report producer.  The remediation is limited to:  - \`backend/workbench/repository/run_repository.py\` - \`tests/test_v189_classification_production.py\` - this objective and its new handoff  Required evidence is TDD RED before production changes, then GREEN for the classification/repository/HTTP/ReportWorkspace focused suites, frontend focused suite and typecheck, compileall, diff check, the known \`tests/test_api.py -q -k artifacts\` gate, formal verify, and formal retrospective. Browser acceptance, external provider benchmark, central integration/cutover, host full gate, merge, tag, and release remain \`NOT VERIFIED\`.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/5 (20.0%; 20.0 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: N/A (sample=0; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T01:31:25.000Z `artifact_integrity_red`; cause_status: `known`; cause: The repository artifact-index validator accepts a valid digest string without checking the indexed artifact file exists, is readable and regular, or matches the digest.; resolution: `open`; lesson: Run artifact existence, readability, regular-file, and content-digest probes through the repository and HTTP seam before changing the validator.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `artifact-index-integrity-red`: occurrences=1; cause_status: `known`; root cause: The repository artifact-index validator accepts a valid digest string without checking the indexed artifact file exists, is readable and regular, or matches the digest.; solution: `open`

## Added tests

- `tests/test_api.py`
- `tests/test_v189_classification_production.py`

## New rules

- `artifact-index-integrity-red`: line experience occurrence(s)=1

## Future guidance

- Run artifact existence, readability, regular-file, and content-digest probes through the repository and HTTP seam before changing the validator.

## Event index

- #1: `953a531d-e6bc-428f-a623-298f14b966df` | 2026-08-20T01:29:15.363Z | STATE_CHANGE/line_started | incident=`4777a646-15bd-45fc-b90c-f0ecd90083a4` | lesson_key=`frozen-context-before-start` | event_sha256=`8d8ab4992536998de811a03105d94f61e2231bb261da341a3f15c414312587c4`
- #2: `2a7e6c1b-4d93-4f20-8b51-9e3d7c5a1f02` | 2026-08-20T01:31:25.000Z | FAILURE/artifact_integrity_red | incident=`6f5a4c3b-2d1e-49f8-8a7b-6c5d4e3f2a16` | lesson_key=`artifact-index-integrity-red` | event_sha256=`99d34fcfacd80da56906a772324f2b62631795fbf4a13903efd34e4140ff86da`
- #3: `7b2e5d9a-4c61-48f0-a3d7-1e9b6c2f5a85` | 2026-08-20T01:34:36.000Z | GATE/api_artifacts_known_gate | incident=`8c3d6e1f-5a72-4b90-8d24-6f1c9e7a3b05` | lesson_key=`api-artifacts-known-gate` | event_sha256=`8635a935367cd64999075190966c1520235a1f499a81a9bf601c81193a6c54f3`
- #4: `9d4f2b7c-6a18-4e50-b3d9-1c7a8f2e5b65` | 2026-08-20T01:34:36.000Z | GATE/artifact_integrity_green | incident=`a5c8e1f4-7b29-4d63-9f02-6e3a8c1b5d74` | lesson_key=`artifact-index-integrity-green` | event_sha256=`6ca9ac8c2500285fc0eae67536884fcdb26ca3e0f727ec452aa4c06bf3990a21`
- #5: `b8e2f5a1-6c3d-4f79-9a02-d7e1c5b8f655` | 2026-08-20T01:34:36.000Z | STATE_CHANGE/artifact_integrity_terminal | incident=`c9f4a7d2-6e1b-48f0-9a53-b7d5c2e8f155` | lesson_key=`formal-remediation-closeout` | event_sha256=`c1404a9bb9de2bee3850f0b25490edc11801816f8d4fcb89c37d87e4fb20bc0c`
