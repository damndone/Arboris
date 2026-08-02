# Retrospective — v1-8-5-notebook-planning-stability

## Goal

# v1.8.5 Notebook planning stability objective  ## Objective  Make source-bound Notebook planning reliably produce a typed option batch when the server has already prepared the required bounded evidence, without adding dataset-specific fallbacks or weakening proposal validation.  ## Design boundary  - Reuse the existing baseline Evidence Pack; do not ask the provider to repeat   completed inspections. - When the baseline is complete, expose only the typed submission tool for the   first provider turn and request that tool explicitly through the generic   model request configuration. - Keep inspection tools available when a real evidence gap remains. - Preserve the long per-provider timeout and user cancellation; do not add a   short aggregate deadline or silently execute a partial plan. - Do not expose private reasoning content or treat it as user-visible evidence. - Do not relax evidence, capability, execution-pin, or Draft validation. - Do not retry a provider stream after it has produced provider activity but   failed to yield a public completion; this avoids duplicate expensive calls.  ## Acceptance  - A complete baseline Evidence Pack causes one typed submission turn and no   inspection turn. - A missing evidence record still permits a bounded inspection followed by a   typed submission. - Provider request configuration reaches the OpenAI-compatible wire payload. - A stream containing only private reasoning activity is not retried as a new   request, and still fails closed if no public completion arrives. - Existing Notebook planning, provider, and contract tests remain green. - Real DeepSeek Notebook planning is retried once through the Workbench UI and   is reported as success or failure with its actual evidence.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/6 (33.3%; 33.3 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=0 ms (sample=2; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-02T03:35:00.000Z `deepseek_v4_tool_choice_incompatible`; cause_status: `known`; cause: DeepSeek V4 thinking requests reject named tool_choice even when a typed tool surface is valid.; resolution: `resolved`; lesson: Provider capability differences must be negotiated at the adapter boundary while preserving the narrowest tool surface.

## All errors

- None recorded.

## All gaps

- #3 2026-08-02T03:36:00.000Z `provider_stream_no_progress`; cause_status: `known`; cause: A streaming provider request could remain pending for the full long provider timeout without a first public event or an actionable UI diagnosis.; resolution: `resolved`; lesson: Keep a long total budget for complex reasoning but enforce a separate no-progress idle boundary and do not retry that same stalled request.

## All waste

- None recorded.

## Root causes and solutions

- `provider-no-progress-boundary`: occurrences=1; cause_status: `known`; root cause: A streaming provider request could remain pending for the full long provider timeout without a first public event or an actionable UI diagnosis.; solution: `resolved`
- `provider-tool-choice-capability`: occurrences=1; cause_status: `known`; root cause: DeepSeek V4 thinking requests reject named tool_choice even when a typed tool surface is valid.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `provider-no-progress-boundary`: line experience occurrence(s)=1
- `provider-tool-choice-capability`: line experience occurrence(s)=1

## Future guidance

- Keep a long total budget for complex reasoning but enforce a separate no-progress idle boundary and do not retry that same stalled request.
- Keep provider-specific transport controls below the provider-neutral Notebook contract and preserve explicit source-column requirements for memory defaults.
- Provider capability differences must be negotiated at the adapter boundary while preserving the narrowest tool surface.

## Event index

- #1: `a69181cf-80db-4f82-82b0-7db66fb5fe87` | 2026-08-02T02:53:17.154Z | STATE_CHANGE/line_started | incident=`71577927-35b2-42d1-ad6f-99ed9922b760` | lesson_key=`frozen-context-before-start` | event_sha256=`228d4bef1d6810f2068dfd59e78afeb86ac8c308fd32ddb3f5021b2c95a2d79c`
- #2: `2e7a8c4f-90b1-4a2d-8c6e-1f3b5d7a9e20` | 2026-08-02T03:35:00.000Z | FAILURE/deepseek_v4_tool_choice_incompatible | incident=`7b1c9d3e-4f56-4a78-8b90-1c2d3e4f5a67` | lesson_key=`provider-tool-choice-capability` | event_sha256=`ad3517899345fda06bf582e3767ae3704d5c20df030f5684aaf8fa941e4f1d6c`
- #3: `3f8b9d5e-1a2c-4e6f-8b0d-2c4e6f8a1b3d` | 2026-08-02T03:36:00.000Z | GAP/provider_stream_no_progress | incident=`8c2d4e6f-9a1b-4c3d-5e7f-0a2b4c6d8e9f` | lesson_key=`provider-no-progress-boundary` | event_sha256=`e49486f9a80b3ac6cca54ebaa29ca84d7534d786f5b96a54c443fd838b9f7146`
- #4: `4a9c1e7b-2d5f-4a8c-9b0e-3d6f1a2c5e78` | 2026-08-02T03:45:00.000Z | REVIEW/notebook_planning_stability_review | incident=`9d3f5a7c-1e2b-4c6d-8f0a-5b7e9c2d4a6f` | lesson_key=`provider-boundary-and-memory-contract` | event_sha256=`199761ff82bd81abb504c444ed4e8a60e39b4651e147d4ac5c59b22c9b2f8596`
- #5: `5b0d2f8a-4c6e-9a1b-3d7f-0e2c5a68b9cd` | 2026-08-02T03:46:00.000Z | GATE/notebook_planning_targeted_gate | incident=`6c1e3a5f-7b9d-4f0a-2c6e-8a1d5b3f9e70` | lesson_key=`bounded-notebook-stability-gate` | event_sha256=`e8e379096335600e9d7b2f0eeb74858f733b9bc93fe0028b7cd0fe395d10d9f3`
- #6: `7d2f4a6b-8c1e-3f5a-9b0d-2c6e7a1f4b89` | 2026-08-02T03:47:00.000Z | STATE_CHANGE/notebook_planning_stability_completed | incident=`8e3a5c7f-1b2d-4f6a-9c0e-7d5b3a1f6e82` | lesson_key=`close-provider-stability-with-browser-evidence` | event_sha256=`54dcf5fa144d64d313d74b68f0336e512fc995d3608f6ce5e0673d4570c60ef1`
