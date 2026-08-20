# Retrospective — v1-8-9-p1-classification-production-remediation-9

## Goal

# Workbench v1.8.9 P1 Classification Production Remediation 9 Objective  Close the returned independent-spec-review gaps from exact baseline \`988f44a358d65d42b3179afcf6b50e328cf3546d\` without changing the completed remediation line, central Agent/Notebook/router/provider behavior, or the report producer.  The real artifacts-list seam must fail closed from the repository reader through \`GET /runs/{run_id}/artifacts\` to \`ReportWorkspace\`. The index must contain an explicit \`artifacts\` list; every record must satisfy the existing canonical \`ArtifactRecord.to_dict()\` contract and the list-reader identity invariants: exact required fields and types, known artifact kind, normalized run-relative path containment, lowercase SHA-256/digest shape, and unique nonempty artifact identity. Unknown \`record_type\`/artifact kind, missing or null fields, duplicate IDs, path escapes, invalid digests, and tampered structure must all produce the exact typed \`ARTIFACTS_INDEX_INVALID\` outcome. The list route must never fall back to \`groups=[]\` or leak parser exceptions.  The classification production regression near line 685 must assert exactly \`CLASSIFICATION_SERVER_IDENTITY_MISMATCH\`, with a RED probe showing that an alternative error code is not acceptable. Existing active project/run/ namespace, artifact/digest, split/fold/OOF/holdout, weights, calibration/threshold, receipt, and evidence bindings must remain server-owned and must not be guessed or recomputed from raw JSON.  The remediation is limited to:  - \`backend/workbench/repository/run_repository.py\` - \`backend/workbench/http/runs_routes.py\` - \`frontend/src/report/ReportWorkspaceContext.tsx\` - \`frontend/src/report/ReportWorkspaceContext.v189.test.tsx\` - \`tests/test_v189_classification_production.py\` - \`tests/test_api.py\` only if focused canonical-index fixtures require contract   alignment - this objective and its new handoff  Required evidence is TDD RED before production changes, then GREEN for the repository/HTTP/ReportWorkspace probes, the classification focused suite, frontend focused suite, \`tests/test_api.py -k artifacts\`, compileall, diff check, formal verify, and formal retrospective. The two known asynchronous \`tests/test_api.py -k artifacts\` fixture failures remain a known gate unless directly caused by this validator. Browser acceptance, external provider benchmark, central integration/cutover, host full gate, merge, tag, and release remain \`NOT VERIFIED\`.

## Final status

COMPLETED_WITH_KNOWN_GATES

## Metrics

- Failure frequency: 3/6 (50.0%; 50.0 per 100 events)
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

- #2 2026-08-20T00:15:39.000Z `classification_remediation_nine_red`; cause_status: `known`; cause: The repository artifacts-list reader accepted missing artifacts, noncanonical records, path escapes, invalid digests, duplicate identities, and tampered record structures; the HTTP boundary therefore returned 200 groups instead of the typed ARTIFACTS_INDEX_INVALID error.; resolution: `accepted`; lesson: Probe every canonical artifact-index invariant at the real repository and HTTP list seams before implementing the fail-closed validator.

## All errors

- #3 2026-08-20T00:21:18.000Z `classification_remediation_nine_fixture_alignment`; cause_status: `known`; cause: The first strict canonical reader run exposed one existing classification regression fixture with a deliberately generic artifact record that omitted ArtifactRecord.to_dict fields.; resolution: `resolved`; lesson: When tightening a shared reader, update only test fixtures that are proven noncanonical and keep the producer implementation untouched.
- #4 2026-08-20T00:21:30.000Z `classification_remediation_nine_api_known_gate`; cause_status: `known`; cause: The required tests/test_api.py -k artifacts selector still has two asynchronous completed-run fixture assertions where the generated report artifact is absent: report grouping and report_html download.; resolution: `accepted`; lesson: Keep asynchronous host fixture failures separate from direct artifacts-list contract evidence and do not modify the report producer to hide the known gate.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `classification-remediation-nine-api-known-gate`: occurrences=1; cause_status: `known`; root cause: The required tests/test_api.py -k artifacts selector still has two asynchronous completed-run fixture assertions where the generated report artifact is absent: report grouping and report_html download.; solution: `accepted`
- `classification-remediation-nine-fixture-alignment`: occurrences=1; cause_status: `known`; root cause: The first strict canonical reader run exposed one existing classification regression fixture with a deliberately generic artifact record that omitted ArtifactRecord.to_dict fields.; solution: `resolved`
- `classification-remediation-nine-red`: occurrences=1; cause_status: `known`; root cause: The repository artifacts-list reader accepted missing artifacts, noncanonical records, path escapes, invalid digests, duplicate identities, and tampered record structures; the HTTP boundary therefore returned 200 groups instead of the typed ARTIFACTS_INDEX_INVALID error.; solution: `accepted`

## Added tests

- No test evidence recorded.

## New rules

- `classification-remediation-nine-api-known-gate`: line experience occurrence(s)=1
- `classification-remediation-nine-fixture-alignment`: line experience occurrence(s)=1
- `classification-remediation-nine-red`: line experience occurrence(s)=1

## Future guidance

- Keep asynchronous host fixture failures separate from direct artifacts-list contract evidence and do not modify the report producer to hide the known gate.
- Probe every canonical artifact-index invariant at the real repository and HTTP list seams before implementing the fail-closed validator.
- When tightening a shared reader, update only test fixtures that are proven noncanonical and keep the producer implementation untouched.

## Event index

- #1: `2673d140-729b-44b9-b8cf-5df3a55a5a2b` | 2026-08-20T00:11:03.724Z | STATE_CHANGE/line_started | incident=`d9f18611-25b8-4b85-8ac8-d0dfca05d02b` | lesson_key=`frozen-context-before-start` | event_sha256=`c90dd1b115a50eb8f6ba420c3ab19f4e863cadb42e8afe394cef0c03285cde68`
- #2: `a1b2c3d4-e5f6-4789-ab01-23456789abcd` | 2026-08-20T00:15:39.000Z | FAILURE/classification_remediation_nine_red | incident=`b2c3d4e5-f6a7-4890-bc12-3456789abcde` | lesson_key=`classification-remediation-nine-red` | event_sha256=`cb43b42d19f7bef398747990f8c38c9ed13203f3dc6db9bc5786eaccfcba3eca`
- #3: `c3d4e5f6-a7b8-4901-bc23-456789abcdef` | 2026-08-20T00:21:18.000Z | ERROR/classification_remediation_nine_fixture_alignment | incident=`d4e5f6a7-b8c9-4012-cd34-56789abcdef0` | lesson_key=`classification-remediation-nine-fixture-alignment` | event_sha256=`a673625378c317065bfcea542f89cc880baa7e0fd83d8c774aedbc5d16974b4a`
- #4: `e5f6a7b8-c9d0-4123-ef45-6789abcdef01` | 2026-08-20T00:21:30.000Z | ERROR/classification_remediation_nine_api_known_gate | incident=`f6a7b8c9-d0e1-4234-f567-89abcdef0123` | lesson_key=`classification-remediation-nine-api-known-gate` | event_sha256=`5dc81c4171ad4a7e247a397a6fa41630304e385b5cf1a0d6d9fd0815ae85b666`
- #5: `f6a7b8c9-d0e1-4234-f567-89abcdef0123` | 2026-08-20T00:27:59.000Z | GATE/classification_remediation_nine_green | incident=`a7b8c9d0-e1f2-4345-6789-abcdef012345` | lesson_key=`classification-remediation-nine-green` | event_sha256=`c41b7ad2ac14c05d092836772c88576a250392cafbcc0b06ac56b0e13505605c`
- #6: `a8b9c0d1-e2f3-4456-789a-bcdef0123456` | 2026-08-20T00:28:30.000Z | STATE_CHANGE/classification_remediation_nine_terminal | incident=`b9c0d1e2-f3a4-4567-89ab-cdef01234567` | lesson_key=`classification-remediation-nine-terminal` | event_sha256=`f13bfe6bfa64771019cf1f3d6864cf00b10df910beece6c0d100e8d2c2b0ca05`
