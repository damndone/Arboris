# Retrospective — v1-8-9-p0-evidence-report-hardening-remediation-4

## Goal

# v1.8.9 P0 Evidence/Report Hardening — remediation-4 objective  ## Objective  Close the independent remediation-3 Evidence/Report boundary review findings without changing the central Agent/Notebook, provider, estimator, or live-host surfaces.  Report facts, projection, rendering, and persistence must be admitted by the exact C0 server-owned Report capability; malformed or caller-selected identity/provenance must fail closed to a typed bounded unavailable/blocked result before any writer or filesystem I/O.  ## Required outcomes  1. \`build_persisted_evidence_report_view\` and every Report fact/render/writer    entry require the exact live C0 host-admitted Report owner.  A missing owner,    \`object.__new__\` projection, caller-selected actor/project/session/scope/    confirmation, or caller-created request identity cannot produce facts or    reach writer/filesystem I/O.  Existing valid host HTTP and writer paths must    remain admitted through the controlled server-host harness. 2. Evidence index parsing must distinguish absent fields from present-but-empty    or invalid fields.  Outer and nested binding/envelope/provenance fields must    agree exactly; no truthy \`or\` fallback may hide an invalid outer value or a    partial/conflicting tamper. 3. The frontend consumes complete server-bound typed provenance, including the    canonical source/execution/validator/contract/projection/result identity    references.  A digest is a server-supplied evidence check, not client-side    authorization of a candidate pair.  Forged facts plus a caller-recomputed    digest are typed unavailable; raw classification remains display-only and    NON-CITABLE. 4. Preserve the strict append-only event timestamp/order policy and the    existing 17-pass event suite.  Every unavailable/blocked path exposes a    bounded reason code and empty facts.  ## TDD and verification  For each required outcome, add a real probe first, run it RED against the exact baseline, then make the smallest implementation change and run the probe GREEN. Run the focused backend authority/boundary/report/export suites, both event suites, frontend focused tests, frontend typecheck, Python compileall, diff check, and formal verify/retrospective.  Record exact counts and RED/GREEN evidence in the remediation-4 formal line.  ## Boundaries and gates  In scope: the typed evidence/report backend and frontend consumer seams, their focused tests, and remediation-4 objective/plan/handoff/formal records.  Protected: central Agent/Notebook routes and runtime, providers, estimator, live host, unrelated report behavior, root worktree, and every other worktree.  Do not install dependencies or alter deployment wiring.  Browser acceptance, external provider evidence, central integration, live production host wiring, full gate, release/tag/merge/push, and deployment remain \`NOT VERIFIED\`.

## Final status

COMPLETED

## Metrics

- Failure frequency: 7/19 (36.8%; 36.8 per 100 events)
- Repeat rate: 1/7 (14.3%)
- Recurrence rate: 1/6 (16.7%)
- MTTR: median=629440 ms (sample=7; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #4 2026-08-20T02:22:00.697Z `report_owner_and_wire_red`; cause_status: `known`; cause: Controlled RED probes showed a caller-created request identity reached the report view seam, object.__new__ projection handling was not typed, and invalid outer wire fields fell back to valid nested fields.; resolution: `open`; lesson: Require the exact owner-bound request identity and reject any present invalid or conflicting outer/nested evidence field before canonical projection.
- #7 2026-08-20T02:31:09.233Z `frontend_server_receipt_red`; cause_status: `known`; cause: The frontend parser accepted forged facts after the caller recomputed a self-consistent projection digest because it had no independent server receipt anchor.; resolution: `open`; lesson: Client parsing must compare the server-supplied receipt to the complete candidate identity and provenance; digest recomputation alone is not authorization.
- #9 2026-08-20T02:35:05.128Z `focused_suite_contract_update`; cause_status: `known`; cause: The full controlled focused suite found one stale assertion expecting the predecessor owner-context reason after the new missing-owner capability reason was intentionally introduced.; resolution: `open`; lesson: When a typed fail-closed reason becomes more precise, update the focused contract assertion and rerun the complete suite.
- #10 2026-08-20T02:44:54.855Z `frontend_focused_fixture_red`; cause_status: `known`; cause: The existing ReportView fixtures omitted the new server-bound receipt, so strict available-projection parsing correctly returned typed unavailable and legacy UI assertions failed.; resolution: `open`; lesson: Update valid Report fixtures to carry the server-issued receipt while preserving the production provenance gate.

## All errors

- #2 2026-08-20T02:19:03.432Z `unsupported_status_probe`; cause_status: `known`; cause: A read-only status probe used a command name that is not part of the formal CLI surface; the first append retry also supplied an event file outside the repository-relative input boundary.; resolution: `resolved`; lesson: Use only the documented formal control commands when inspecting a line.
- #3 2026-08-20T02:21:40.404Z `report_host_socket_environment_red`; cause_status: `external`; cause: The default sandbox rejected the real Unix authority socket bind before the remediation-4 probes reached their assertions.; resolution: `open`; lesson: Keep host socket permission failures separate from implementation RED/GREEN evidence and rerun the identical harness in a controlled environment.
- #12 2026-08-20T02:44:55.404Z `frontend_typecheck_red`; cause_status: `known`; cause: The strict frontend compiler rejected the parser's conversion from an unknown record to the complete server receipt identity type.; resolution: `open`; lesson: Resolve strict parser type errors with an explicit boundary cast and rerun the compiler.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `formal-cli-command-surface`: occurrences=1; cause_status: `known`; root cause: A read-only status probe used a command name that is not part of the formal CLI surface; the first append retry also supplied an event file outside the repository-relative input boundary.; solution: `resolved`
- `frontend-focused-fixture-contract`: occurrences=1; cause_status: `known`; root cause: The existing ReportView fixtures omitted the new server-bound receipt, so strict available-projection parsing correctly returned typed unavailable and legacy UI assertions failed.; solution: `open`
- `frontend-server-bound-provenance`: occurrences=1; cause_status: `known`; root cause: The frontend parser accepted forged facts after the caller recomputed a self-consistent projection digest because it had no independent server receipt anchor.; solution: `open`
- `report-host-socket-boundary`: occurrences=1; cause_status: `external`; root cause: The default sandbox rejected the real Unix authority socket bind before the remediation-4 probes reached their assertions.; solution: `open`
- `report-owner-proof-admission`: occurrences=2; cause_status: `known`; root cause: Controlled RED probes showed a caller-created request identity reached the report view seam, object.__new__ projection handling was not typed, and invalid outer wire fields fell back to valid nested fields.; solution: `open`
- `report-typecheck-contract-cast`: occurrences=1; cause_status: `known`; root cause: The strict frontend compiler rejected the parser's conversion from an unknown record to the complete server receipt identity type.; solution: `open`

## Added tests

- `backend focused suite (controlled host): 1 failed, 118 passed, 1 warning`
- `controlled backend evidence/report/export/event focused suite`
- `controlled host backend evidence boundary and focused suite`
- `controlled host backend evidence/report/export/event focused suite`
- `frontend focused ReportEvidenceBoundary, ReportWorkspaceContext, ReportView, FamilyEvidence, and TableView suites`
- `frontend/src/report/ReportEvidenceBoundary.v189.test.tsx and ReportWorkspaceContext.v189.test.tsx`
- `frontend/src/report/ReportEvidenceBoundary.v189.test.tsx::rejects a caller-rehashed forged facts pair without a server receipt`
- `frontend/src/report/ReportView.test.tsx focused run before receipt fixture update`
- `tests/test_v189_evidence_report_boundary.py -k remediation_four (controlled host)`
- `tests/test_v189_evidence_report_boundary.py -k remediation_four (default sandbox)`
- `tests/test_v189_evidence_report_boundary.py -k remediation_four_caller_created or remediation_four_object_new`
- `tests/test_v189_evidence_report_boundary.py -k remediation_four_present_invalid_outer`

## New rules

- `formal-cli-command-surface`: line experience occurrence(s)=1
- `frontend-focused-fixture-contract`: line experience occurrence(s)=1
- `frontend-server-bound-provenance`: line experience occurrence(s)=1
- `report-host-socket-boundary`: line experience occurrence(s)=1
- `report-owner-proof-admission`: line experience occurrence(s)=2
- `report-typecheck-contract-cast`: line experience occurrence(s)=1

## Future guidance

- Client parsing must compare the server-supplied receipt to the complete candidate identity and provenance; digest recomputation alone is not authorization.
- Close the owner admission incident only after negative probes and the real controlled positive host path both pass.
- Close typed contract errors only after a clean compiler run.
- Compare the independent server receipt against complete identity and canonical provenance at the frontend boundary.
- Keep host socket permission failures separate from implementation RED/GREEN evidence and rerun the identical harness in a controlled environment.
- Keep sandbox permission failures separate from implementation RED/GREEN evidence and rerun host probes in a controlled environment.
- Keep test fixtures aligned with the server-owned receipt contract instead of weakening runtime validation.
- Keep the server receipt separate from the candidate projection and validate the full typed provenance at the consumer boundary.
- Require the exact owner-bound request identity and reject any present invalid or conflicting outer/nested evidence field before canonical projection.
- Resolve strict parser type errors with an explicit boundary cast and rerun the compiler.
- Treat presence, validity, and equality as separate evidence admission checks; truthiness is not a provenance rule.
- Update a stale bounded-reason assertion and rerun the complete focused suite before closing the line.
- Update valid Report fixtures to carry the server-issued receipt while preserving the production provenance gate.
- Use identity-bound server capability admission at the typed Report view seam and preserve a controlled host positive path.
- Use only the documented formal control commands when inspecting a line.
- When a typed fail-closed reason becomes more precise, update the focused contract assertion and rerun the complete suite.

## Event index

- #1: `c2b24d93-c6a4-4526-ba28-4664bb21f95b` | 2026-08-20T02:17:32.550Z | STATE_CHANGE/line_started | incident=`75b256c0-ba11-41bf-9628-016a6e58954d` | lesson_key=`frozen-context-before-start` | event_sha256=`ccf771be0f955f10d8c83e2dd803371392965ac49ac495ad6e256e72a83d86ff`
- #2: `7dbf3b61-d4d1-4f94-93a4-2a8dbd9e7f41` | 2026-08-20T02:19:03.432Z | ERROR/unsupported_status_probe | incident=`8a1f5ad1-4e9e-44f7-9b2d-9c9af1b53e20` | lesson_key=`formal-cli-command-surface` | event_sha256=`996e78c344e1b5b6288008be5385132eec09df64780c17d544ee0980bacf0041`
- #3: `1e5c7b9a-1f6e-4d71-a2c3-6b8d9f0e4a12` | 2026-08-20T02:21:40.404Z | ERROR/report_host_socket_environment_red | incident=`a01b2c3d-4e5f-4678-9a0b-1c2d3e4f5a60` | lesson_key=`report-host-socket-boundary` | event_sha256=`22301b88e986dbffe9d93402039cac19d975371c7e8abe4c4627fc5ab31ef0d3`
- #4: `2f6a8c0e-5b7d-4a91-b3c2-7d9e1f0a6b54` | 2026-08-20T02:22:00.697Z | FAILURE/report_owner_and_wire_red | incident=`b12c3d4e-5f6a-4789-0b1c-2d3e4f5a6b70` | lesson_key=`report-owner-proof-admission` | event_sha256=`6ebf802523b46db402ad4c42754abc43e679545b92bd084d3ba8984be3e7f75e`
- #5: `3a7c9e1b-6d4f-4b82-90c1-5e7a2d8f0b63` | 2026-08-20T02:25:16.673Z | REVIEW/report_owner_request_green | incident=`c23d4e5f-6a7b-4890-1c2d-3e4f5a6b7c81` | lesson_key=`report-owner-proof-admission` | event_sha256=`c9f910b18b05e416d3b98ab1e90214d2a38e2709f751a48d322445408505e2f0`
- #6: `4b8d0f2a-7c5e-4913-a6b2-9d1f3e7c0a84` | 2026-08-20T02:28:14.959Z | REVIEW/strict_outer_nested_wire_green | incident=`d34e5f6a-7b8c-4901-2d3e-4f5a6b7c8d92` | lesson_key=`strict-outer-nested-evidence-wire` | event_sha256=`8c89f3ebe34a087627806b2fa9e8c733c707bb673acad56f6e47c7ad9df998b1`
- #7: `5c9e1a7b-3d6f-4e82-b0a1-7c5d9f2e4b86` | 2026-08-20T02:31:09.233Z | FAILURE/frontend_server_receipt_red | incident=`e45f6a7b-8c9d-4012-3e4f-5a6b7c8d9e03` | lesson_key=`frontend-server-bound-provenance` | event_sha256=`497b0a4cd50b7e109d691218c7b2358b581ff24bdf524f1cd1d6ab53f95e7eb8`
- #8: `6d0f2a8c-5e7b-4b91-a3c2-9e1f6d0a7b54` | 2026-08-20T02:34:02.809Z | REVIEW/frontend_server_receipt_green | incident=`f56a7b8c-9d0e-4123-4f5a-6b7c8d9e0a14` | lesson_key=`frontend-server-bound-provenance` | event_sha256=`7e004517399c7e230421468aa3f225c11943e10de695cc4a324823cab0303692`
- #9: `7e1a3c5d-9b2f-4d80-a6c1-8e5f2b7d0a94` | 2026-08-20T02:35:05.128Z | FAILURE/focused_suite_contract_update | incident=`f67b8c9d-0e1a-4234-5f6b-7c8d9e0a1b25` | lesson_key=`report-owner-proof-admission` | event_sha256=`a681ace0593c7da33a8fe3fbca1b307e8fa4f060c6776ce43d3874e5df6b1a3d`
- #10: `3f9e7d1c-5b2a-4a68-9c01-7e4d2b8f6a35` | 2026-08-20T02:44:54.855Z | FAILURE/frontend_focused_fixture_red | incident=`4a1e7c9b-3d5f-4b82-9e06-1c7a5d2f8b34` | lesson_key=`frontend-focused-fixture-contract` | event_sha256=`a757094170eb34ba25a5d6aaa7a8db4e64261f7446f3ed8fa6ba52bb6984f60e`
- #11: `4a2f8e6c-1d7b-49f0-a352-8c5e7b9d2f14` | 2026-08-20T02:44:55.118Z | REVIEW/frontend_focused_fixture_green | incident=`4a1e7c9b-3d5f-4b82-9e06-1c7a5d2f8b34` | lesson_key=`frontend-focused-fixture-contract` | event_sha256=`da90922948794e9716c8d11fc05c402d0a6bed38323fa06fb5105ec73975ffdf`
- #12: `5b3c9f7d-2e8a-40b1-a463-9d6f8c0e3a25` | 2026-08-20T02:44:55.404Z | ERROR/frontend_typecheck_red | incident=`5b2c8e7a-1d4f-49b0-a635-7c9e2f8a4d16` | lesson_key=`report-typecheck-contract-cast` | event_sha256=`0f053cf9df2edb18fdc26aaf31d42abae849ca1810153c696fe17bc0ee506d93`
- #13: `6c4d0a8e-3f9b-41c2-b574-0e7a9d1f5b26` | 2026-08-20T02:44:55.681Z | REVIEW/frontend_typecheck_green | incident=`5b2c8e7a-1d4f-49b0-a635-7c9e2f8a4d16` | lesson_key=`report-typecheck-contract-cast` | event_sha256=`a826e06884f8e88bb3f43a4dfc56b96c80c9562c84279c049d40ddf65a951bf2`
- #14: `7d5e1b9f-4a0c-42d3-c685-1f8b0a2e6c37` | 2026-08-20T02:44:55.945Z | REVIEW/report_host_socket_boundary_resolved | incident=`a01b2c3d-4e5f-4678-9a0b-1c2d3e4f5a60` | lesson_key=`report-host-socket-boundary` | event_sha256=`c0f6615fe716f9640d21e1ce7a2ee49ef51df9ea99910afdf8d3be550bf58253`
- #15: `8e6f2c0a-5b1d-43e4-d796-2a9c1b3f7d48` | 2026-08-20T02:44:56.195Z | REVIEW/report_owner_and_wire_green_gate | incident=`b12c3d4e-5f6a-4789-0b1c-2d3e4f5a6b70` | lesson_key=`report-owner-proof-admission` | event_sha256=`db5e496dc51610be9983954b8dedd317f64eace3ca7eb13275fd696d23ca49ec`
- #16: `9f7a3d1b-6c2e-44f5-e807-3bad2c4e8f59` | 2026-08-20T02:45:34.316Z | REVIEW/report_frontend_receipt_green_gate | incident=`e45f6a7b-8c9d-4012-3e4f-5a6b7c8d9e03` | lesson_key=`frontend-server-bound-provenance` | event_sha256=`ee55e1bb3e28595636ce655947bb8b85ca233d30ce8434b4d4c34521047d8304`
- #17: `0a8b4c2d-7e3f-45f6-8901-4c6d2e8a0b17` | 2026-08-20T02:45:34.568Z | REVIEW/report_focused_suite_green | incident=`f67b8c9d-0e1a-4234-5f6b-7c8d9e0a1b25` | lesson_key=`report-owner-proof-admission` | event_sha256=`34e41a2b9b1d535d8693dd56db594c8f97f1366c8dab15ab061e1b25285e27d6`
- #18: `1b9c5d3e-8f4a-46b7-9012-5d7e3f9b1c28` | 2026-08-20T02:45:34.814Z | GATE/report_remediation_focused_gate | incident=`2c0e6a4f-9b5d-47a8-0123-6e8f4a0c2d39` | lesson_key=`report-remediation-focused-gate` | event_sha256=`c54c456a5b1a26d5c67aef09d0684a1283c034a1994e40af251a69b23da34a57`
- #19: `2c0e6a4f-9b5d-47a8-0123-6e8f4a0c2d40` | 2026-08-20T02:46:07.084Z | STATE_CHANGE/line_completed | incident=`2c0e6a4f-9b5d-47a8-0123-6e8f4a0c2d40` | lesson_key=`report-remediation-line-complete` | event_sha256=`f7a151442a25704441c2dd2125312de3e92947c30d7e2ad21a6cc0c75364937b`
