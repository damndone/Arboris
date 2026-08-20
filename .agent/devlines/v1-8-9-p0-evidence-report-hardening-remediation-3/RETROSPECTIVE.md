# Retrospective — v1-8-9-p0-evidence-report-hardening-remediation-3

## Goal

# Workbench v1.8.9 P0 Evidence/Report Remediation 3  Remediate the remaining independent-review \`NOT COMPLIANT\` findings from the exact closeout baseline \`363812ee8063cd61b12ca82750b777e002a0e782\` in the existing evidence/report hardening worktree. This is a new formal line; do not edit the predecessor formal line or its records.  Required TDD outcomes:  1. Remove the importable \`_REPORT_OWNER_FACTORY_TOKEN\` and    \`_REPORT_FACTORY_TOKEN\` trust roots. Report owner construction must require    the existing C0/deployment \`HostAuthorityEndpointV1\` and a host-issued    opaque proof bound to the report purpose, scope, subject, canonical root and    payload. Caller-selected resolver/config/token, JSON/pickle/object.__new__    and same-process forged objects must fail closed before projection, writer,    or any XLSX/HTML/PDF/filesystem IO. Add real untrusted import probes and a    controlled server-host harness probe that obtains the capability through the    existing host channel. 2. Make every required provenance field strict and canonical: artifact,    run/model/result identity, source/admission, commit, envelope, confirmation,    and projection digest must be present and mutually consistent. Missing,    partial, tampered, and self-consistent forged provenance returns typed    unavailable/blocked and never becomes Report facts or writer input. Reuse    the existing canonical digest semantics. 3. Keep classification/raw artifact JSON in \`ReportWorkspaceContext\` strictly    display-only NON-CITABLE compatibility state. It must not enter formal    evidence facts, writer input, or LLM context. Add a real Report render and    selection-path probe. 4. Preserve the server-generated strict append timestamp strategy and the    existing \`tests/test_events.py\` plus \`tests/test_devline_control_events.py\`    17-pass behavior.  Protected boundaries: do not modify central Agent, Notebook, provider, estimator, or live-host execution code. Browser, provider production wiring, central integration, host acceptance, full-gate, and release acceptance remain NOT VERIFIED.

## Final status

COMPLETED

## Metrics

- Failure frequency: 12/42 (28.6%; 28.6 per 100 events)
- Repeat rate: 1/12 (8.3%)
- Recurrence rate: 1/11 (9.1%)
- MTTR: median=58000 ms (sample=11; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0; coverage=0/1)

## All failures

- #4 2026-08-20T00:57:40.643Z `report_host_factory_authority_red`; cause_status: `known`; cause: The Report owner still trusted an importable module object and accepted a caller-invoked _from_host path without a host-issued report proof.; resolution: `open`; lesson: Bind Report owner admission to the existing host-issued opaque capability, never to an importable module object.
- #7 2026-08-20T01:30:40.000Z `report_config_owner_admission_red`; cause_status: `known`; cause: The global Report persistence configuration accepted an object.__new__ copy of a valid owner without rechecking host admission.; resolution: `open`; lesson: Every Report persistence installation boundary must revalidate the exact host-admitted owner before state mutation.
- #11 2026-08-20T01:40:02.000Z `report_provenance_red`; cause_status: `known`; cause: TDD probes for missing outer source, validator, execution, and contract provenance fields failed before the canonical admission guard was implemented.; resolution: `open`; lesson: Require every canonical provenance field before loading or projecting server-owned facts.
- #13 2026-08-20T01:40:04.000Z `frontend_provenance_red`; cause_status: `known`; cause: The frontend TDD probe accepted a self-consistent projection when required provenance was incomplete or its identity disagreed with the candidate.; resolution: `open`; lesson: Validate required provenance structure and identity bindings before exposing projection facts to Report UI selection.
- #15 2026-08-20T01:40:06.000Z `report_raw_display_red`; cause_status: `known`; cause: The Report render/selection probe initially lacked an explicit NON-CITABLE classification display boundary for raw compatibility JSON.; resolution: `open`; lesson: Test raw compatibility data through the actual Report render and LLM selection path, not only through isolated helpers.
- #17 2026-08-20T01:40:08.000Z `report_unavailable_provenance_red`; cause_status: `known`; cause: The typed unavailable Report view omitted the required provenance field names even though it correctly contained no facts.; resolution: `open`; lesson: Keep unavailable output shape-complete with explicit sentinel fields while retaining zero facts.

## All errors

- #3 2026-08-20T00:53:51.108Z `formal_start_tag_rejected`; cause_status: `known`; cause: The second remediation-3 start invocation used a dotted display tag, but formal tags require normalized identifiers.; resolution: `resolved`; lesson: Use normalized hyphenated identifiers for formal tags before starting a line.
- #5 2026-08-20T00:57:44.304Z `report_host_harness_socket_boundary`; cause_status: `external`; cause: The controlled server-host harness could not bind its real Unix authority socket in the default sandbox.; resolution: `open`; lesson: Separate host socket permissions from Report authority behavior and rerun the real host harness with controlled permissions.
- #6 2026-08-20T01:00:00.000Z `report_host_harness_setup_error`; cause_status: `known`; cause: The controlled host probe passed the socket boundary but its temporary persistence directory was not created before FD admission.; resolution: `resolved`; lesson: Create the controlled persistence root before invoking the FD-safe admission seam.
- #19 2026-08-20T01:40:10.000Z `report_fixture_authority_lifetime`; cause_status: `known`; cause: The first full focused backend run rendered owner-issued export fixtures after their persistence admission context had closed; live authority revalidation correctly rejected those stale fixtures.; resolution: `open`; lesson: Keep controlled host authority and persistence admission alive through the entire IO assertion, then close it at process exit.
- #21 2026-08-20T01:40:12.000Z `report_typecheck_contract_cast`; cause_status: `known`; cause: After making citable provenance fields required in TypeScript, the parser's deliberate runtime narrowing cast needed an explicit unknown boundary.; resolution: `open`; lesson: Run typecheck immediately after tightening public typed contracts and keep parser casts explicit.
- #42 2026-08-20T01:58:22.391Z `report_host_socket_environment_final`; cause_status: `external`; cause: The final default-sandbox backend focused rerun hit the known Unix socket permission boundary; the identical command passed in the controlled socket-capable environment.; resolution: `resolved`; lesson: Keep host socket permission boundaries separate from implementation results and record the controlled rerun.

## All gaps

- None recorded.

## All waste

- #2 2026-08-20T00:53:21.572Z `formal_start_argument_quoting`; cause_status: `known`; cause: The first remediation-3 start invocation passed test strings without shell quoting, so the formal CLI parsed embedded spaces as extra arguments.; resolution: `resolved`; lesson: Shell-quote every formal CLI value that contains spaces before invoking start.

## Root causes and solutions

- `formal-start-argument-quoting`: occurrences=1; cause_status: `known`; root cause: The first remediation-3 start invocation passed test strings without shell quoting, so the formal CLI parsed embedded spaces as extra arguments.; solution: `resolved`
- `formal-start-normalized-tag`: occurrences=1; cause_status: `known`; root cause: The second remediation-3 start invocation used a dotted display tag, but formal tags require normalized identifiers.; solution: `resolved`
- `frontend-provenance-red`: occurrences=1; cause_status: `known`; root cause: The frontend TDD probe accepted a self-consistent projection when required provenance was incomplete or its identity disagreed with the candidate.; solution: `open`
- `report-config-owner-admission-red`: occurrences=1; cause_status: `known`; root cause: The global Report persistence configuration accepted an object.__new__ copy of a valid owner without rechecking host admission.; solution: `open`
- `report-fixture-authority-lifetime`: occurrences=1; cause_status: `known`; root cause: The first full focused backend run rendered owner-issued export fixtures after their persistence admission context had closed; live authority revalidation correctly rejected those stale fixtures.; solution: `open`
- `report-host-authority-red`: occurrences=1; cause_status: `known`; root cause: The Report owner still trusted an importable module object and accepted a caller-invoked _from_host path without a host-issued report proof.; solution: `open`
- `report-host-harness-setup`: occurrences=1; cause_status: `known`; root cause: The controlled host probe passed the socket boundary but its temporary persistence directory was not created before FD admission.; solution: `resolved`
- `report-host-socket-boundary`: occurrences=2; cause_status: `external`; root cause: The controlled server-host harness could not bind its real Unix authority socket in the default sandbox.; solution: `open`
- `report-provenance-red`: occurrences=1; cause_status: `known`; root cause: TDD probes for missing outer source, validator, execution, and contract provenance fields failed before the canonical admission guard was implemented.; solution: `open`
- `report-raw-display-red`: occurrences=1; cause_status: `known`; root cause: The Report render/selection probe initially lacked an explicit NON-CITABLE classification display boundary for raw compatibility JSON.; solution: `open`
- `report-typecheck-contract-cast`: occurrences=1; cause_status: `known`; root cause: After making citable provenance fields required in TypeScript, the parser's deliberate runtime narrowing cast needed an explicit unknown boundary.; solution: `open`
- `report-unavailable-provenance-red`: occurrences=1; cause_status: `known`; root cause: The typed unavailable Report view omitted the required provenance field names even though it correctly contained no facts.; solution: `open`

## Added tests

- `frontend/src/report/ReportEvidenceBoundary.v189.test.tsx`
- `frontend/src/report/ReportEvidenceBoundary.v189.test.tsx::rejects a self-consistent digest when canonical provenance is incomplete`
- `frontend/src/report/ReportEvidenceBoundary.v189.test.tsx::wires the real ReportView path to the typed FamilyEvidence projection`
- `frontend/src/report/ReportWorkspaceContext.v189.test.tsx::keeps raw classification JSON display-only and out of selected facts and LLM context`
- `tests/test_report_export.py tests/test_reporting.py tests/test_reporting_exports.py`
- `tests/test_v189_evidence_report_boundary.py export owner fixture helpers`
- `tests/test_v189_evidence_report_boundary.py::test_remediation_three_configuration_rejects_object_new_owner`
- `tests/test_v189_evidence_report_boundary.py::test_remediation_three_controlled_server_host_harness_issues_report_owner`
- `tests/test_v189_evidence_report_boundary.py::test_remediation_three_imported_factory_roots_and_untrusted_owner_fail_before_io`
- `tests/test_v189_evidence_report_boundary.py::test_remediation_three_outer_index_missing_provenance_is_unavailable`
- `tests/test_v189_evidence_report_boundary.py::test_remediation_three_report_provenance_is_complete_and_canonical`
- `tests/test_v189_evidence_report_boundary.py::test_unbound_projection_is_unavailable_without_server_identity_and_admission`

## New rules

- `formal-start-argument-quoting`: line experience occurrence(s)=1
- `formal-start-normalized-tag`: line experience occurrence(s)=1
- `frontend-provenance-red`: line experience occurrence(s)=1
- `report-config-owner-admission-red`: line experience occurrence(s)=1
- `report-fixture-authority-lifetime`: line experience occurrence(s)=1
- `report-host-authority-red`: line experience occurrence(s)=1
- `report-host-harness-setup`: line experience occurrence(s)=1
- `report-host-socket-boundary`: line experience occurrence(s)=2
- `report-provenance-red`: line experience occurrence(s)=1
- `report-raw-display-red`: line experience occurrence(s)=1
- `report-typecheck-contract-cast`: line experience occurrence(s)=1
- `report-unavailable-provenance-red`: line experience occurrence(s)=1

## Future guidance

- Bind Report owner admission to the existing host-issued opaque capability, never to an importable module object.
- Close provenance incidents only after both negative and canonical positive paths are exercised.
- Close provenance incidents only after negative and canonical positive paths are both exercised.
- Close raw-data bypasses only with an end-to-end selection-path probe, not a render-only assertion.
- Close typed contract errors only after a clean compiler run, not after a focused runtime suite alone.
- Compare outer provenance with the admitted server record rather than trusting payload or index self-consistency.
- Create the controlled persistence root before invoking the FD-safe admission seam.
- Every Report persistence installation boundary must revalidate the exact host-admitted owner before state mutation.
- Keep controlled host authority and persistence admission alive through the entire IO assertion, then close it at process exit.
- Keep environment boundaries explicit and rerun host probes in a controlled socket-capable environment.
- Keep environment boundaries explicit even after controlled reruns pass.
- Keep host socket permission boundaries separate from implementation results and record the controlled rerun.
- Keep the frontend projection reader as a strict canonical parser, not a best-effort JSON adapter.
- Keep type-level required provenance aligned with the runtime fail-closed parser.
- Keep unavailable output shape-complete with explicit sentinel fields while retaining zero facts.
- Make fail-closed output explicit and structurally stable for every consumer.
- Make frontend provenance failure observable as typed unavailability rather than partial facts.
- Preserve compatibility reads only behind an explicit non-citable branch and assert the downstream request boundary.
- Represent missing evidence explicitly and completely while preserving the fail-closed fact boundary.
- Require every canonical provenance field before loading or projecting server-owned facts.
- Resolve trust-root findings with a real host capability probe and explicit pre-IO rejection.
- Revalidate live owner admission at every installation boundary, not only at construction.
- Revalidate the exact host-admitted owner at every Report persistence installation boundary.
- Run typecheck immediately after tightening public typed contracts and keep parser casts explicit.
- Separate host socket permissions from Report authority behavior and rerun the real host harness with controlled permissions.
- Shell-quote every formal CLI value that contains spaces before invoking start.
- Test fixtures must model the same live capability lifetime required by production IO boundaries.
- Test raw compatibility data through the actual Report render and LLM selection path, not only through isolated helpers.
- Treat a live capability lifetime as part of the test contract when asserting filesystem IO.
- Treat live capability lifetime as part of the test contract when asserting filesystem IO.
- Use normalized hyphenated identifiers for formal tags before starting a line.
- Validate required provenance structure and identity bindings before exposing projection facts to Report UI selection.
- Verify the real host-issued capability path separately from local owner-shaped test fixtures.

## Event index

- #1: `df65b764-d7c9-48fa-a695-c66ab0ed5825` | 2026-08-20T00:52:08.774Z | STATE_CHANGE/line_started | incident=`0f9d6274-78f9-407b-901c-81f14dc366ae` | lesson_key=`frozen-context-before-start` | event_sha256=`b0362d594062bf06fbd51e83d659e42f0d69ed3d18e5390317654d59d85a1eca`
- #2: `c7d8e9f0-1234-4abc-8def-0123456789ab` | 2026-08-20T00:53:21.572Z | WASTE/formal_start_argument_quoting | incident=`12345678-90ab-4cde-8123-4567890abcde` | lesson_key=`formal-start-argument-quoting` | event_sha256=`17fa672a34b54b1f459632b4b4e915741089de107e8b8fa6caefc7f44eaaf3a2`
- #3: `d8e9f012-3456-4abc-8def-0123456789ab` | 2026-08-20T00:53:51.108Z | ERROR/formal_start_tag_rejected | incident=`23456789-0abc-4def-8123-4567890abcde` | lesson_key=`formal-start-normalized-tag` | event_sha256=`a7173abb44082b9efa793831353b9081326541be9e70efd028202b86b0e6d8d6`
- #4: `e9012345-6789-4abc-8def-0123456789ab` | 2026-08-20T00:57:40.643Z | FAILURE/report_host_factory_authority_red | incident=`34567890-abcd-4ef0-8123-4567890abcde` | lesson_key=`report-host-authority-red` | event_sha256=`6fffd2a00661366eaa8ea24492871c6322dc95f305847e2502204f372f964866`
- #5: `f0123456-789a-4bcd-8ef0-123456789abc` | 2026-08-20T00:57:44.304Z | ERROR/report_host_harness_socket_boundary | incident=`4567890a-bcde-4f01-8123-4567890abcde` | lesson_key=`report-host-socket-boundary` | event_sha256=`928d5f12dc264a55c20043c7e732d198e0e6b00b8f19a2c83639ab13983e6b5f`
- #6: `567890ab-cdef-4012-9234-567890abcdef` | 2026-08-20T01:00:00.000Z | ERROR/report_host_harness_setup_error | incident=`67890abc-def0-4123-9234-567890abcdef` | lesson_key=`report-host-harness-setup` | event_sha256=`9482240abf6a89e06b8b15cacaa5b03fc71d04121b43cccde930e1cf7087c58c`
- #7: `7890abcd-ef12-4abc-9def-0123456789ab` | 2026-08-20T01:30:40.000Z | FAILURE/report_config_owner_admission_red | incident=`89abcdef-0123-4abc-9def-0123456789ab` | lesson_key=`report-config-owner-admission-red` | event_sha256=`72222c9bbed3b9d7dff6096a2aba743a0cee69b9aeeaf194deb8bc652dcf5650`
- #8: `8abcdef0-1234-4abc-9def-0123456789ab` | 2026-08-20T01:36:12.000Z | REVIEW/report_config_owner_admission_green | incident=`9abcdef0-1234-4abc-9def-0123456789ab` | lesson_key=`report-config-owner-admission-green` | event_sha256=`d4b13bb7eb5f8831f1851c799cf800b32e3917600b7e54e2e68779a2f0b6325c`
- #9: `abcdef01-2345-4abc-9def-0123456789ab` | 2026-08-20T01:40:00.000Z | REVIEW/report_host_authority_green | incident=`abcdef12-3456-4abc-9def-0123456789ab` | lesson_key=`report-host-authority-green` | event_sha256=`af824b3c5979fdcf6cd96d0437b403bd1597a5b0fc5be1fe34dd03f29c4ac1c6`
- #10: `abcdef02-2345-4abc-9def-0123456789ab` | 2026-08-20T01:40:01.000Z | GATE/report_host_socket_green | incident=`abcdef23-3456-4abc-9def-0123456789ab` | lesson_key=`report-host-socket-green` | event_sha256=`8c24f32be0bc413c8643f00142aebbf96f98b2a112c0ae5984f27a58bf20a1e0`
- #11: `abcdef03-2345-4abc-9def-0123456789ab` | 2026-08-20T01:40:02.000Z | FAILURE/report_provenance_red | incident=`abcdef34-3456-4abc-9def-0123456789ab` | lesson_key=`report-provenance-red` | event_sha256=`adbc65c1a2bce79e9cddef045ac24bf8517a5803b48e2e361972d75c7478049d`
- #12: `abcdef04-2345-4abc-9def-0123456789ab` | 2026-08-20T01:40:03.000Z | REVIEW/report_provenance_green | incident=`abcdef45-3456-4abc-9def-0123456789ab` | lesson_key=`report-provenance-green` | event_sha256=`60ba9c5b80d57863acc33a89f027b078216440ef91c75e823767d8bd25154e43`
- #13: `abcdef05-2345-4abc-9def-0123456789ab` | 2026-08-20T01:40:04.000Z | FAILURE/frontend_provenance_red | incident=`abcdef56-3456-4abc-9def-0123456789ab` | lesson_key=`frontend-provenance-red` | event_sha256=`17a5c88200412883fcf73a989f50bc0336d09d9e32d6e30707c98b1bf897acd9`
- #14: `abcdef06-2345-4abc-9def-0123456789ab` | 2026-08-20T01:40:05.000Z | REVIEW/frontend_provenance_green | incident=`abcdef67-3456-4abc-9def-0123456789ab` | lesson_key=`frontend-provenance-green` | event_sha256=`82f6e91347fe497f8f3e9e72cbc1e1dc79fb00f0b8fb499112f3ec101200563e`
- #15: `abcdef07-2345-4abc-9def-0123456789ab` | 2026-08-20T01:40:06.000Z | FAILURE/report_raw_display_red | incident=`abcdef78-3456-4abc-9def-0123456789ab` | lesson_key=`report-raw-display-red` | event_sha256=`8cdf06c4e358c30d16b9b9789e6a5d74519080142e585947074939d52cdd28a8`
- #16: `abcdef08-2345-4abc-9def-0123456789ab` | 2026-08-20T01:40:07.000Z | REVIEW/report_raw_display_green | incident=`abcdef89-3456-4abc-9def-0123456789ab` | lesson_key=`report-raw-display-green` | event_sha256=`6ad63b34cd3e49e06911d11c21e700d87c64374d112ca38f3c3f3e6bde5f1139`
- #17: `abcdef09-2345-4abc-9def-0123456789ab` | 2026-08-20T01:40:08.000Z | FAILURE/report_unavailable_provenance_red | incident=`abcdef10-3456-4abc-9def-0123456789ab` | lesson_key=`report-unavailable-provenance-red` | event_sha256=`a5531eb561a5f5d38eb56a74cf17aed5f07f96410a2741d8c76565c2fbf8072f`
- #18: `abcdef11-2345-4abc-9def-0123456789ab` | 2026-08-20T01:40:09.000Z | REVIEW/report_unavailable_provenance_green | incident=`abcdef12-3456-4abc-9def-0123456789ab` | lesson_key=`report-unavailable-provenance-green` | event_sha256=`ee4c79735400ae9ce737a26c9399fae340e01bd5145acdf2e0968922be1d3e94`
- #19: `abcdef13-2345-4abc-9def-0123456789ab` | 2026-08-20T01:40:10.000Z | ERROR/report_fixture_authority_lifetime | incident=`abcdef14-3456-4abc-9def-0123456789ab` | lesson_key=`report-fixture-authority-lifetime` | event_sha256=`eabfe6b798933555868bc5c62914bdea778fd327531dae4a7b08444adad1677f`
- #20: `abcdef15-2345-4abc-9def-0123456789ab` | 2026-08-20T01:40:11.000Z | REVIEW/report_fixture_authority_lifetime_green | incident=`abcdef16-3456-4abc-9def-0123456789ab` | lesson_key=`report-fixture-authority-lifetime-green` | event_sha256=`97c086c0841641cad42c441b8e1556d054de3da6239c9b1d6631cab83c6d76ef`
- #21: `abcdef17-2345-4abc-9def-0123456789ab` | 2026-08-20T01:40:12.000Z | ERROR/report_typecheck_contract_cast | incident=`abcdef18-3456-4abc-9def-0123456789ab` | lesson_key=`report-typecheck-contract-cast` | event_sha256=`1645c5802b70f4a5724350442043145b7497571f72bf6dfb866405ec57642151`
- #22: `abcdef19-2345-4abc-9def-0123456789ab` | 2026-08-20T01:40:13.000Z | REVIEW/report_typecheck_contract_cast_green | incident=`abcdef20-3456-4abc-9def-0123456789ab` | lesson_key=`report-typecheck-contract-cast-green` | event_sha256=`9956d0604d59098b6fcaae254ffbd6316942b70c04b005155b2ddb242797fe14`
- #23: `abcdef21-2345-4abc-9def-0123456789ab` | 2026-08-20T01:41:00.000Z | REVIEW/report_host_authority_resolved | incident=`34567890-abcd-4ef0-8123-4567890abcde` | lesson_key=`report-host-authority-resolved` | event_sha256=`1ea392e7905b9cfb047c43c52683b1f1118d98c38029a63382a4f52c7f9d4532`
- #24: `abcdef22-2345-4abc-9def-0123456789ab` | 2026-08-20T01:41:01.000Z | REVIEW/report_host_socket_resolved | incident=`4567890a-bcde-4f01-8123-4567890abcde` | lesson_key=`report-host-socket-resolved` | event_sha256=`0982dcb1a228a0e0aad521884c0d744cada4d18d25c31948ed501fefd0d664a6`
- #25: `abcdef23-2345-4abc-9def-0123456789ab` | 2026-08-20T01:41:02.000Z | REVIEW/report_provenance_resolved | incident=`abcdef34-3456-4abc-9def-0123456789ab` | lesson_key=`report-provenance-resolved` | event_sha256=`5383e7908496a0ff923e2aface1705f4371c8d689eb14f1ebf1723fb0370c78b`
- #26: `abcdef24-2345-4abc-9def-0123456789ab` | 2026-08-20T01:41:03.000Z | REVIEW/frontend_provenance_resolved | incident=`abcdef56-3456-4abc-9def-0123456789ab` | lesson_key=`frontend-provenance-resolved` | event_sha256=`21609f962c9106f87dbe3c3e78008d93671f8a6cda9197e6494fec96341b77cb`
- #27: `abcdef25-2345-4abc-9def-0123456789ab` | 2026-08-20T01:41:04.000Z | REVIEW/report_raw_display_resolved | incident=`abcdef78-3456-4abc-9def-0123456789ab` | lesson_key=`report-raw-display-resolved` | event_sha256=`27bb9446c2ba6c2db0699c6d6bd2b42c000c54bf9fbc8f1e3581137ae8e2d4d1`
- #28: `abcdef26-2345-4abc-9def-0123456789ab` | 2026-08-20T01:41:05.000Z | REVIEW/report_unavailable_provenance_resolved | incident=`abcdef10-3456-4abc-9def-0123456789ab` | lesson_key=`report-unavailable-provenance-resolved` | event_sha256=`32f971cc3243e565e3a7ee4a3cf31f75b751b3d771c6a66a69e4ace156793766`
- #29: `abcdef27-2345-4abc-9def-0123456789ab` | 2026-08-20T01:41:06.000Z | REVIEW/report_fixture_authority_lifetime_resolved | incident=`abcdef14-3456-4abc-9def-0123456789ab` | lesson_key=`report-fixture-authority-lifetime-resolved` | event_sha256=`a28a8c179e55c6b4872fcddf77230d2d60afedd4fc153506d81f7c8be972866e`
- #30: `abcdef28-2345-4abc-9def-0123456789ab` | 2026-08-20T01:41:07.000Z | REVIEW/report_typecheck_contract_resolved | incident=`abcdef18-3456-4abc-9def-0123456789ab` | lesson_key=`report-typecheck-contract-resolved` | event_sha256=`93a8fddfcfa73e2167cfa77e51a3620fd3743ea3df9a027f2489306401700686`
- #31: `abcdef29-2345-4abc-9def-0123456789ab` | 2026-08-20T01:44:35.000Z | GATE/report_remediation_focused_gate | incident=`abcdef30-3456-4abc-9def-0123456789ab` | lesson_key=`report-remediation-focused-gate` | event_sha256=`6ab32594a7a04e7a36856502e20d462ac96864f9dfb0fb6a5f828aff81fd2dd1`
- #32: `abcdef31-2345-4abc-9def-0123456789ab` | 2026-08-20T01:44:36.000Z | STATE_CHANGE/line_completed | incident=`abcdef32-3456-4abc-9def-0123456789ab` | lesson_key=`report-remediation-line-complete` | event_sha256=`54101472ff5a879b67ed41f694a277519d713d3a2811c9db71555319e8f1045e`
- #33: `abcdef33-2345-4abc-9def-0123456789ab` | 2026-08-20T01:53:38.265Z | REVIEW/report_host_authority_red_resolved | incident=`34567890-abcd-4ef0-8123-4567890abcde` | lesson_key=`report-host-authority-red` | event_sha256=`0b9c13d29719b0d0dc186af44ad6efefdb48ed56ac90654a3115e8d7907a7726`
- #34: `abcdef34-2345-4abc-9def-0123456789ab` | 2026-08-20T01:53:54.870Z | REVIEW/report_host_socket_boundary_resolved | incident=`4567890a-bcde-4f01-8123-4567890abcde` | lesson_key=`report-host-socket-boundary` | event_sha256=`334399db596073bdd8d4f38e618d96a6f3dec5e8988ca3ced814dd165a121b8b`
- #35: `abcdef35-2345-4abc-9def-0123456789ab` | 2026-08-20T01:54:30.541Z | REVIEW/report_config_owner_admission_red_resolved | incident=`89abcdef-0123-4abc-9def-0123456789ab` | lesson_key=`report-config-owner-admission-red` | event_sha256=`f7dbd1692f885939c549f32b6373078ebff06233a765a35154a6027a30eeadcc`
- #36: `abcdef36-2345-4abc-9def-0123456789ab` | 2026-08-20T01:54:30.589Z | REVIEW/report_provenance_red_resolved | incident=`abcdef34-3456-4abc-9def-0123456789ab` | lesson_key=`report-provenance-red` | event_sha256=`0787ae3f31b0d8a3efcfd4e54106e6c1b5efae26e9fb8ef66af19d0e3a14c546`
- #37: `abcdef37-2345-4abc-9def-0123456789ab` | 2026-08-20T01:54:30.638Z | REVIEW/frontend_provenance_red_resolved | incident=`abcdef56-3456-4abc-9def-0123456789ab` | lesson_key=`frontend-provenance-red` | event_sha256=`dca0fcd52d33ad442eaeb200884a73a2ec0ab4520ceb5beb92abd1dd2199ff28`
- #38: `abcdef38-2345-4abc-9def-0123456789ab` | 2026-08-20T01:54:30.689Z | REVIEW/report_raw_display_red_resolved | incident=`abcdef78-3456-4abc-9def-0123456789ab` | lesson_key=`report-raw-display-red` | event_sha256=`18c444d5f2b7e952940593e71892296127942017af9426192e0ec1fdfb7bd94e`
- #39: `abcdef39-2345-4abc-9def-0123456789ab` | 2026-08-20T01:54:30.737Z | REVIEW/report_unavailable_provenance_red_resolved | incident=`abcdef10-3456-4abc-9def-0123456789ab` | lesson_key=`report-unavailable-provenance-red` | event_sha256=`96f91579042b322639825cb26c80117823bc853f510f5d7ef04d5b293eae04b6`
- #40: `abcdef40-2345-4abc-9def-0123456789ab` | 2026-08-20T01:54:30.786Z | REVIEW/report_fixture_authority_lifetime_resolved | incident=`abcdef14-3456-4abc-9def-0123456789ab` | lesson_key=`report-fixture-authority-lifetime` | event_sha256=`1972669620cb43455cc64612028c7f3c726daf9aeb773064d63a322e68b5f7bf`
- #41: `abcdef41-2345-4abc-9def-0123456789ab` | 2026-08-20T01:54:30.835Z | REVIEW/report_typecheck_contract_cast_resolved | incident=`abcdef18-3456-4abc-9def-0123456789ab` | lesson_key=`report-typecheck-contract-cast` | event_sha256=`4cb9551410b5a81364df106a8c4a3f94392a9f5b0406e9258a3aa2e967222e68`
- #42: `abcdef42-2345-4abc-9def-0123456789ab` | 2026-08-20T01:58:22.391Z | ERROR/report_host_socket_environment_final | incident=`4567890a-bcde-4f01-8123-4567890abcde` | lesson_key=`report-host-socket-boundary` | event_sha256=`ff9d7e9a0933fa5492f8c148be659f3bf354a8c74e2b8681e3c5c7d2bbe5538c`
