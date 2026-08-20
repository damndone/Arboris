# Retrospective — v1-8-9-p1-classification-production-remediation-11

## Goal

# Workbench v1.8.9 P1 Classification Production Remediation 11 Objective  Close the independent-spec-review blocker from exact baseline \`bab159d3ed8e19a67c17a3fdce21853437c0b451\` without changing the completed remediation-10 line, central Agent/Notebook/router/provider behavior, or the report producer.  The repository artifacts-index reader must derive its accepted artifact types from the canonical producer/registry vocabulary, including the real \`formal_output\` workflow artifact type. A valid canonical \`formal_output\` index must pass through the repository, \`GET /runs/{run_id}/artifacts\`, and ReportWorkspace. Unknown or forged artifact types, missing or null fields, duplicate artifact IDs, path escapes, invalid digests, and malformed JSON must fail closed with exactly \`ARTIFACTS_INDEX_INVALID\`; the HTTP route must return HTTP 500 without returning groups or leaking raw parser exceptions.  An absent or unreadable artifacts index is a resource-unavailable condition: the repository and HTTP route must return exactly \`ARTIFACTS_INDEX_UNAVAILABLE\` and HTTP 503. The tests must state this status matrix explicitly and parameterize valid \`formal_output\`, invalid mutations, and missing/unreadable cases.  Existing classification production bindings remain server-owned and must not be guessed or recomputed from raw JSON: active project/run/namespace, artifact/digest, split/fold/OOF/holdout, weights, calibration/threshold, receipt, and evidence. Agent, Notebook, and Report consume only typed persisted evidence.  The remediation is limited to:  - \`backend/workbench/repository/run_repository.py\` - \`backend/workbench/http/runs_routes.py\` - \`frontend/src/report/ReportWorkspaceContext.tsx\` - \`frontend/src/report/ReportWorkspaceContext.v189.test.tsx\` - \`tests/test_v189_classification_production.py\` - \`tests/test_api.py\` only if focused canonical-index fixtures require direct   contract alignment - this objective and its new handoff  Required evidence is TDD RED before production changes, then GREEN for the repository/HTTP/ReportWorkspace valid and invalid artifact-index probes, the classification consumer/protocol/leakage suites, frontend focused suite and typecheck, compileall, diff check, the required \`tests/test_api.py -k artifacts\` known gate, formal verify, and formal retrospective. The two existing asynchronous report-fixture failures remain a known gate; do not modify the report producer. Browser acceptance, external provider benchmark, central integration/cutover, host full gate, merge, tag, and release remain \`NOT VERIFIED\`.

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

- #2 2026-08-20T01:13:53.968Z `classification_remediation_eleven_red`; cause_status: `known`; cause: The repository artifact-type allowlist omits the canonical formal_output workflow artifact, so valid repository and HTTP artifact-list reads fail closed as invalid.; resolution: `accepted`; lesson: Test every canonical producer artifact type at the repository, HTTP, and ReportWorkspace boundaries before freezing the vocabulary.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `classification-remediation-eleven-red`: occurrences=1; cause_status: `known`; root cause: The repository artifact-type allowlist omits the canonical formal_output workflow artifact, so valid repository and HTTP artifact-list reads fail closed as invalid.; solution: `accepted`

## Added tests

- No test evidence recorded.

## New rules

- `classification-remediation-eleven-red`: line experience occurrence(s)=1

## Future guidance

- Test every canonical producer artifact type at the repository, HTTP, and ReportWorkspace boundaries before freezing the vocabulary.

## Event index

- #1: `0562cf34-bb1c-43c8-9001-2be6ba977a2a` | 2026-08-20T01:11:32.817Z | STATE_CHANGE/line_started | incident=`5b00105b-48cf-4881-bd50-73027ad71064` | lesson_key=`frozen-context-before-start` | event_sha256=`a608ab35de44ce3bb42a871807273f8cb2e68233fea533592e8e6354ee4811d4`
- #2: `c0a8012e-1d57-4e34-8f8c-0e58df9a9a11` | 2026-08-20T01:13:53.968Z | FAILURE/classification_remediation_eleven_red | incident=`d4e5f6a7-b8c9-4012-cd34-56789abcde11` | lesson_key=`classification-remediation-eleven-red` | event_sha256=`a5d83d0377fc7dd2ed1f84e84a10a0b834344350411fc5418e9ff4b490c9924c`
- #3: `e61a3c8f-4d29-47b0-9c52-7f18e6a2d3b5` | 2026-08-20T01:15:47.200Z | GATE/classification_remediation_eleven_api_known_gate | incident=`f2a7c9e4-1d63-4b80-9f35-6e28a0d7c452` | lesson_key=`classification-remediation-eleven-api-known-gate` | event_sha256=`3d29560694a9e1942e11ca177c065087e6e3fbd9eb9f3051bd4a0c70c951ce0f`
- #4: `a8b9c0d1-e2f3-4456-789a-bcdef0123457` | 2026-08-20T01:17:54.030Z | GATE/classification_remediation_eleven_green | incident=`b9c0d1e2-f3a4-4567-89ab-cdef01234567` | lesson_key=`classification-remediation-eleven-green` | event_sha256=`2324c2910a52e8c9088c9b5db7f380a49aaa9a458c20cf4cbb5297ca94468e91`
- #5: `b9c0d1e2-f3a4-4567-89ab-cdef01234568` | 2026-08-20T01:18:59.225Z | STATE_CHANGE/classification_remediation_eleven_terminal | incident=`c0d1e2f3-a4b5-4678-9abc-def012345679` | lesson_key=`classification-remediation-eleven-terminal` | event_sha256=`20c7f76e65873036949f6b045d85986232da57f66af000966f341b287140a218`
