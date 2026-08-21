# Retrospective — v1-8-9-p0-agent-natural-language-route

## Goal

# Work order: v1.8.9 P0 Agent natural-language route bridge  ## Objective  Connect the ordinary HTTP Agent turn to the same server-owned compiler used by the explicit Agent/Notebook cutover endpoints. The provider loop remains durable and budgeted, but analysis requests must reach a typed compiler preview before any confirmation or execution boundary.  ## Required behavior  1. Resolve the real HTTP actor/session/project identity before using a bound    compiler; URL and model claims remain hints only. 2. Expose a narrow compiler-backed preview tool whose source text is the exact    user turn and whose optional fields are validated by the shared compiler. 3. When a compiler is bound for the exact scope, do not expose the legacy    proposal tool as an execution-authority fallback. 4. Preserve AgentCore persistence, step budget, abort, and typed tool evidence. 5. Missing compiler or identity remains a typed unavailable boundary; no direct    compiler execution or client-shaped confirmation is accepted.  ## Non-goals  - No direct execution from a natural-language turn. - No statistical estimator changes. - No browser/provider/cross-process/release acceptance claim. - No merge, push, tag, release, or deployment mutation.  ## Verification boundary  Focused route/compiler tests and \`git diff --check\` prove this bridge only. Full repository, browser, external-provider, cross-process, and release gates remain separate.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/4 (25.0%; 25.0 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T03:18:54.015Z `agent_route_used_raw_session_scope`; cause_status: `known`; cause: The ordinary Agent route looked up the server-owned compiler with the historical raw session ID after the route had switched its runtime registration and identity resolver to an opaque session scope.; resolution: `resolved`; lesson: Use one canonical server-owned project/session scope for registration, lookup, identity assertion, and compiler invocation; never mix a legacy route identifier with an opaque authority key.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `agent-route-authority-lookup-scope`: occurrences=1; cause_status: `known`; root cause: The ordinary Agent route looked up the server-owned compiler with the historical raw session ID after the route had switched its runtime registration and identity resolver to an opaque session scope.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `agent-route-authority-lookup-scope`: line experience occurrence(s)=1

## Future guidance

- Use one canonical server-owned project/session scope for registration, lookup, identity assertion, and compiler invocation; never mix a legacy route identifier with an opaque authority key.

## Event index

- #1: `b7d954dc-134a-4c42-b260-d1564fa1c8da` | 2026-08-21T03:03:07.177Z | STATE_CHANGE/line_started | incident=`6d618808-9f62-48ce-a9f3-eafdb2076b84` | lesson_key=`frozen-context-before-start` | event_sha256=`6f2c1ee4426984dfb6033bcea8ec750f5f26691155d8244474cf3a61217b8e1f`
- #2: `8c05a9dd-05a2-45c8-93f0-7e6c822b9093` | 2026-08-21T03:18:54.015Z | FAILURE/agent_route_used_raw_session_scope | incident=`8c05a9dd-05a2-45c8-93f0-7e6c822b9093` | lesson_key=`agent-route-authority-lookup-scope` | event_sha256=`8e17ea95d97fcccb796408ad7c5b1285bcdba47b4eb5e213a37e03b04a3bf1e5`
- #3: `0d39cd9a-53b2-4fa5-a2c7-8f9b7d42f8a3` | 2026-08-21T03:19:20.874Z | GATE/focused_agent_route_bridge_passed | incident=`0d39cd9a-53b2-4fa5-a2c7-8f9b7d42f8a3` | lesson_key=`focused-agent-route-bridge-gate` | event_sha256=`335c348636ca94d452e2bfd09b75b3c97d03c3a2cb79c7bb75cf925c2e94f5f1`
- #4: `d20d8b7a-38ea-46b0-9f0e-f9e3b2bdb1e7` | 2026-08-21T03:19:46.299Z | STATE_CHANGE/line_completed | incident=`d20d8b7a-38ea-46b0-9f0e-f9e3b2bdb1e7` | lesson_key=`scoped-agent-route-closeout` | event_sha256=`6d0bd8ada764aa16d356c0174bb49ccf0413abac1c0df417082e7689fb6826ba`
