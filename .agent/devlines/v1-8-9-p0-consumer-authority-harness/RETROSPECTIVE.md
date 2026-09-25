# Retrospective — v1-8-9-p0-consumer-authority-harness

## Goal

# Workbench v1.8.9 P0 Consumer Authority Harness  ## Objective  Make the external evidence-authority test harness robust when the full v1.8.9 suite temporarily replaces or closes its shared Unix socket. Consumer projection tests must always obtain a live external authority in the current process, while production remains dependent on deployment-owned authority.  ## Scope  - \`tests/test_v189_consumer_projection.py\` - \`tests/test_v189_evidence_envelope.py\` - \`tests/test_v189_central_evidence_consumer_mount.py\`  ## Acceptance  - The consumer projection suite passes alone and after the authority-mount   suite in the same process. - The harness never falls back to an in-process or caller-owned authority. - Production evidence code is unchanged.

## Final status

COMPLETED

## Metrics

- Failure frequency: 4/8 (50.0%; 50.0 per 100 events)
- Repeat rate: 0/4 (0.0%)
- Recurrence rate: 0/4 (0.0%)
- MTTR: N/A (sample=0; unresolved=4)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #3 2026-08-21T09:16:26.469Z `stale_authority_cache_red`; cause_status: `known`; cause: The direct Unix socket probe closed the shared authority listener and the cached harness returned the missing socket instead of rebuilding a live external server.; resolution: `open`; lesson: Test authority acquisition must validate endpoint path, owner process and server liveness, then rebuild the external Unix server when the cached instance is stale.
- #4 2026-08-21T09:18:32.699Z `central_mount_consumer_red`; cause_status: `known`; cause: The evidence report package seeded the shared test authority, central mount replaced and closed the same pathname, and consumer projection reused the now-unlinked cached server.; resolution: `open`; lesson: A central mount may replace a shared Unix pathname; every consumer authority acquisition must verify the cached endpoint and rebuild before client connection.

## All errors

- #2 2026-08-21T09:16:26.352Z `sandbox_socket_boundary`; cause_status: `external`; cause: The default sandbox denied binding the real Unix authority socket, so the consumer baseline could not reach the harness boundary.; resolution: `accepted`; lesson: Keep Unix authority socket permission failures separate from harness RED/GREEN evidence and use a socket-capable host for this boundary.

## All gaps

- #7 2026-08-21T09:22:10.140Z `external_acceptance_boundary`; cause_status: `external`; cause: The scoped line does not execute the full backend regression or production provider and deployment-host acceptance gates.; resolution: `accepted`; lesson: Report focused harness verification separately from full backend, provider, host and release acceptance.

## All waste

- None recorded.

## Root causes and solutions

- `central-mount-consumer-order-red`: occurrences=1; cause_status: `known`; root cause: The evidence report package seeded the shared test authority, central mount replaced and closed the same pathname, and consumer projection reused the now-unlinked cached server.; solution: `open`
- `external-acceptance-boundary`: occurrences=1; cause_status: `external`; root cause: The scoped line does not execute the full backend regression or production provider and deployment-host acceptance gates.; solution: `accepted`
- `host-socket-sandbox-boundary`: occurrences=1; cause_status: `external`; root cause: The default sandbox denied binding the real Unix authority socket, so the consumer baseline could not reach the harness boundary.; solution: `accepted`
- `stale-authority-cache-red`: occurrences=1; cause_status: `known`; root cause: The direct Unix socket probe closed the shared authority listener and the cached harness returned the missing socket instead of rebuilding a live external server.; solution: `open`

## Added tests

- `tests/test_v189_central_evidence_consumer_mount.py tests/test_v189_consumer_projection.py`
- `tests/test_v189_evidence_envelope.py tests/test_v189_central_evidence_consumer_mount.py tests/test_v189_consumer_projection.py`
- `tests/test_v189_evidence_envelope.py::_ExternalHostAuthority`
- `tests/test_v189_evidence_report_boundary.py tests/test_v189_central_evidence_consumer_mount.py tests/test_v189_consumer_projection.py`

## New rules

- `central-mount-consumer-order-red`: line experience occurrence(s)=1
- `external-acceptance-boundary`: line experience occurrence(s)=1
- `host-socket-sandbox-boundary`: line experience occurrence(s)=1
- `stale-authority-cache-red`: line experience occurrence(s)=1

## Future guidance

- A central mount may replace a shared Unix pathname; every consumer authority acquisition must verify the cached endpoint and rebuild before client connection.
- Keep Unix authority socket permission failures separate from harness RED/GREEN evidence and use a socket-capable host for this boundary.
- Keep test authority transport and production authority ownership separate, and review the allowed-path diff before closing the line.
- Report focused harness verification separately from full backend, provider, host and release acceptance.
- Test authority acquisition must validate endpoint path, owner process and server liveness, then rebuild the external Unix server when the cached instance is stale.

## Event index

- #1: `8c94dfa3-8a37-407d-b0b0-6c3b218d02fe` | 2026-08-21T09:08:07.917Z | STATE_CHANGE/line_started | incident=`6eedc9b0-892d-4c66-839c-9973e2cd3832` | lesson_key=`frozen-context-before-start` | event_sha256=`4ae60321cd6e88af3f67196c150abd9e5b521604d6e82ea25a40303292f83372`
- #2: `d6bc8d26-77ae-4ba2-87c7-c66a1a32e14f` | 2026-08-21T09:16:26.352Z | ERROR/sandbox_socket_boundary | incident=`e17d9c3a-4f28-4c7b-9a61-2d5e8f0b3c74` | lesson_key=`host-socket-sandbox-boundary` | event_sha256=`8886a35cc43d9c6129ee2939f2ff46bd6a9c0df4490e02dbefde40d5818ff547`
- #3: `a4f7c2e9-6b13-4d85-90a7-3e1c5f8b2d64` | 2026-08-21T09:16:26.469Z | FAILURE/stale_authority_cache_red | incident=`b8e3f1a6-5c29-47d0-9e84-2f6b1d7a3c50` | lesson_key=`stale-authority-cache-red` | event_sha256=`a85d38d772517724f3748faa2cb3389693f63892cba86eb774e85688c92e4a00`
- #4: `c5e8a1f4-7b29-4d63-90c2-6f1a3e8b5d74` | 2026-08-21T09:18:32.699Z | FAILURE/central_mount_consumer_red | incident=`d9f2b6a1-4c37-48e5-90b2-7a1d3f6c8e54` | lesson_key=`central-mount-consumer-order-red` | event_sha256=`5463d41eb2917b9bd6c0d4ab89a34b1640d8e94424bb03843b0a45249e8ebf3b`
- #5: `e1b6c9f3-4a27-48d0-9c52-7f1d3e8a5b64` | 2026-08-21T09:22:09.894Z | GATE/consumer_authority_focused_green | incident=`f2a7d4c9-5e18-4b63-90f1-2c6d8a3e7b54` | lesson_key=`consumer-authority-focused-gate` | event_sha256=`195d54e928ee7c50c4d371e43c6b41a841bafb6620632da827e18d7f52bc1f6e`
- #6: `b3f8a2d6-7c19-4e50-90a4-1d6b3f8c5e72` | 2026-08-21T09:22:10.013Z | REVIEW/consumer_authority_scope_review | incident=`c4e9b2f7-6a13-48d5-90c1-2f7b3e8a5d64` | lesson_key=`test-production-authority-separation` | event_sha256=`cc44ffffb47d8db7aba0414bb5082709ee7152377a35e4906fa15bc9c3cbdfbb`
- #7: `d5a1e7c3-9b24-4f68-90d2-6c3e8a1b7f54` | 2026-08-21T09:22:10.140Z | GAP/external_acceptance_boundary | incident=`e6b2f8d4-1a37-49c0-90e5-3f7b2d8c6a14` | lesson_key=`external-acceptance-boundary` | event_sha256=`fd881f8947f8c52798936ab9c3710b41aedddddbe203e25dc5b98df3aa0364ca`
- #8: `f7c2a8e4-1b36-49d0-90e5-3a6f8c2d7b14` | 2026-08-21T09:22:21.351Z | STATE_CHANGE/line_completed | incident=`a8d3f1c6-5b27-49e0-90a4-2f7c8e1b6d53` | lesson_key=`consumer-authority-line-complete` | event_sha256=`43c9bacd473170da043711fd711d5766d9dda8e509eb24e08f91c602e2fbfa20`
