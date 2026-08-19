# Retrospective — v1-8-9-p1-data-consumer

## Goal

# Workbench v1.8.9 P1 Data Consumer Objective  Complete the safe, composable data-consumer foundation needed by SPSS/Stata users without turning it into a second execution engine. Add typed metadata and missing-value semantics, preview-first operations, and manifest/HTTP coverage for the supported data transformations. Preserve immutable dataset identity, lineage, server-owned admission, bounded context egress, and fail-closed behavior.  This line owns the backend data profile/metadata/filter/operation contracts, the data-operation manifest and HTTP surface, and the existing data-operation consumer component tests. It may add a reusable editor contribution but does not change the central Agent/Notebook router or the canonical section registry mount; central mounting is a later integration task.  Required outcomes:  - variable labels, value labels, measurement roles, user-defined missing   values, weights, filters, sorting, split-file/group semantics, and batch   recode have typed contracts with preview, confirmation, identity-bound   persistence, and lineage; - existing backend operations are not advertised as reachable unless their   manifest, HTTP/runtime, and evidence path are real; - filter expressions remain a bounded AST, never arbitrary code; - metadata loss is explicit and round-trip checks are available to consumers; - raw rows and restricted columns remain unavailable to remote contexts by   default.  Native .sav/.dta interchange is a separately staged adapter within this line only if the local optional dependency and safe round-trip contract can be proven; otherwise it must remain a typed unavailable capability rather than a fake reader/writer.

## Final status

COMPLETED

## Metrics

- Failure frequency: 16/30 (53.3%; 53.3 per 100 events)
- Repeat rate: 1/16 (6.2%)
- Recurrence rate: 1/15 (6.7%)
- MTTR: median=0 ms (sample=13; unresolved=3)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/12 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-19T17:00:00.000Z `tdd_red_data_consumer_extensions`; cause_status: `known`; cause: New data-consumer contract tests were run at the frozen baseline before implementation and correctly failed for typed metadata mutation, user-defined missing filters, sort/split/batch recode, interchange, manifest reachability, and unavailable UI rendering.; resolution: `accepted`; lesson: Freeze typed data-consumer declarations as red assertions before implementing the runtime and UI seams.
- #3 2026-08-19T17:03:41.000Z `manifest_surface_fixture_stale`; cause_status: `known`; cause: The manifest implementation now includes the authorized local metadata/sort/split/recode descriptors, so the frozen legacy EXPECTED_OPERATION_IDS assertion and builtin provider digest fixture fail until the allowlisted tests and fixture are updated.; resolution: `open`; lesson: Update the allowlisted manifest expectations and static provider projection only after the live descriptor surface is executable.
- #4 2026-08-19T17:07:39.000Z `unavailable_editor_projection_missing_reason`; cause_status: `known`; cause: The first frontend implementation rendered descriptor-level availability through the top-level unavailable shape and omitted reason_code/message; the focused UI test caught the typed boundary losing its reason before the selector was removed.; resolution: `resolved`; lesson: Keep descriptor-level and manifest-level unavailable projections explicitly typed at the renderer boundary.
- #15 2026-08-19T15:00:00.000Z `reviewer_adversarial_red`; cause_status: `known`; cause: Reviewer-directed adversarial RED probes reproduced incomplete split/group metadata binding, partial rename confirmation writes, route reachability independent of the live manifest, permissive runtime adapter trust boundaries, and frontend completion on unverified confirmation responses.; resolution: `open`; lesson: Run adversarial probes at artifact, trust-boundary, live-manifest, and browser-response seams before accepting a green focused suite.
- #27 2026-08-19T19:52:00.000Z `reviewer_adversarial_red_round3`; cause_status: `known`; cause: The third-round reviewer-directed RED probes reproduced the requested trust, authority, atomicity, live-manifest, runtime-adapter, and frontend completion gaps at the current tip before any production-path edit.; resolution: `open`; lesson: Adversarial tests must cross the server-owned artifact, live descriptor, transaction, typed adapter, and browser response boundaries before a focused green suite can establish compliance.

## All errors

- #9 2026-08-19T17:16:33.000Z `handoff_trailing_whitespace`; cause_status: `known`; cause: The staged handoff Markdown used two trailing spaces for line breaks, so git diff --cached --check correctly rejected the staged closeout even though source and test files were clean.; resolution: `resolved`; lesson: Run cached diff-check after the final handoff formatting change, not only before staging.
- #10 2026-08-19T17:17:35.000Z `retrospective_refresh_order`; cause_status: `known`; cause: After appending the final handoff whitespace event, verify was invoked before the required retrospective regeneration and correctly rejected the stale RETROSPECTIVE.md.; resolution: `resolved`; lesson: Regenerate the retrospective immediately after every appended event, then run verify.
- #16 2026-08-19T15:01:00.000Z `formal_event_evidence_digest_rejected`; cause_status: `known`; cause: The first formal append attempt used a non-digest evidence placeholder and the CLI rejected it before writing the event.; resolution: `resolved`; lesson: Validate formal event evidence fields before invoking append.
- #18 2026-08-19T19:05:00.000Z `unconfirmed_sidecar_chain_regression`; cause_status: `known`; cause: The new derived metadata sidecar binding annotated children whose sidecar was explicitly confirmed=false, and the next chained transform treated that sidecar as an authoritative MetadataRegistryV1.; resolution: `open`; lesson: A metadata sidecar may preserve provenance without becoming a consumer registry unless its confirmed flag is true; chained transforms must distinguish those states.
- #19 2026-08-19T19:07:00.000Z `metadata_exception_indent`; cause_status: `known`; cause: The first patch for the unconfirmed metadata sidecar branch mis-indented an except clause and Python rejected the module during test collection.; resolution: `resolved`; lesson: Run compileall or an import-level check immediately after structural exception-handling edits before invoking the focused suite.
- #22 2026-08-19T19:30:00.000Z `formal_final_gate_validation_rejected`; cause_status: `known`; cause: The first final verification event used preventability=not_applicable, which is outside the formal event contract.; resolution: `resolved`; lesson: Validate formal event enum fields before appending the final gate evidence.
- #24 2026-08-19T19:31:00.000Z `git_stage_sandbox_rejected`; cause_status: `external`; cause: The unprivileged staging command could not create the worktree Git index lock under the protected root Git metadata directory.; resolution: `resolved`; lesson: When a user-authorized worktree commit is blocked by Git metadata sandboxing, preserve the source state and retry only with scoped metadata permission.
- #25 2026-08-19T19:53:00.000Z `formal_event_evidence_kind_rejected`; cause_status: `known`; cause: The first third-round RED event append used an evidence.kind value outside the formal controlled identifier set and was rejected before writing.; resolution: `resolved`; lesson: Validate formal event enum fields before invoking devline_control append.
- #26 2026-08-19T19:53:00.000Z `formal_event_tag_rejected`; cause_status: `known`; cause: The first third-round RED event append used an evidence.kind value outside the formal controlled identifier set and was rejected before writing.; resolution: `resolved`; lesson: Validate formal event enum fields before invoking devline_control append.
- #28 2026-08-19T20:06:00.000Z `host_socket_sandbox_boundary`; cause_status: `external`; cause: The unprivileged C0/context-egress/evidence-host run could not bind its temporary Unix authority socket; the same command was rerun in the authorized host environment.; resolution: `resolved`; lesson: Run socket-authority evidence suites in the host environment and record the sandbox boundary separately.

## All gaps

- #11 2026-08-19T17:54:04.000Z `spec_compliance_red`; cause_status: `known`; cause: Independent specification probes found that metadata revisions, confirmed missing-value provenance, split children, weight consumption, transform sidecars, runtime adapter joins, and catalog surface evidence were incomplete in the prior tip.; resolution: `open`; lesson: Every advertised data-consumer contract needs a server-owned artifact probe and a child reload probe before the manifest is trusted.

## All waste

- None recorded.

## Root causes and solutions

- `data-consumer-adversarial-red`: occurrences=1; cause_status: `known`; root cause: Reviewer-directed adversarial RED probes reproduced incomplete split/group metadata binding, partial rename confirmation writes, route reachability independent of the live manifest, permissive runtime adapter trust boundaries, and frontend completion on unverified confirmation responses.; solution: `open`
- `data-consumer-contract-first`: occurrences=1; cause_status: `known`; root cause: New data-consumer contract tests were run at the frozen baseline before implementation and correctly failed for typed metadata mutation, user-defined missing filters, sort/split/batch recode, interchange, manifest reachability, and unavailable UI rendering.; solution: `accepted`
- `data-consumer-manifest-live-surface`: occurrences=1; cause_status: `known`; root cause: The manifest implementation now includes the authorized local metadata/sort/split/recode descriptors, so the frozen legacy EXPECTED_OPERATION_IDS assertion and builtin provider digest fixture fail until the allowlisted tests and fixture are updated.; solution: `open`
- `data-consumer-server-artifact-probes`: occurrences=1; cause_status: `known`; root cause: Independent specification probes found that metadata revisions, confirmed missing-value provenance, split children, weight consumption, transform sidecars, runtime adapter joins, and catalog surface evidence were incomplete in the prior tip.; solution: `open`
- `data-consumer-third-round-adversarial-red`: occurrences=1; cause_status: `known`; root cause: The third-round reviewer-directed RED probes reproduced the requested trust, authority, atomicity, live-manifest, runtime-adapter, and frontend completion gaps at the current tip before any production-path edit.; solution: `open`
- `exception-edit-import-check`: occurrences=1; cause_status: `known`; root cause: The first patch for the unconfirmed metadata sidecar branch mis-indented an except clause and Python rejected the module during test collection.; solution: `resolved`
- `final-handoff-whitespace-gate`: occurrences=1; cause_status: `known`; root cause: The staged handoff Markdown used two trailing spaces for line breaks, so git diff --cached --check correctly rejected the staged closeout even though source and test files were clean.; solution: `resolved`
- `formal-event-controlled-evidence-kind`: occurrences=2; cause_status: `known`; root cause: The first third-round RED event append used an evidence.kind value outside the formal controlled identifier set and was rejected before writing.; solution: `resolved`
- `formal-event-enum-validation`: occurrences=1; cause_status: `known`; root cause: The first final verification event used preventability=not_applicable, which is outside the formal event contract.; solution: `resolved`
- `formal-event-evidence-digest`: occurrences=1; cause_status: `known`; root cause: The first formal append attempt used a non-digest evidence placeholder and the CLI rejected it before writing the event.; solution: `resolved`
- `formal-retrospective-refresh-order`: occurrences=1; cause_status: `known`; root cause: After appending the final handoff whitespace event, verify was invoked before the required retrospective regeneration and correctly rejected the stale RETROSPECTIVE.md.; solution: `resolved`
- `git-metadata-sandbox-stage`: occurrences=1; cause_status: `external`; root cause: The unprivileged staging command could not create the worktree Git index lock under the protected root Git metadata directory.; solution: `resolved`
- `host-socket-environment-boundary`: occurrences=1; cause_status: `external`; root cause: The unprivileged C0/context-egress/evidence-host run could not bind its temporary Unix authority socket; the same command was rerun in the authorized host environment.; solution: `resolved`
- `typed-unavailable-rendering`: occurrences=1; cause_status: `known`; root cause: The first frontend implementation rendered descriptor-level availability through the top-level unavailable shape and omitted reason_code/message; the focused UI test caught the typed boundary losing its reason before the selector was removed.; solution: `resolved`
- `unconfirmed-sidecar-chain-boundary`: occurrences=1; cause_status: `known`; root cause: The new derived metadata sidecar binding annotated children whose sidecar was explicitly confirmed=false, and the next chained transform treated that sidecar as an authoritative MetadataRegistryV1.; solution: `open`

## Added tests

- `reviewer-directed RED probes in tests/test_v189_filter_ast.py tests/test_data_operation_routes.py tests/test_v189_data_operation_manifest.py frontend/src/lineage/detail/sections/DataOperationsSection.test.tsx`

## New rules

- `data-consumer-adversarial-red`: line experience occurrence(s)=1
- `data-consumer-contract-first`: line experience occurrence(s)=1
- `data-consumer-manifest-live-surface`: line experience occurrence(s)=1
- `data-consumer-server-artifact-probes`: line experience occurrence(s)=1
- `data-consumer-third-round-adversarial-red`: line experience occurrence(s)=1
- `exception-edit-import-check`: line experience occurrence(s)=1
- `final-handoff-whitespace-gate`: line experience occurrence(s)=1
- `formal-event-controlled-evidence-kind`: line experience occurrence(s)=2
- `formal-event-enum-validation`: line experience occurrence(s)=1
- `formal-event-evidence-digest`: line experience occurrence(s)=1
- `formal-retrospective-refresh-order`: line experience occurrence(s)=1
- `git-metadata-sandbox-stage`: line experience occurrence(s)=1
- `host-socket-environment-boundary`: line experience occurrence(s)=1
- `typed-unavailable-rendering`: line experience occurrence(s)=1
- `unconfirmed-sidecar-chain-boundary`: line experience occurrence(s)=1

## Future guidance

- A metadata sidecar may preserve provenance without becoming a consumer registry unless its confirmed flag is true; chained transforms must distinguish those states.
- Adversarial tests must cross the server-owned artifact, live descriptor, transaction, typed adapter, and browser response boundaries before a focused green suite can establish compliance.
- Every advertised data-consumer contract needs a server-owned artifact probe and a child reload probe before the manifest is trusted.
- Freeze typed data-consumer declarations as red assertions before implementing the runtime and UI seams.
- Keep descriptor-level and manifest-level unavailable projections explicitly typed at the renderer boundary.
- Regenerate the retrospective immediately after every appended event, then run verify.
- Run adversarial probes at artifact, trust-boundary, live-manifest, and browser-response seams before accepting a green focused suite.
- Run cached diff-check after the final handoff formatting change, not only before staging.
- Run compileall or an import-level check immediately after structural exception-handling edits before invoking the focused suite.
- Run socket-authority evidence suites in the host environment and record the sandbox boundary separately.
- Update the allowlisted manifest expectations and static provider projection only after the live descriptor surface is executable.
- Validate formal event enum fields before appending the final gate evidence.
- Validate formal event enum fields before invoking devline_control append.
- Validate formal event evidence fields before invoking append.
- When a user-authorized worktree commit is blocked by Git metadata sandboxing, preserve the source state and retry only with scoped metadata permission.

## Event index

- #1: `46981e9a-4ca0-4fff-b3b7-5f16cf141d59` | 2026-08-19T16:35:26.177Z | STATE_CHANGE/line_started | incident=`d83c1149-1300-4ae9-8aa1-e588b16a503d` | lesson_key=`frozen-context-before-start` | event_sha256=`2479a8cff0a271d8ecb5e25afe1994f55c32ef36ef838ea1473dd8d3fdff4a6a`
- #2: `b6a31f4a-48c3-4e16-9b70-2a7a9c8d1f22` | 2026-08-19T17:00:00.000Z | FAILURE/tdd_red_data_consumer_extensions | incident=`a5e0d9c2-3f14-4a67-8b91-0d2e6f7c4a10` | lesson_key=`data-consumer-contract-first` | event_sha256=`770b465d7dd9029fcfdfddb79742667bd70113f47fb31015b4ce0b673b60214f`
- #3: `9c1f3e4a-7b52-4e0a-9d31-5f6c8a2b1e77` | 2026-08-19T17:03:41.000Z | FAILURE/manifest_surface_fixture_stale | incident=`d2a4f6c8-1e30-4b72-9f5a-7c8d0e2b4a61` | lesson_key=`data-consumer-manifest-live-surface` | event_sha256=`7d181a4e3aeadabbe35114acfc9678c7ee49e2acd7de6eb3b200a78ec07747cd`
- #4: `3e7a9c1d-5f20-4b68-8a32-6d1e4f9b7c50` | 2026-08-19T17:07:39.000Z | FAILURE/unavailable_editor_projection_missing_reason | incident=`e4b6d8f0-2a31-4c75-9d6e-8f1b3a5c7d20` | lesson_key=`typed-unavailable-rendering` | event_sha256=`0bdeaff2df1e372d856a55efe0c8f8a3fe97a87705f83ee0a73c6dc1439e6638`
- #5: `5f8a2c4e-7b10-4d93-9e61-3a7c5b8d0f24` | 2026-08-19T17:13:17.000Z | GATE/focused_backend_data_consumer | incident=`6a9c1e3f-5b7d-4c20-8f62-1d4e7a9b3c58` | lesson_key=`data-consumer-focused-backend-gate` | event_sha256=`157ec5f40a7728483af107609adcf3cb642bbb3c71513a77e70f28a588d8508b`
- #6: `7c1e5a9d-3f62-4b80-8d14-6e9a2c5f7b31` | 2026-08-19T17:13:17.000Z | GATE/focused_frontend_data_consumer | incident=`8d2f6a1c-4e90-5b73-9a16-c7e2f4b8d0a5` | lesson_key=`data-consumer-focused-frontend-gate` | event_sha256=`bb30eacad9a8ec16d2a02f5ac463e94c0e8344dfaea57c0e9d0ffd6c046169b1`
- #7: `9a4d7e2c-6f10-4b83-8c51-2e9f5a7d1b36` | 2026-08-19T17:13:17.000Z | GATE/allowlist_diff_check | incident=`ab6e1c3f-5d90-4b72-8a16-9f2e7c4d0b58` | lesson_key=`data-consumer-allowlist-diff-gate` | event_sha256=`d7062838226557c2608079cd11b3a69d9f5ce762c2f40b0d1eaff717894302ea`
- #8: `c2e6a1f4-8b30-4d75-9c12-5a7e3f0b6d98` | 2026-08-19T17:14:50.000Z | STATE_CHANGE/line_completed | incident=`d4f8b2a6-1c70-4e93-9a25-6b0d3f7c8e14` | lesson_key=`data-consumer-formal-closeout` | event_sha256=`8bff028ec454de6f5cb8c744f3f8491bf054ff8eea7a63ae18d52f20ca59965f`
- #9: `e6a1c3f8-5b20-4d79-9a14-7c2e6f0b8d35` | 2026-08-19T17:16:33.000Z | ERROR/handoff_trailing_whitespace | incident=`f8c2a4d6-1e70-4b93-9c25-6a0d3f7e8b14` | lesson_key=`final-handoff-whitespace-gate` | event_sha256=`afe9cd02561a369c7f304a3192a7cffddb41b77dc5b18d1fea1f9a903a55b3e8`
- #10: `f1a3c7e9-5b20-4d68-8a14-6c2e0f7b9d35` | 2026-08-19T17:17:35.000Z | ERROR/retrospective_refresh_order | incident=`a4e8c2f6-1b70-4d93-9a25-6f0c3e7b8d14` | lesson_key=`formal-retrospective-refresh-order` | event_sha256=`7452baccff9f45cd816a3b82c816b089b8e44ae8c120f7fea9c6900d8e475d0b`
- #11: `f3a0c8e1-1a4d-4e94-8b45-2d8a1e6b7c90` | 2026-08-19T17:54:04.000Z | GAP/spec_compliance_red | incident=`e8c6f5a4-9b2d-4e71-8c03-6a1f0d9b2e84` | lesson_key=`data-consumer-server-artifact-probes` | event_sha256=`6e936abd8dd22c27e2ae099a7c159440dcfeb8790014f9b3ea8b63cbcbd8dad9`
- #12: `a6d3f1b8-4c2e-4f70-9a15-7e8c0b2d6f43` | 2026-08-19T18:13:51.000Z | GATE/manifest_surface_fixture_stale_resolved | incident=`d2a4f6c8-1e30-4b72-9f5a-7c8d0e2b4a61` | lesson_key=`data-consumer-manifest-live-surface` | event_sha256=`0872cb1f44ae5965c04a56466678c2deb4af2f439754f5d390d76624ff118d2b`
- #13: `b7d4f1a9-2c6e-4f83-9a15-7e0b3d5c8f21` | 2026-08-19T18:19:28.000Z | GATE/spec_compliance_red_resolved | incident=`e8c6f5a4-9b2d-4e71-8c03-6a1f0d9b2e84` | lesson_key=`data-consumer-server-artifact-probes` | event_sha256=`272c7faa56f1a6a1793b81f3f2549f9665cbc8e49489944adeb060edf94305e2`
- #14: `c8e2a6f4-1b7d-4c90-8e35-6a2f9d0b7c14` | 2026-08-19T18:23:27.000Z | GATE/post_review_regression | incident=`d1f7a3c9-5e20-4b86-9a14-7c2e6f0b8d35` | lesson_key=`final-review-regression-gate` | event_sha256=`00aa2f9e7e32e6a410bcc9ed4d258dedbf071d5767c29cee2d4458f243c6c888`
- #15: `d7e6f5a4-b3c2-4d1e-9f80-7a6b5c4d3e2f` | 2026-08-19T15:00:00.000Z | FAILURE/reviewer_adversarial_red | incident=`e7d6c5b4-a3f2-4e1d-9c80-7b6a5d4c3e2f` | lesson_key=`data-consumer-adversarial-red` | event_sha256=`9185239895345c50f42aa46df87bbeeaf0198855399a0b259d954efae4b23f8c`
- #16: `e8f7a6b5-c4d3-4e2f-9a80-7b6c5d4e3f21` | 2026-08-19T15:01:00.000Z | ERROR/formal_event_evidence_digest_rejected | incident=`f8e7d6c5-b4a3-4f2e-9d80-7c6b5a4e3f21` | lesson_key=`formal-event-evidence-digest` | event_sha256=`362b9b87f7a7b9f09c7715cf22afcbffc7df436431fa2a95b640291a478f98a3`
- #17: `f4a6c8e0-2b1d-4f73-9a65-8c0e1d2f4b6a` | 2026-08-19T19:00:00.000Z | GATE/c0_evidence_socket_sandbox | incident=`d2f4a6c8-1b3e-4d70-9f52-6a8c0e1b3d5f` | lesson_key=`c0-evidence-socket-sandbox` | event_sha256=`b9b1d073aca057c1aed17b50b506def44792a5adbec7eddc52676aa3e4828a3b`
- #18: `a6c8e0f2-4b1d-4f73-9a65-8c0e1d2f4b7a` | 2026-08-19T19:05:00.000Z | ERROR/unconfirmed_sidecar_chain_regression | incident=`c8e0f2a4-1b3d-4f70-9a52-6c8e0b1d3f5a` | lesson_key=`unconfirmed-sidecar-chain-boundary` | event_sha256=`a63dad7b5caed2993d13c35af13d826c9b96ab00baa944d6d06308bfcff41db7`
- #19: `b7d9f1a3-5c2e-4f80-9a64-8c0e1d2f4b6a` | 2026-08-19T19:07:00.000Z | ERROR/metadata_exception_indent | incident=`d9f1a3c5-2e4b-4f70-9a68-0c1e2d3f5b7a` | lesson_key=`exception-edit-import-check` | event_sha256=`180f4e86fb4b21745b8964973fbdf7ef8ed4409b5b0b6fefd4bca3af3ced2991`
- #20: `c9e1a7b3-5d4f-4a2e-9c8b-6f0d1e3a5b7c` | 2026-08-19T19:27:23.000Z | GATE/c0_evidence_socket_sandbox_resolved | incident=`d2f4a6c8-1b3e-4d70-9f52-6a8c0e1b3d5f` | lesson_key=`c0-evidence-socket-sandbox` | event_sha256=`0ee1fd0e77c64803bf03c7f4a52b4f454d84cca6e54bf1c02de5bbf75b2752bc`
- #21: `d9f3b1a7-6c4e-4d20-8b5a-1e7c3f9a2d6b` | 2026-08-19T19:28:00.000Z | GATE/unconfirmed_sidecar_chain_regression_resolved | incident=`c8e0f2a4-1b3d-4f70-9a52-6c8e0b1d3f5a` | lesson_key=`unconfirmed-sidecar-chain-boundary` | event_sha256=`12fd75c22d4676aeea19c2957c8b5a3a72a2192235c75f34509e14cc9a818ef3`
- #22: `f6b2d8a4-1c3e-4f70-9a52-6e0b3d5c7f91` | 2026-08-19T19:30:00.000Z | ERROR/formal_final_gate_validation_rejected | incident=`f7c3a9e5-1b2d-4f60-8a14-6e0c3b5d7a92` | lesson_key=`formal-event-enum-validation` | event_sha256=`2c25de3d57b79766f1c6324949c89defa60b59c2584f07f5daba6d3c21fa1d57`
- #23: `e4a2c6f8-1b3d-4e70-9a52-6c8f0d1b3a5e` | 2026-08-19T19:29:00.000Z | GATE/data_consumer_final_verification | incident=`e5f1a7c3-9b2d-4e60-8a14-6c0f3b5d7e92` | lesson_key=`final-data-consumer-verification` | event_sha256=`255174339f561ec423e33b3d9ae50b6ab0be8e0677472a376b8feccf8dcc526a`
- #24: `a7c3e9f1-5b2d-4f60-8a14-6e0c3b7d9f25` | 2026-08-19T19:31:00.000Z | ERROR/git_stage_sandbox_rejected | incident=`b8d4f0a2-6c3e-4f71-9a25-7e0c3b5d1f96` | lesson_key=`git-metadata-sandbox-stage` | event_sha256=`e707877a082cab985bec7f30b7457db9203f6fe2c56cbb92db6e0f884abdae5b`
- #25: `3a2b1c0d-9e8f-7a6b-5c4d-3e2f1a0b9c8d` | 2026-08-19T19:53:00.000Z | ERROR/formal_event_evidence_kind_rejected | incident=`4b3c2d1e-0f9a-8b7c-6d5e-4f3a2b1c0d9e` | lesson_key=`formal-event-controlled-evidence-kind` | event_sha256=`0cb4af05bada06ddb5e97495893adb73ee46ea763b32efa2de930ad7be667a3d`
- #26: `5c4d3e2f-1a0b-9c8d-7e6f-5a4b3c2d1e0f` | 2026-08-19T19:53:00.000Z | ERROR/formal_event_tag_rejected | incident=`6d5e4f3a-2b1c-0d9e-8f7a-6b5c4d3e2f1a` | lesson_key=`formal-event-controlled-evidence-kind` | event_sha256=`11e7c7a32555de7db09bd4657f6437993579c68ae6f94ff8f45745d27a216616`
- #27: `1f0e9d8c-7b6a-4c5d-9e8f-0a1b2c3d4e5f` | 2026-08-19T19:52:00.000Z | FAILURE/reviewer_adversarial_red_round3 | incident=`2e1d0c9b-8a7f-6e5d-4c3b-2a1908171615` | lesson_key=`data-consumer-third-round-adversarial-red` | event_sha256=`85ea2b3acdb17d1385df445a0d7551133751b305c6f80ba796ddcd79684881ce`
- #28: `6e4f2a1c-8b7d-4c5e-9f0a-3b2d1c7e6a5f` | 2026-08-19T20:06:00.000Z | ERROR/host_socket_sandbox_boundary | incident=`7f5e3d1c-9b8a-4c6d-2e1f-34567890abce` | lesson_key=`host-socket-environment-boundary` | event_sha256=`778d72347febb8f22c8e0b4fb3ac528d9097c9162edfd2344766e3304e72d5e6`
- #29: `9a7c5e3d-1f2b-4d6e-8c0a-5b7e9d1f3c2a` | 2026-08-19T20:08:00.000Z | GATE/data_consumer_round3_spec_compliance | incident=`ab8d6f4e-2c1a-4b7e-9d0f-6a5c3e1b8f2d` | lesson_key=`round3-final-data-consumer-gate` | event_sha256=`5f16ce98770b815e6cc2ac3906d695ddd4b8471a491dbb62938d11963c4661fe`
- #30: `2c8e6a4d-1f0b-4c7e-9a5d-3b6f8d2e1c0a` | 2026-08-19T20:09:00.000Z | GATE/data_consumer_round3_final_rerun | incident=`3d9f7b5e-1a2c-4e6f-8b0d-5c7a9e1f3b2d` | lesson_key=`post-edit-final-rerun` | event_sha256=`edbfdf6bbe214a2bf29db9afd831f4d6d57b524172724b075f0721388fd060d7`
