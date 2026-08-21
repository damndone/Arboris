# Retrospective — v1-8-9-central-evidence-consumer-mount

## Goal

# v1.8.9 Central Evidence Consumer Mount Objective  ## Objective  Mount the already-persisted, typed v1.8.9 evidence into the real central Agent, Notebook, and Report consumer paths. The central surfaces must read a server-owned evidence envelope and its receipt, project only the consumer contract, and return \`UNAVAILABLE\`/\`DEGRADED\` when the evidence is missing, stale, foreign, or unverifiable. They must never reconstruct statistical results from raw model-result JSON or infer a result from labels.  ## Required behavior  1. A central run-detail request is bound to server-observed actor, project,    session, run, model-run, and confirmation identity before it reads a    projection. 2. Agent and Notebook result tools use the same typed persisted-evidence    source and the same projection registry. A natural-language request may    choose the consumer surface, but cannot choose a filesystem path, raw    result packet, provider callable, or alternate model result. 3. Report view-model and export routes consume only the owner-admitted typed    projection and receipt. If the artifact hash, receipt, registry, or scope    is invalid, the response is an explicit unavailable/degraded packet rather    than a guessed table or recalculated statistic. 4. Existing compatibility fields remain visibly non-authoritative until they    are backed by the typed evidence projection. No second capability table or    consumer-specific statistical calculation is introduced. 5. Tests cover the same path for Agent, Notebook, and Report, including    missing/stale/foreign evidence, forged identity, malformed digest, raw    model-result fallback, and positive persisted-evidence rendering.  ## Non-goals  - No new estimator/model family or statistical formula. - No native \`.sav/.zsav/.dta\` dependency work. - No browser/provider/cross-process/full-gate/release claim unless separately   executed on the candidate SHA. - No migration of the legacy \`prediction.py\` classification entrypoint in   this line; that is a separate typed host-port production migration.  ## Acceptance boundary  Focused central consumer tests may prove the server route/service/view-model join. Browser-visible acceptance, real provider startup, cross-process authority persistence, full repository gate, and release readiness remain \`NOT VERIFIED\` until explicitly run.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/5 (40.0%; 40.0 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T17:28:45.955Z `central_consumer_route_red`; cause_status: `known`; cause: The first central run-detail probe found that the route kept model_results empty but did not expose the server-owned typed results projection or receipt.; resolution: `resolved`; lesson: A compatibility field being empty is not a completed consumer mount; the central response must carry the owner-bound typed projection and receipt explicitly.

## All errors

- None recorded.

## All gaps

- #3 2026-08-20T17:29:06.154Z `adjacent_legacy_agent_suite_gap`; cause_status: `known`; cause: The adjacent Agent context suite still uses legacy model-result fixtures without the server-owned artifact binding required by the existing strict reader; the current central mount does not change that reader or its fixtures.; resolution: `accepted`; lesson: Keep focused consumer acceptance separate from legacy fixture migration; carry the fixture gap explicitly instead of weakening the strict artifact binding.

## All waste

- None recorded.

## Root causes and solutions

- `central-results-projection-explicit`: occurrences=1; cause_status: `known`; root cause: The first central run-detail probe found that the route kept model_results empty but did not expose the server-owned typed results projection or receipt.; solution: `resolved`
- `legacy-agent-fixture-gap-separated`: occurrences=1; cause_status: `known`; root cause: The adjacent Agent context suite still uses legacy model-result fixtures without the server-owned artifact binding required by the existing strict reader; the current central mount does not change that reader or its fixtures.; solution: `accepted`

## Added tests

- No test evidence recorded.

## New rules

- `central-results-projection-explicit`: line experience occurrence(s)=1
- `legacy-agent-fixture-gap-separated`: line experience occurrence(s)=1

## Future guidance

- A compatibility field being empty is not a completed consumer mount; the central response must carry the owner-bound typed projection and receipt explicitly.
- Keep focused consumer acceptance separate from legacy fixture migration; carry the fixture gap explicitly instead of weakening the strict artifact binding.

## Event index

- #1: `2e3459b2-f0ec-4ac8-8bd8-4da940185f29` | 2026-08-20T17:08:40.473Z | STATE_CHANGE/line_started | incident=`633af1be-dad3-4d7c-a33e-172765f06fa6` | lesson_key=`frozen-context-before-start` | event_sha256=`9d6c688bb8eeb428d29a239d797839912984274d59356efe0ee8bf36759c5687`
- #2: `c1e8a4f7-5b2d-4f90-8a16-2d7c9e3b5f64` | 2026-08-20T17:28:45.955Z | FAILURE/central_consumer_route_red | incident=`d3a4f1c8-6e27-4b90-8a15-2c7e9f3b5d64` | lesson_key=`central-results-projection-explicit` | event_sha256=`2ec5081545441ad14e7f1fae644b07233dbe2b445224b57c6c3407c8af61485e`
- #3: `e7a1c4f9-5b26-4d80-9a13-2f7c8b3e6d54` | 2026-08-20T17:29:06.154Z | GAP/adjacent_legacy_agent_suite_gap | incident=`f4a7c1e9-5b26-4d80-9a13-2f7c8b3e6d54` | lesson_key=`legacy-agent-fixture-gap-separated` | event_sha256=`5caeecb68c8014f97f848883a45a042339f406496cd18ff595ae4c3d8fc1ee53`
- #4: `a9c4f1e7-5b26-4d80-8a13-2f7c9b3e6d54` | 2026-08-20T17:30:29.835Z | GATE/central_consumer_focused_green | incident=`b4a7c1e9-5d26-4f80-9a13-2c7e8b3d6f54` | lesson_key=`central-consumer-focused-gate-boundary` | event_sha256=`7f47833f793472ae23158e62f85040d2a13f561f704ba6c9486ddf6bce8e91a7`
- #5: `d7a1c4f9-5b26-4e80-9a13-2f7c8b3e6d54` | 2026-08-20T17:30:44.507Z | STATE_CHANGE/line_completed | incident=`f4a7c1e9-5d26-4b80-9a13-2c7e8b3d6d54` | lesson_key=`central-consumer-focused-gate-boundary` | event_sha256=`6a5c40fbbd1ff78d4e2108676e71b7eb2695c03d7578f1e3edbd94a10c2e9313`
