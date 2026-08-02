# Retrospective — v1-8-5-notebook-planning-resilience

## Goal

# v1.8.5 Notebook planning resilience objective  ## Objective  Test the Notebook planning boundary against plausible provider, transport, planner, and cancellation failures, then fix only general defects proved by those tests. The result must remain typed, evidence-bound, fail-closed, and safe to retry without silently duplicating provider work.  This is a resilience slice on top of the existing Notebook planning stability slice. It does not add model families, change the frontend, expose private chain-of-thought, or add dataset-specific behavior.  ## Failure matrix  The test harness must cover at least:  1. provider returns no event until the idle boundary; 2. provider emits private reasoning activity, then disconnects or ends without    public text/tool completion; 3. provider emits malformed JSON, malformed tool-call fragments, an unknown    tool, or a tool call with invalid arguments; 4. provider emits duplicate done/tool events or repeats a submission; 5. provider disconnects after a valid partial tool call and after a valid    complete submission; 6. caller cancellation races with provider completion and with timeout; 7. evidence is incomplete, contradictory, stale, oversized, or contains an    unsupported artifact type; 8. a proposal is submitted with missing source columns, invalid memory    defaults, duplicate option IDs, too many options, or an invalid risk/    evidence field.  Each case must assert an observable terminal state, bounded provider-call count, no execution side effect, and a diagnostic that distinguishes provider failure, cancellation, timeout, malformed output, and contract rejection.  ## Invariants  - A request is never retried after a provider activity, completed tool call, or   user cancellation unless the retry policy explicitly proves no actionable   provider progress occurred. - Invalid or ambiguous model output never becomes a persisted option batch. - A valid option batch is persisted at most once per planning attempt. - Cancellation is idempotent and wins over a late provider completion. - Memory may fill only registered fields after required source fields are   declared; it cannot invent dataset columns or model inputs. - The planner never executes a proposal. It only produces a validated option   batch for the existing confirmation and authorization lifecycle. - Private reasoning remains internal; only observable activity stages and   safe diagnostics are exposed.  ## Test-first delivery  1. Add deterministic fault-injection adapters and failing tests for the matrix    above. Record at least one failure before each production fix. 2. Fix the smallest provider-neutral or adapter-boundary defect that explains    the failure. Do not loosen validation to make malformed responses pass. 3. Run the focused Notebook/provider/memory suite and inspect provider-call    counts, terminal states, and persisted batches. 4. Run one real Workbench DeepSeek request through the visible Notebook UI;    verify success, cancellation, and failure presentation without using a    backend upload shortcut.  ## Acceptance and non-claims  Acceptance requires the fault-injection matrix to pass, no duplicate provider calls in the tested races, the focused suite to remain green, and one real DeepSeek Notebook planning request to complete or fail with an actionable diagnosis. This slice does not claim every provider is compatible, that all complex prompts complete within a fixed wall-clock time, or that full release, frontend, deployment, or native-containment gates have passed.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/7 (42.9%; 42.9 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: median=0 ms (sample=3; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-02T03:48:04.000Z `partial_tool_call_retry_gap`; cause_status: `known`; cause: A provider disconnected after emitting a valid partial tool-call fragment, but the adapter had not recorded public provider progress and retried the request.; resolution: `resolved`; lesson: Record recoverable provider progress as soon as a valid tool-call argument prefix is received, so disconnects after partial calls are not retried.
- #3 2026-08-02T03:48:04.000Z `abort_signal_hung_stream_gap`; cause_status: `known`; cause: A provider stream remained pending indefinitely while the caller cancellation signal was already set, and the model adapter waited only on provider progress.; resolution: `resolved`; lesson: Wait for provider progress and the abort signal as competing events, and make cancellation win over a late provider completion.
- #4 2026-08-02T03:48:04.000Z `complete_nonobject_tool_json_gap`; cause_status: `known`; cause: A complete non-object tool argument payload was treated as a recoverable partial prefix, so the malformed response was not given the bounded retry path.; resolution: `resolved`; lesson: Distinguish a recoverable JSON object prefix from a complete scalar or array payload before deciding whether provider progress prevents retry.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `abort-signal-races-provider-stream`: occurrences=1; cause_status: `known`; root cause: A provider stream remained pending indefinitely while the caller cancellation signal was already set, and the model adapter waited only on provider progress.; solution: `resolved`
- `complete-nonobject-tool-json-remains-retryable`: occurrences=1; cause_status: `known`; root cause: A complete non-object tool argument payload was treated as a recoverable partial prefix, so the malformed response was not given the bounded retry path.; solution: `resolved`
- `partial-tool-progress-prevents-retry`: occurrences=1; cause_status: `known`; root cause: A provider disconnected after emitting a valid partial tool-call fragment, but the adapter had not recorded public provider progress and retried the request.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `abort-signal-races-provider-stream`: line experience occurrence(s)=1
- `complete-nonobject-tool-json-remains-retryable`: line experience occurrence(s)=1
- `partial-tool-progress-prevents-retry`: line experience occurrence(s)=1

## Future guidance

- Distinguish a recoverable JSON object prefix from a complete scalar or array payload before deciding whether provider progress prevents retry.
- Keep resilience fixes at the provider and adapter boundary, expose only observable activity and diagnostics, and retain confirmation-gated planning semantics.
- Record recoverable provider progress as soon as a valid tool-call argument prefix is received, so disconnects after partial calls are not retried.
- Wait for provider progress and the abort signal as competing events, and make cancellation win over a late provider completion.

## Event index

- #1: `ce2368e6-16f2-4eb9-9770-3ba1088a3d66` | 2026-08-02T03:36:00.479Z | STATE_CHANGE/line_started | incident=`052d0401-efca-47f2-ab63-8cd6cb5e3ce1` | lesson_key=`frozen-context-before-start` | event_sha256=`72eab6286f4acdde42eff4cdeaa390345f0da711413b6efa2e5c973b60aab446`
- #2: `e3d26cc4-36d2-4c1b-8c5e-8f8e9e44d7b1` | 2026-08-02T03:48:04.000Z | FAILURE/partial_tool_call_retry_gap | incident=`1dca3bc8-2b4b-478b-8d55-8de86dc7cc23` | lesson_key=`partial-tool-progress-prevents-retry` | event_sha256=`4a3243de25adc925ba04047e9aca1ff31ba6e691b728d024f794f0a66a5725d1`
- #3: `b7df2a4a-66c6-4ed2-88f0-4a0c30f09d7e` | 2026-08-02T03:48:04.000Z | FAILURE/abort_signal_hung_stream_gap | incident=`5d1bc3ef-3fdf-47a8-8f77-27b9076a1b1c` | lesson_key=`abort-signal-races-provider-stream` | event_sha256=`86dacec5722bc331c0e362ef7c1848de3609c4e7d688e060e166b5f9ca569dee`
- #4: `ca5f2b1c-2b9e-46b0-9e11-73b4b92bcff4` | 2026-08-02T03:48:04.000Z | FAILURE/complete_nonobject_tool_json_gap | incident=`b2c4a8ae-1870-4e1a-bf16-3f32b5ee1ee4` | lesson_key=`complete-nonobject-tool-json-remains-retryable` | event_sha256=`8a09874abba32c1d6f394cde95ed2cc66032263580a3d35a64dcc6b02e44b778`
- #5: `f0c9d42a-18f4-48ac-b91a-0f4a1d7e63e2` | 2026-08-02T03:48:04.000Z | REVIEW/notebook_resilience_review_verified | incident=`f0c9d42a-18f4-48ac-b91a-0f4a1d7e63e2` | lesson_key=`resilience-boundary-review-verified` | event_sha256=`698b910f66f91d1d7954a78cd789786e00f94c1ae2fc390a06217127b267f64a`
- #6: `b11d4a95-a0dd-4f39-9b7b-a16721a8b54a` | 2026-08-02T03:50:30.000Z | GATE/notebook_resilience_focused_gate_passed | incident=`b11d4a95-a0dd-4f39-9b7b-a16721a8b54a` | lesson_key=`notebook-resilience-focused-gate-passed` | event_sha256=`9384626665754a98660a61b864176c25c43408e433444c8aa815c432fb33391e`
- #7: `c8f5c29a-c2d7-49af-a8d6-9e4f2c42e71d` | 2026-08-02T03:50:30.000Z | STATE_CHANGE/notebook_resilience_slice_completed | incident=`c8f5c29a-c2d7-49af-a8d6-9e4f2c42e71d` | lesson_key=`close-notebook-resilience-slice` | event_sha256=`e829d8d272e3caba5fc7fe020c0ac2d76863ec5e355baa644e2c9c6937f5f9c1`
