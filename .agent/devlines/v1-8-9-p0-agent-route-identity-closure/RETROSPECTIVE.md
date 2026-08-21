# Retrospective — v1-8-9-p0-agent-route-identity-closure

## Goal

# Workbench v1.8.9 P0 Agent route identity closure  ## Objective  Close the remaining Agent/Notebook route identity seam in which a direct route-function call with \`request=None\` can currently treat caller-supplied actor, session, and project values as if they were server-owned identity. Natural-language preview, confirmation, execution, and evidence paths must all require the same server-bound identity contract. A missing request or missing deployment-bound resolver must fail closed before compiler, proposal, provider, repository, or evidence side effects.  Preserve the real HTTP path and its typed unavailable responses. If a test needs a direct route call, it must use an explicit server-owned test harness that supplies a typed host binding; no boolean, arbitrary callback, raw mapping, or caller assertion may become an authority substitute.  ## Required evidence  - RED probes showing \`request=None\` cannot reach an authority or execution   side effect; - GREEN for the affected Agent route and Agent/Notebook cutover suites; - positive HTTP/typed-host harness coverage remains valid; - compileall and \`git diff --check\`; - formal verification and generated retrospective; - real supervisor/provider, browser, multi-worker, full-host, merge, tag, and   release gates remain separate \`NOT VERIFIED\` evidence.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/4 (25.0%; 25.0 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: N/A (sample=0; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T04:52:44.131Z `agent_route_identity_bypass_red`; cause_status: `known`; cause: Direct Agent/Notebook route calls with request=None previously promoted caller actor, session, and project fields into server authority and could reach cutover or legacy repository paths.; resolution: `open`; lesson: A direct route-function call has no deployment-bound identity and must fail before authority, repository, provider, or evidence access; stale direct-call fixtures must migrate to an explicit HTTP or host harness.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `route-identity-fail-closed`: occurrences=1; cause_status: `known`; root cause: Direct Agent/Notebook route calls with request=None previously promoted caller actor, session, and project fields into server authority and could reach cutover or legacy repository paths.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `route-identity-fail-closed`: line experience occurrence(s)=1

## Future guidance

- A direct route-function call has no deployment-bound identity and must fail before authority, repository, provider, or evidence access; stale direct-call fixtures must migrate to an explicit HTTP or host harness.

## Event index

- #1: `eeeb65a5-253c-44f4-b775-ea190fce7abb` | 2026-08-21T04:30:54.765Z | STATE_CHANGE/line_started | incident=`bfeca647-b3b5-4090-b596-664fc57d8bd7` | lesson_key=`frozen-context-before-start` | event_sha256=`9c20be75a85bdb39dcbdb119febbfd385c3dad88f447c9c190dfafb3ef43af74`
- #2: `789abcde-f012-4345-8678-9abcdef01234` | 2026-08-21T04:52:44.131Z | FAILURE/agent_route_identity_bypass_red | incident=`89abcdef-0123-4456-8789-abcdef012345` | lesson_key=`route-identity-fail-closed` | event_sha256=`e9f9d62268ec02cb539ed6dc3bbae1a57b9844010115b7b1be118f46b528cffc`
- #3: `f0123456-789a-4bcd-8ef0-123456789abc` | 2026-08-21T04:58:00.192Z | GATE/agent_route_identity_focused_green | incident=`01234567-89ab-4cde-8f01-23456789abcd` | lesson_key=`agent-route-identity-closeout` | event_sha256=`75f8f3231c041a80a915492ee676597a78de1be861a6a7f0f7cc8d7b9914f330`
- #4: `12345678-9abc-4def-8012-3456789abcdf` | 2026-08-21T04:58:17.008Z | STATE_CHANGE/agent_route_identity_line_completed | incident=`23456789-abcd-4ef0-8123-456789abcdf0` | lesson_key=`agent-route-identity-line-boundary` | event_sha256=`a99e620660a492d06fd177f1c40a8ed8582522d6f5e9a060af2053fb0239a1ce`
