# Retrospective — v1-8-9-p1-data-consumer-projection-readers

## Goal

# v1.8.9 P1 Data Consumer Projection Readers Objective  ## Objective  Close the remaining central data-consumer read boundary. Agent, Notebook, and Report must consume one server-owned, scope-bound projection of committed data operation evidence. The readers must not accept a caller-owned project path, dataframe, raw packet, or alternate registry, and they must return an explicit unavailable projection for missing, stale, malformed, foreign, or ambiguous durable state.  ## Success criteria  1. A server-only opaque run capability can be minted only from a resolved    project/run scope and carries no serializable path or raw data. 2. One central reader resolves committed data \`OperationRecord\` output ports    and produces a bounded, deterministic projection with record, operation,    artifact identity, evidence digest, catalog identity, and lineage facts. 3. Agent and Notebook wrappers accept only the server capability and delegate    to the same central reader; path/raw/forged capability inputs fail closed. 4. The Report run response includes the same server-owned data projection and    receipt when the request identity is admitted; it never falls back to raw    model/data files. 5. Tests prove Agent/Notebook/Report projections share the same digest and    reject foreign scope, stale catalog, incomplete output, ambiguity, raw    payloads, and forged capabilities.  ## Non-goals  - Do not execute a new data operation in this line; execution remains behind   the existing preview/confirmation/OperationRecord lifecycle. - Do not expose dataframe rows, filesystem paths, arbitrary options, or raw   evidence payloads through a consumer projection. - Do not weaken legacy compatibility tests by treating path-derived input as   authoritative. - Do not claim browser, external-provider, cross-process, full-host, or   release acceptance from focused tests alone.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/7 (14.3%; 14.3 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0; coverage=0/3)

## All failures

- #4 2026-08-21T01:08:30.540Z `projection_path_type_red`; cause_status: `known`; cause: The first central projection test used an exact pathlib.Path type check, which rejected macOS PosixPath before capability minting.; resolution: `resolved`; lesson: Use pathlib-compatible type checks at server boundaries; exact Path identity rejects valid platform path subclasses.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- #2 2026-08-21T00:58:01.839Z `formal_cli_argument_mismatch`; cause_status: `known`; cause: The first formal start command used an unsupported workorder option and was rejected by the repository CLI.; resolution: `resolved`; lesson: Check the repository CLI help before constructing a formal development-line command.
- #3 2026-08-21T01:01:49.957Z `subagent_no_delivery`; cause_status: `known`; cause: The delegated central projection worker stayed running through bounded waits and produced no files or handoff, so it was closed to keep the critical path moving.; resolution: `mitigated`; lesson: Use a bounded implementation slice and close an unresponsive subagent before repeated waits consume the critical path.
- #6 2026-08-21T01:11:38.402Z `review_subagent_no_delivery`; cause_status: `known`; cause: The bounded read-only review worker also stayed running without returning findings, so it was closed and the main line used direct code inspection plus executable tests.; resolution: `mitigated`; lesson: Keep delegated reviews bounded and treat a non-returning reviewer as no evidence; complete the review with explicit local inspection and tests.

## Root causes and solutions

- `bounded-subagent-delivery`: occurrences=1; cause_status: `known`; root cause: The delegated central projection worker stayed running through bounded waits and produced no files or handoff, so it was closed to keep the critical path moving.; solution: `mitigated`
- `formal-cli-surface-check`: occurrences=1; cause_status: `known`; root cause: The first formal start command used an unsupported workorder option and was rejected by the repository CLI.; solution: `resolved`
- `pathlib-subclass-boundary`: occurrences=1; cause_status: `known`; root cause: The first central projection test used an exact pathlib.Path type check, which rejected macOS PosixPath before capability minting.; solution: `resolved`
- `review-no-evidence-claim`: occurrences=1; cause_status: `known`; root cause: The bounded read-only review worker also stayed running without returning findings, so it was closed and the main line used direct code inspection plus executable tests.; solution: `mitigated`

## Added tests

- `tests/test_v189_data_consumer_projection.py`
- `tests/test_v189_data_consumer_projection.py tests/test_v189_data_host_resolver.py tests/test_v189_data_host_port.py tests/test_v189_consumer_catalog_contract.py tests/test_v189_consumer_coverage.py tests/test_v189_agent_notebook_runtime_bootstrap.py tests/test_v189_data_consumer_central_mount.py`

## New rules

- `bounded-subagent-delivery`: line experience occurrence(s)=1
- `formal-cli-surface-check`: line experience occurrence(s)=1
- `pathlib-subclass-boundary`: line experience occurrence(s)=1
- `review-no-evidence-claim`: line experience occurrence(s)=1

## Future guidance

- Check the repository CLI help before constructing a formal development-line command.
- Keep delegated reviews bounded and treat a non-returning reviewer as no evidence; complete the review with explicit local inspection and tests.
- Use a bounded implementation slice and close an unresponsive subagent before repeated waits consume the critical path.
- Use pathlib-compatible type checks at server boundaries; exact Path identity rejects valid platform path subclasses.

## Event index

- #1: `9bb75841-d597-466b-a489-f51a44d77a60` | 2026-08-21T00:57:15.121Z | STATE_CHANGE/line_started | incident=`db561d73-30e0-4767-aab9-30cdea8bd08b` | lesson_key=`frozen-context-before-start` | event_sha256=`786bf6be34ce526f2d41abb32f248f738540e5569272d2377a4f9ebb6c6ab670`
- #2: `11111111-1111-4111-8111-111111111111` | 2026-08-21T00:58:01.839Z | WASTE/formal_cli_argument_mismatch | incident=`22222222-2222-4222-8222-222222222222` | lesson_key=`formal-cli-surface-check` | event_sha256=`bb2a39aa26e8fd44770ece38104ec57a80888d92485c4c007ace254984ca33ad`
- #3: `33333333-3333-4333-8333-333333333333` | 2026-08-21T01:01:49.957Z | WASTE/subagent_no_delivery | incident=`44444444-4444-4444-8444-444444444444` | lesson_key=`bounded-subagent-delivery` | event_sha256=`5db2d3db254fd98a5ae59ac91533796fa5fafdf0c4618de63f6b16e3cf8dd7b2`
- #4: `55555555-5555-4555-8555-555555555555` | 2026-08-21T01:08:30.540Z | FAILURE/projection_path_type_red | incident=`66666666-6666-4666-8666-666666666666` | lesson_key=`pathlib-subclass-boundary` | event_sha256=`b797896ce11daf561daa8bd41bbccedf6e36f25f900dee1bcdba8ccb697c919b`
- #5: `77777777-7777-4777-8777-777777777777` | 2026-08-21T01:08:30.587Z | GATE/data_projection_focused_green | incident=`88888888-8888-4888-8888-888888888888` | lesson_key=`data-projection-focused-green` | event_sha256=`810d248ba2348a7042b2a0dd299b50510e14f0a9a1c29312e604dec107282be9`
- #6: `99999999-9999-4999-8999-999999999999` | 2026-08-21T01:11:38.402Z | WASTE/review_subagent_no_delivery | incident=`aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | lesson_key=`review-no-evidence-claim` | event_sha256=`eea5cb0fd215b92c53db2e851ab971a2bff135726dcd4bfe30fd5e45257841d7`
- #7: `bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb` | 2026-08-21T01:12:00.428Z | STATE_CHANGE/line_completed | incident=`cccccccc-cccc-4ccc-8ccc-cccccccccccc` | lesson_key=`bounded-data-projection-closeout` | event_sha256=`666e82d246707022f9319252308a0e84447d1ee555ee7199437a8e364c165143`
