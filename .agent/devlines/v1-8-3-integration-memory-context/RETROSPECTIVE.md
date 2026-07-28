# Retrospective — v1-8-3-integration-memory-context

## Goal

Complete the v1.8.3 integration slice in the fixed worktree. Connect the already implemented domain-memory control plane to the existing Notebook planning context, Core Agent Trace, and HTTP application assembly. Expose only bounded, non-authoritative memory hints and explicit opt-in controls; keep memory default-off, keep iteration separate from retrieval, and do not add any route that executes code, starts analysis, grants capability admission, or bypasses proposal/risk authorization. Mount the existing memory control/review router through server-owned state, and add minimal Notebook presentation for controls, bounded hints, and explicit review queue. Prove disabled-by-default, hash/freshness separation, ref-only trace payloads, route mounting, and no-automatic-execution behavior with focused backend/frontend tests.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/9 (22.2%; 22.2 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: N/A (sample=0; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0; coverage=0/1)

## All failures

- #2 2026-07-27T03:30:00.000Z `integration_tdd_red`; cause_status: `known`; cause: The new integration tests intentionally referenced the missing context projection and Core Trace registration seams; the NotebookSurface test found that the existing shared surface had not mounted the already-built domain-memory controls and hint list.; resolution: `accepted`; lesson: Keep the Integration slice red before wiring the existing memory components into shared context, trace, HTTP, and Notebook seams.
- #3 2026-07-27T03:36:00.000Z `core_trace_registry_fixture_stale`; cause_status: `known`; cause: The Core Trace exact-registration regression test still listed the pre-integration event set after the ref-only domain-memory retrieval event was intentionally registered.; resolution: `accepted`; lesson: When Integration adds a versioned Core Trace event, update the exact registry fixture through an explicit formal rescope.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- #7 2026-07-27T04:02:00.000Z `quick_gate_repeated_full_suite`; cause_status: `known`; cause: The repository quick gate fell back to another complete backend and frontend suite after equivalent full suites had already completed; the duplicate run was interrupted to avoid spending another long cycle on unchanged evidence.; resolution: `accepted`; lesson: Check gate fallback behavior before rerunning an already completed long suite; prefer targeted gate evidence when full evidence is current.

## Root causes and solutions

- `avoid-duplicate-full-gate`: occurrences=1; cause_status: `known`; root cause: The repository quick gate fell back to another complete backend and frontend suite after equivalent full suites had already completed; the duplicate run was interrupted to avoid spending another long cycle on unchanged evidence.; solution: `accepted`
- `integration-red-before-wiring`: occurrences=1; cause_status: `known`; root cause: The new integration tests intentionally referenced the missing context projection and Core Trace registration seams; the NotebookSurface test found that the existing shared surface had not mounted the already-built domain-memory controls and hint list.; solution: `accepted`
- `trace-registry-fixture-parity`: occurrences=1; cause_status: `known`; root cause: The Core Trace exact-registration regression test still listed the pre-integration event set after the ref-only domain-memory retrieval event was intentionally registered.; solution: `accepted`

## Added tests

- No test evidence recorded.

## New rules

- `avoid-duplicate-full-gate`: line experience occurrence(s)=1
- `integration-red-before-wiring`: line experience occurrence(s)=1
- `trace-registry-fixture-parity`: line experience occurrence(s)=1

## Future guidance

- Check gate fallback behavior before rerunning an already completed long suite; prefer targeted gate evidence when full evidence is current.
- Keep the Integration slice red before wiring the existing memory components into shared context, trace, HTTP, and Notebook seams.
- When Integration adds a versioned Core Trace event, update the exact registry fixture through an explicit formal rescope.

## Event index

- #1: `68503403-8faf-41d3-89b8-b826baae0a47` | 2026-07-27T07:26:30.589Z | STATE_CHANGE/line_started | incident=`cb6c37ce-efd2-4e1c-b51c-72f83449af87` | lesson_key=`frozen-context-before-start` | event_sha256=`532f7116b04cc13331dfa772b2e6e64fcd0ef1f81ceb5ab1fbb2515a85265896`
- #2: `9d7d6f3a-0c17-4d70-8d58-6f6e6e09a4b1` | 2026-07-27T03:30:00.000Z | FAILURE/integration_tdd_red | incident=`3e2b7c6b-2c36-4b1a-9b6a-1a3e1d4b7f90` | lesson_key=`integration-red-before-wiring` | event_sha256=`cc8ef2f1224a73766b8ff90be61df51773ac470e3e244c8a1c7c5bbc7826913b`
- #3: `f4f2d6ae-7b10-4b2f-9f98-2ea6e0a12b5c` | 2026-07-27T03:36:00.000Z | FAILURE/core_trace_registry_fixture_stale | incident=`b8edbc24-9f14-4f36-8578-7a3d3e6b1d21` | lesson_key=`trace-registry-fixture-parity` | event_sha256=`381dfdabcdd3af662825e9ceb114a98cdfac8e0c312282791d07ab41cf49d726`
- #4: `0f058735-ffb4-4b82-9824-c25cc5b4f471` | 2026-07-27T07:36:35.973Z | STATE_CHANGE/context_rescope_required | incident=`cc8172e3-a33a-45cb-be21-fdb317c03234` | lesson_key=`context-pack-rescope` | event_sha256=`6c1924db3a3cd49cd49e6bda7a0afc411c81ed32ed9645d1ae117d327436621b`
- #5: `716c9c07-eb3b-4af7-8d5d-09dbd71f1071` | 2026-07-27T07:36:35.976Z | STATE_CHANGE/context_rescoped | incident=`600eba17-9833-4fff-9add-475aedabbbe0` | lesson_key=`context-pack-rescope` | event_sha256=`7a9d84123bc72b4ffa3b8cd3170d09addf49d39b8c4373c0a842baccd4124e8d`
- #6: `c6e97b45-4d2a-4f9a-9c10-5f2de1a8790c` | 2026-07-27T03:50:00.000Z | GATE/full_backend_gate_classified | incident=`2c2f91e1-9c67-4d5e-9e3c-0cbf4de9a8f1` | lesson_key=`full-gate-host-and-baseline-separation` | event_sha256=`aa5075b2a64648d415617b89ae8328c13a47a80cdb0f2b6019c90ef80ab3703d`
- #7: `9aefc1a8-2ed4-42b7-967e-0f740ea2d4c8` | 2026-07-27T04:02:00.000Z | WASTE/quick_gate_repeated_full_suite | incident=`e9c6fa3b-36e0-4f6b-9b0d-3f2c8e4d7a51` | lesson_key=`avoid-duplicate-full-gate` | event_sha256=`75c4f16deddd6999433afb5c72057735248e97fa665562baed0521414b864a36`
- #8: `7b9d0c2a-3f4e-4a61-8c2d-1e5f7a9b6c30` | 2026-07-27T04:05:00.000Z | GATE/integration_targeted_green | incident=`4a1e7c9b-2d5f-46b8-9c30-7e2a5d1f8b64` | lesson_key=`integration-targeted-gate-green` | event_sha256=`6a0fa5b1356d0b047e022183b26cee81477b03a334bb68c7f2bfc6f861e8eddb`
- #9: `8c1e7d4a-5f2b-46a9-9d30-7e4b2f6c1a85` | 2026-07-27T04:06:00.000Z | STATE_CHANGE/integration_completed | incident=`5b2f8d1c-7e4a-49c3-0d6f-1a8e5c2b7d90` | lesson_key=`close-after-targeted-evidence` | event_sha256=`16638687728747105003c1426195c912f989f3eb86dd4bb330366fa330f4c3ab`
