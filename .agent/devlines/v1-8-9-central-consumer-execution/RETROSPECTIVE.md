# Retrospective — v1-8-9-central-consumer-execution

## Goal

# v1.8.9 Central Consumer Execution Objective  ## Objective  Close the next P0/P1 integration gap after runtime bootstrap: make the server-owned shared Agent/Notebook runtime consume typed host data and classification inputs and return bounded, evidence-bindable results. The existing package-local data operations and classification engines remain the statistical owners; this line adds only the typed host ports and their declaration-derived runtime joins.  ## Required behavior  1. A data-consumer host port may be issued only by the server and may resolve    opaque snapshot/operation identities to existing typed data-operation    execution. It must never receive caller filesystem paths or return rows,    raw frames, or caller-authored evidence. 2. A classification host port may be issued only by the server and may resolve    an opaque snapshot identity to typed feature/target inputs, execute an    existing Logistic Regression or Random Forest adapter/protocol, and return    a bounded result packet containing model/evaluation identities and evidence    digests. It must fail closed on missing, stale, mismatched, or forged input. 3. Runtime composition must join the exact server-issued ports to the exact    server-loaded catalog. A missing port keeps that contribution unavailable;    a forged port, catalog clone, mismatched digest, or extra field is rejected. 4. Agent and Notebook continue to use the same compiler, confirmation store,    execution admission, and evidence commit path. This line must not create a    second capability table or a direct HTTP/provider fallback. 5. Tests prove real injected-host execution through compile -> persisted    proposal -> server confirmation -> execute -> typed evidence receipt, plus    fail-closed authority, scope, snapshot, stale, and raw-egress boundaries.  ## Non-goals  - No new statistical model family, estimator formula, or alternate split/CV   protocol. - No frontend, Report renderer, browser acceptance, external provider,   cross-process, full-gate, merge, push, tag, release, or deployment change. - No native file-format dependency installation; \`.sav/.zsav/.dta\` remains an   explicit optional-dependency boundary.  ## Acceptance boundary  Focused package and shared-runtime tests may prove the typed host-port and same-compiler path. Browser, provider, cross-process, full-repository, and release evidence remain separate and must be reported as NOT VERIFIED until run on an exact candidate SHA.

## Final status

COMPLETED

## Metrics

- Failure frequency: 6/17 (35.3%; 35.3 per 100 events)
- Repeat rate: 0/6 (0.0%)
- Recurrence rate: 0/6 (0.0%)
- MTTR: median=0 ms (sample=3; unresolved=3)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #6 2026-08-20T16:30:28.003Z `classification_runtime_bootstrap_red`; cause_status: `known`; cause: The new shared-runtime probe fails because bootstrap has no classification execution-port parameter or join yet.; resolution: `open`; lesson: Probe the central join before implementing host-port wiring and require an explicit typed parameter.
- #11 2026-08-20T16:47:26.271Z `classification_result_boundary_red`; cause_status: `known`; cause: Adversarial classification host-port tests initially exposed that digest fields accepted arbitrary 64-character strings and result validation did not recompute the bounded result digest.; resolution: `resolved`; lesson: A bounded result shape is not sufficient; evidence validators must verify canonical content binding and numeric domain constraints.
- #13 2026-08-20T16:53:54.508Z `data_completed_result_validator_red`; cause_status: `known`; cause: The first shared-runtime data dispatch probe reached the completed host path, but the result validator still required the unavailable reason code for every status.; resolution: `resolved`; lesson: Result validators must branch on the declared status before applying status-specific reason-code contracts.

## All errors

- #2 2026-08-20T16:26:44.128Z `formal_start_tag_invalid`; cause_status: `known`; cause: The first formal start attempt used an uppercase tag and the CLI rejected non-normalized tags before creating the line.; resolution: `resolved`; lesson: Normalize formal tags before invoking the start command.
- #7 2026-08-20T16:32:47.371Z `classification_host_port_import_error`; cause_status: `known`; cause: The in-progress classification host-port patch referenced dataclass_field without importing it, causing module collection to fail before tests ran.; resolution: `open`; lesson: Run module collection immediately after adding typed dataclass fields and keep imports in the same TDD slice.

## All gaps

- #5 2026-08-20T16:28:44.164Z `central_consumer_mount_missing`; cause_status: `known`; cause: A read-only audit found package-local data and classification projections but no confirmed central Agent/Notebook/Report production caller for those persisted results.; resolution: `open`; lesson: Keep package-local projection evidence separate from proof that a center route or UI consumes it.

## All waste

- None recorded.

## Root causes and solutions

- `central-consumer-mount-before-claim`: occurrences=1; cause_status: `known`; root cause: A read-only audit found package-local data and classification projections but no confirmed central Agent/Notebook/Report production caller for those persisted results.; solution: `open`
- `classification-host-port-before-runtime-join`: occurrences=1; cause_status: `known`; root cause: The new shared-runtime probe fails because bootstrap has no classification execution-port parameter or join yet.; solution: `open`
- `classification-result-digest-and-domain-validation`: occurrences=1; cause_status: `known`; root cause: Adversarial classification host-port tests initially exposed that digest fields accepted arbitrary 64-character strings and result validation did not recompute the bounded result digest.; solution: `resolved`
- `data-runtime-status-specific-result-validation`: occurrences=1; cause_status: `known`; root cause: The first shared-runtime data dispatch probe reached the completed host path, but the result validator still required the unavailable reason code for every status.; solution: `resolved`
- `formal-cli-command-surface`: occurrences=1; cause_status: `known`; root cause: The first formal start attempt used an uppercase tag and the CLI rejected non-normalized tags before creating the line.; solution: `resolved`
- `typed-port-import-before-focused-test`: occurrences=1; cause_status: `known`; root cause: The in-progress classification host-port patch referenced dataclass_field without importing it, causing module collection to fail before tests ran.; solution: `open`

## Added tests

- `tests/test_v189_central_consumer_execution.py`

## New rules

- `central-consumer-mount-before-claim`: line experience occurrence(s)=1
- `classification-host-port-before-runtime-join`: line experience occurrence(s)=1
- `classification-result-digest-and-domain-validation`: line experience occurrence(s)=1
- `data-runtime-status-specific-result-validation`: line experience occurrence(s)=1
- `formal-cli-command-surface`: line experience occurrence(s)=1
- `typed-port-import-before-focused-test`: line experience occurrence(s)=1

## Future guidance

- A bounded result shape is not sufficient; evidence validators must verify canonical content binding and numeric domain constraints.
- A timed-out reviewer is not approval; preserve that boundary and report the exact local evidence instead.
- Keep package-local projection evidence separate from proof that a center route or UI consumes it.
- Normalize formal tags before invoking the start command.
- Probe the central join before implementing host-port wiring and require an explicit typed parameter.
- Result validators must branch on the declared status before applying status-specific reason-code contracts.
- Review workers must verify the exact active worktree before treating focused green tests as evidence.
- Run module collection immediately after adding typed dataclass fields and keep imports in the same TDD slice.
- Server-issued record authority and complete identity claims must be verified together at the host boundary.
- Typed objects still require complete identity claims and server-issued provenance; structural typing alone is insufficient.

## Event index

- #1: `4f3534f7-ed3e-4926-9f25-287aee0db3d8` | 2026-08-20T16:26:19.812Z | STATE_CHANGE/line_started | incident=`8e7bfb9a-cd8d-47bd-9536-b8ff5c41be2b` | lesson_key=`frozen-context-before-start` | event_sha256=`f3fab874c54582e131ba9913bc60b3e00da043b53f16bbfda578cac107823ec5`
- #2: `b6e2f9a1-4c73-5d80-9e16-7a2f8c4d1b30` | 2026-08-20T16:26:44.128Z | ERROR/formal_start_tag_invalid | incident=`d7a4c9f2-6e31-4b80-9d25-7f3a1c8e5b62` | lesson_key=`formal-cli-command-surface` | event_sha256=`ebcb6d0e36aa0b0a82dcf55be34384a7f3d85542401376c5201849b9ddf0fd2d`
- #3: `2d87360d-092d-4e15-9663-f3a142993d94` | 2026-08-20T16:27:15.699Z | STATE_CHANGE/context_rescope_required | incident=`87d149fe-b447-4330-b171-0159911599b3` | lesson_key=`context-pack-rescope` | event_sha256=`3e4406ce2e88de190a8dd49e69f3608d5000a233f8f8d2ce07dbc8a1d813465a`
- #4: `8f276291-f807-4ecb-9655-28ccd4ddc7ff` | 2026-08-20T16:27:15.703Z | STATE_CHANGE/context_rescoped | incident=`aa989eb7-968c-497a-b0e2-9e63ac6a3a46` | lesson_key=`context-pack-rescope` | event_sha256=`4a5e63520a67fd2114ee864a234d10bce1cc3996dc60c72498aff18c1ac7649f`
- #5: `c8f1a4d7-2e63-4b90-9c15-7a3d6e8b2f40` | 2026-08-20T16:28:44.164Z | GAP/central_consumer_mount_missing | incident=`e5b9c2f7-6a31-4d80-9e24-7b3f1c8a5d62` | lesson_key=`central-consumer-mount-before-claim` | event_sha256=`20fc8faadfa8fb7038a6981f30b6f75ab87566af04f1d7d0a8beab58c712e500`
- #6: `a7d2f9c4-6e31-4b80-9d25-7f3a1c8e5b62` | 2026-08-20T16:30:28.003Z | FAILURE/classification_runtime_bootstrap_red | incident=`c9e4b7f2-6a31-4d80-9e25-7b3f1c8a5d62` | lesson_key=`classification-host-port-before-runtime-join` | event_sha256=`668fd3b2315a32301efa9c9260535090a1ad80d9da871c28dc42e0ce6bb58692`
- #7: `e4b7d2f9-6a31-4c80-9e25-7f3a1b8d5c62` | 2026-08-20T16:32:47.371Z | ERROR/classification_host_port_import_error | incident=`f9c4a7d2-6e31-4b80-9d25-7f3a1c8e5b62` | lesson_key=`typed-port-import-before-focused-test` | event_sha256=`463eaa2dd3675825c8a30ed0be0f418f40474bf132ce9e9c7839a22e507f3c75`
- #8: `f2a7c9d4-6e31-4b80-9d25-7f3a1c8e5b62` | 2026-08-20T16:35:57.566Z | REVIEW/data_host_port_spec_blocked | incident=`a6d9f2c7-4b31-5e80-9c25-7f3a1d8e5b62` | lesson_key=`typed-record-provenance-and-identity-completeness` | event_sha256=`67659cd698602ca45b074e63d1067de8f15f592908c7695a84657ffa81d4582c`
- #9: `1dc01265-00ed-4e4e-ab98-07e5cb90d2ec` | 2026-08-20T16:41:02.242Z | STATE_CHANGE/context_rescope_required | incident=`2339fdf8-38ed-4e35-bbe0-2a696290b469` | lesson_key=`context-pack-rescope` | event_sha256=`af3e321864f2a6d75c041eefd6f0dc52be8e7f79ba4f804bcbf2a248e564119b`
- #10: `912d2f0c-61a6-4d2a-b548-7bb248cb88e7` | 2026-08-20T16:41:02.249Z | STATE_CHANGE/context_rescoped | incident=`1aa06f7a-aaf4-4e87-a455-2a120c198051` | lesson_key=`context-pack-rescope` | event_sha256=`8707e4c01eef9185b4a772623c223a4d8522f223187826cb272ca62699b45792`
- #11: `b8d2f4a1-6c93-4e70-9a15-2f8c1d5b7e64` | 2026-08-20T16:47:26.271Z | FAILURE/classification_result_boundary_red | incident=`c4e8a1d2-7f63-4b90-9a15-2e6d8c4f1b73` | lesson_key=`classification-result-digest-and-domain-validation` | event_sha256=`56ca00b3a8509cbd6ed8e1300ae3e4882d78c4a04d85d9dab3f13e6cc4d9a494`
- #12: `d6a1f8c3-4b72-5e90-9c14-2f7a6b8e3d51` | 2026-08-20T16:53:39.692Z | REVIEW/data_host_port_spec_resolved | incident=`a7c2e9f4-6b18-4d53-8e20-1f7a9c3b5d62` | lesson_key=`data-host-port-authority-and-claims` | event_sha256=`75ea3b983b4e6d4027d2123dedf042315c83d3c21710ca89957d5b286e8b9dc7`
- #13: `e3b7c1a9-5d42-4f86-9e10-2a6c8d4f7b53` | 2026-08-20T16:53:54.508Z | FAILURE/data_completed_result_validator_red | incident=`b8d4f1a6-7c29-4e53-9a10-2f6d8c3b5e74` | lesson_key=`data-runtime-status-specific-result-validation` | event_sha256=`c379fb51fc3b229890b2d643c2339bdec3a93a611cee1c07723ba62185e550ac`
- #14: `f1a7c3e9-5b42-4d86-8a10-2c6e7b4f9d53` | 2026-08-20T17:05:18.562Z | REVIEW/data_host_port_security_review_pass | incident=`c8e4a1f7-6b32-4d90-9e15-2f7a8c3b5d64` | lesson_key=`review-active-worktree-and-contract-boundary` | event_sha256=`86d101e6b62e264bbf7aa15ad868dd1e589dbeaf9219fcad4cc4b44fe1852208`
- #15: `a4c9e1f7-6b32-4d85-9a10-2f7c8b3e5d64` | 2026-08-20T17:06:16.651Z | REVIEW/classification_security_local_revalidation | incident=`b7d3f1a6-8c24-4e59-9a10-2f6c8d3b5e74` | lesson_key=`classification-review-timeout-not-approval` | event_sha256=`79348928684f54fbf3d117bbfe12579ee22817ce9a59a8a3e259e55258d3c9b9`
- #16: `c7e3a1f9-5b42-4d86-9e10-2f6a8c3b5d74` | 2026-08-20T17:06:44.603Z | GATE/central_host_port_focused_green | incident=`d8f4a1c7-6b32-4e90-9a15-2f7c8b3e5d64` | lesson_key=`central-host-port-focused-gate-boundary` | event_sha256=`de3e152d9a0c920cf358dff6794ec0f2afe6a677a6163d11523acceaf692e75f`
- #17: `e9c4a1f7-6b32-4d85-9a10-2f7c8b3e5d64` | 2026-08-20T17:07:04.217Z | STATE_CHANGE/line_completed | incident=`f1d7c3a9-5b42-4e86-9a10-2f7c8b3d5e64` | lesson_key=`central-consumer-bounded-line-closeout` | event_sha256=`f783fba708d88763b31885e9cd630094d56adf36bb13ba1dc305b4cd3222cb1e`
