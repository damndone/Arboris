# Retrospective — v1-8-9-p1-data-consumer-central-mount

## Goal

# v1.8.9 P1 data-consumer central mount objective  ## Objective  Verify and, only where the contract probes demonstrate a missing behavior, complete the central data-consumer surface so the server-owned data-operation manifest, source identity, preview/confirmation lifecycle, immutable effect, OperationRecord, output ports, and unavailable semantics are consumed by the Workbench registry without a second capability list or raw-payload fallback.  The central surface must make the existing data-consumer package genuinely usable from the user-operated editor and preserve the same typed contract used by Agent and Notebook. A successful confirmation is allowed to render only after HTTP success, exact source/catalog/request identity, typed effect, OperationRecord, and declared output ports all match. Native formats that are not available remain typed unavailable.  ## Non-goals  - Do not redesign or duplicate the package-owned data-operation executor,   metadata authority, filter AST, interchange adapter, or runtime port. - Do not modify classification ML, statistical estimators, central evidence   registry, Report model-result semantics, or browser/provider deployment. - Do not install optional dependencies or claim \`.sav\`, \`.zsav\`, or \`.dta\`   support without a real reader/writer and round-trip evidence.  ## Verification target  The central backend and frontend tests must prove manifest-to-route alignment, source identity binding, preview-to-confirm replay, exact OperationRecord and output-port completion, fail-closed unavailable behavior, and that the registry mounts one canonical schema-driven editor for dataset nodes.

## Final status

COMPLETED

## Metrics

- Failure frequency: 4/14 (28.6%; 28.6 per 100 events)
- Repeat rate: 0/4 (0.0%)
- Recurrence rate: 0/4 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=3)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T17:43:40.557Z `central_data_consumer_ports_red`; cause_status: `known`; cause: The central column-cast confirmation route returned only the legacy operation payload and did not expose the server-owned OperationRecord outputs, typed derived/evidence ports, or consumer slots required by the central data-consumer contract.; resolution: `open`; lesson: A package executor and legacy operation response are not a central consumer mount; every advertised mutating data operation must return the complete server-owned output-port projection.

## All errors

- #4 2026-08-20T17:55:22.682Z `frontend_typecheck_red`; cause_status: `known`; cause: The new frontend regression fixture used a narrowly inferred response shape and legacy binding keys, so TypeScript rejected the test before the production preference change could be verified.; resolution: `resolved`; lesson: New response-contract tests must explicitly model both the authoritative typed field and intentionally malformed legacy compatibility fields.

## All gaps

- #5 2026-08-20T18:00:43.176Z `full_frontend_report_consumer_gap`; cause_status: `known`; cause: The full frontend suite still contains adjacent Report and classification-consumer fixtures that do not satisfy the current typed persisted-evidence boundary; the focused data-consumer suite remains green, but the full suite cannot be called green.; resolution: `open`; lesson: Keep package-local and central consumer evidence separate, and do not promote focused green tests to full-suite or release readiness while adjacent Report fixtures remain stale.
- #12 2026-08-20T19:41:13.715Z `host_sandbox_acceptance_boundary`; cause_status: `external`; cause: The agent sandbox denied the process-private UNIX socket and Darwin containment operations required by adjacent authority and code-execution acceptance suites.; resolution: `accepted`; lesson: Keep host containment and authority-socket evidence separate from package-local green tests; do not weaken safety tests to satisfy the agent sandbox.

## All waste

- None recorded.

## Root causes and solutions

- `central-data-consumer-ports-explicit`: occurrences=1; cause_status: `known`; root cause: The central column-cast confirmation route returned only the legacy operation payload and did not expose the server-owned OperationRecord outputs, typed derived/evidence ports, or consumer slots required by the central data-consumer contract.; solution: `open`
- `focused-green-not-full-green`: occurrences=1; cause_status: `known`; root cause: The full frontend suite still contains adjacent Report and classification-consumer fixtures that do not satisfy the current typed persisted-evidence boundary; the focused data-consumer suite remains green, but the full suite cannot be called green.; solution: `open`
- `host-sandbox-boundary`: occurrences=1; cause_status: `external`; root cause: The agent sandbox denied the process-private UNIX socket and Darwin containment operations required by adjacent authority and code-execution acceptance suites.; solution: `accepted`
- `typed-response-fixture-shape`: occurrences=1; cause_status: `known`; root cause: The new frontend regression fixture used a narrowly inferred response shape and legacy binding keys, so TypeScript rejected the test before the production preference change could be verified.; solution: `resolved`

## Added tests

- `tests/test_v189_data_consumer_central_mount.py; tests/test_data_operation_routes.py`

## New rules

- `central-data-consumer-ports-explicit`: line experience occurrence(s)=1
- `focused-green-not-full-green`: line experience occurrence(s)=1
- `host-sandbox-boundary`: line experience occurrence(s)=1
- `typed-response-fixture-shape`: line experience occurrence(s)=1

## Future guidance

- A central consumer review must inspect the serialized HTTP body and replayed terminal records, not only the typed port constructor or one happy-path operation.
- A package executor and legacy operation response are not a central consumer mount; every advertised mutating data operation must return the complete server-owned output-port projection.
- Keep host containment and authority-socket evidence separate from package-local green tests; do not weaken safety tests to satisfy the agent sandbox.
- Keep package-local and central consumer evidence separate, and do not promote focused green tests to full-suite or release readiness while adjacent Report fixtures remain stale.
- New response-contract tests must explicitly model both the authoritative typed field and intentionally malformed legacy compatibility fields.
- Review the serialized HTTP body and adversarial replay records, and require every identity-bearing nested object to contain at least one typed identity.

## Event index

- #1: `ba223fd9-fd7b-4463-a212-7674c4cd039d` | 2026-08-20T17:39:55.175Z | STATE_CHANGE/line_started | incident=`c26069fc-fa1c-4d3f-8d6f-081c24f49b6c` | lesson_key=`frozen-context-before-start` | event_sha256=`811098d28140699474ca7702e13b47676c9d2eede0897f1a9312fce45e5d1473`
- #2: `c3a1f6e4-1e7a-4b2c-9d63-0f5a8e2c741b` | 2026-08-20T17:43:40.557Z | FAILURE/central_data_consumer_ports_red | incident=`d6b4e2f1-8c39-4a7d-91e5-2b6f0c3d8a14` | lesson_key=`central-data-consumer-ports-explicit` | event_sha256=`d9ad966fdd316802b135bd0954c29f8fb13436f33c5295fc5e2ba956ac4d5670`
- #3: `3f9b1d20-2a84-4f78-9d1b-6c4e7a5b8f02` | 2026-08-20T17:54:09.551Z | GATE/data_consumer_ports_green | incident=`6d2e8f41-5b7c-4a90-81d3-f0e6b2c4a7e9` | lesson_key=`completed-data-operation-record-authoritative` | event_sha256=`b7840905cb07d042e81f75de2aa7b17b6f7703fa6a5f49c7f5a28f841b74e828`
- #4: `4a8c2e61-7d93-4fb0-a5e2-1c6b9f3d8e70` | 2026-08-20T17:55:22.682Z | ERROR/frontend_typecheck_red | incident=`7e2c4a91-6b5d-438f-90a1-d3c8e5b7f204` | lesson_key=`typed-response-fixture-shape` | event_sha256=`312089e3558df10dfef3d4a03e4731b6c3d5b6f564cda600de5b8f27633b6fcf`
- #5: `5b1e7c42-9a63-4d80-b2f5-6c8e0a3d7f91` | 2026-08-20T18:00:43.176Z | GAP/full_frontend_report_consumer_gap | incident=`8c4f2a70-6d91-4be3-a5f8-1e7b9d3c0a62` | lesson_key=`focused-green-not-full-green` | event_sha256=`2c93f244b2be3a3436d2ddf08f07ba9ae14ee5bea95d9a06ef6760791cdcbeaa`
- #6: `3236bf05-7da2-4bc7-aebf-035128c3fa79` | 2026-08-20T18:08:53.975Z | STATE_CHANGE/context_rescope_required | incident=`e2d6fdd2-3183-4d3d-beba-b6bf5e1190bd` | lesson_key=`context-pack-rescope` | event_sha256=`a0e271cfb385bb27fe1d59efcda652b500a0c10e0eeb0cc8289950fdccd246bb`
- #7: `8df3f9c1-0a34-4e3b-aaaf-05941f705fea` | 2026-08-20T18:08:53.981Z | STATE_CHANGE/context_rescoped | incident=`08d077c7-156a-4790-b324-322a59191695` | lesson_key=`context-pack-rescope` | event_sha256=`5723268a5f77696db20b7a80b65857b8453c4ca0a703b2cf2d07e99b5a76814c`
- #8: `5075a468-76bb-4de6-9ef7-b8b1859a4fd0` | 2026-08-20T18:09:24.158Z | STATE_CHANGE/context_rescope_required | incident=`50fc3684-fe2a-4838-8028-5a6b8a0d0b78` | lesson_key=`context-pack-rescope` | event_sha256=`6073973ad7dab69f256eb74d27cda14cb5b1669dde36c617bceba5d9d94eb3c2`
- #9: `3efd426c-498d-4c1c-b7a1-8faf4d524cb3` | 2026-08-20T18:09:24.164Z | STATE_CHANGE/context_rescoped | incident=`7b253228-cc97-414d-94c6-67904b8b0536` | lesson_key=`context-pack-rescope` | event_sha256=`51df6de7d1a7b945f904820203eae2ca35e1a9b85be981c6eff55a506c82d91b`
- #10: `6c2f8a41-5d93-4be7-90a1-e3b7d9f0c562` | 2026-08-20T18:11:07.356Z | REVIEW/central_data_consumer_spec_review | incident=`9f4b2d70-6e81-43a5-bc29-0d7f1e3a6b52` | lesson_key=`central-serialized-body-and-replay-review` | event_sha256=`bd97f1b65b06f31141f575af9aaaaac1cd48a184b1d256f52eeff365da98a514`
- #11: `a1b2c3d4-e5f6-4789-abcd-0123456789ab` | 2026-08-20T19:41:13.587Z | REVIEW/central_mount_adversarial_review | incident=`b1c2d3e4-f5a6-4789-bcde-1234567890ab` | lesson_key=`central-mount-adversarial-review` | event_sha256=`511b9faa5c98cbda1e98791c323dc99914d332f1ad92bbd1eb61e90a4ebf3939`
- #12: `c1d2e3f4-a5b6-4789-cdef-2345678901bc` | 2026-08-20T19:41:13.715Z | GAP/host_sandbox_acceptance_boundary | incident=`d1e2f3a4-b5c6-4789-def0-3456789012cd` | lesson_key=`host-sandbox-boundary` | event_sha256=`e292e8cc5416a02ffc4e92b5848b2246f050b4f53602bdf2e0fa7c8895d75065`
- #13: `e1f2a3b4-c5d6-4789-ef01-4567890123de` | 2026-08-20T19:41:13.841Z | GATE/central_mount_focused_gate | incident=`f1a2b3c4-d5e6-4789-f012-5678901234ef` | lesson_key=`bounded-central-mount-gate` | event_sha256=`555bf3f3de68049176ff029ad22d740eb9c439ac000dae28dde5493faaf4580c`
- #14: `01234567-89ab-4cde-f012-3456789abcde` | 2026-08-20T19:41:22.014Z | STATE_CHANGE/central_mount_line_completed | incident=`12345678-9abc-4def-0123-456789abcdef` | lesson_key=`central-mount-line-completion` | event_sha256=`5419b1bd65d6a53cc8415f35b5ff57ad1c7264309e9a8ca5195ef9d3a79f3597`
