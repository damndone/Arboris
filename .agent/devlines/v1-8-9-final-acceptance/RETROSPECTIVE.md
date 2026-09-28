# Retrospective — v1-8-9-final-acceptance

## Goal

# Workbench v1.8.9 Final Acceptance Objective  ## Objective  On the immutable v1.8.9 C3 candidate, independently verify the real product path for the existing P0/P1 design: Agent and Notebook natural-language planning, server confirmation and admission, workflow truth, persisted evidence, data-operation consumption, classification evidence, Report projection, reload durability, unsafe-request blocking, and the remaining provider/full-gate/release boundaries. This line is evidence-only: it must not repair product behavior or change the C3 candidate.  ## Baseline  - Candidate SHA: \`05362b5697e10eb25fd219da003641f96eeec082\` - Candidate worktree: \`workbench-v1.8.9-foundation-integration\` - Candidate-bound deterministic evaluation: sidecar run must bind the exact   candidate SHA and manifest digests.  ## Required outcomes  - Run the deterministic candidate-bound acceptance runner and retain its   immutable result outside the candidate worktree. - Use a fresh isolated browser/test state to exercise Agent, Notebook, data   operations, classification, Report evidence, reload/recovery, and blocked   unsafe or ambiguous requests. - Record browser-visible evidence with exact candidate SHA, scenario IDs,   timestamps, commands, screenshots or stable evidence references. - If an authorized real provider/configuration exists, record provider-bound   behavior, request/response digests, model/config identity, cost and latency   without secrets; otherwise record \`NOT_VERIFIED\` explicitly. - Run the exact final host gate only in an approved host environment and keep   formal, browser, provider, full-gate and release claims separate. - Produce the final acceptance manifest and layered handoff; do not merge,   push, tag, or release from this line.  ## Non-goals  - No product source, test, provider declaration, frontend component, or C3   lock modification. - No fallback from provider mode to deterministic mode. - No inference from focused tests that a browser/provider/release boundary is   complete.  ## Known limits at start  - Historical Notebook runtime/direct workflow routes may remain unmigrated. - The host identity resolver and real provider may not be configured. - The full gate may require an approved host outside the restricted sandbox.

## Final status

STARTED

## Metrics

- Failure frequency: N/A (sample=0)
- Repeat rate: N/A (sample=0)
- Recurrence rate: N/A (sample=0)
- MTTR: N/A (sample=0; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: N/A (sample=0)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- None recorded.

## Added tests

- No test evidence recorded.

## New rules

- No rule candidate recorded.

## Future guidance

- No guidance recorded.

## Event index

- #1: `21088858-6869-46e5-aa13-a31f79e519b9` | 2026-08-19T16:16:13.411Z | STATE_CHANGE/line_started | incident=`e6d2a0d4-044e-45d1-8339-52e97e6b96a6` | lesson_key=`frozen-context-before-start` | event_sha256=`f3ed3d4942c06833408ea3d4376d0bee0287c3d58984dcbdd47386f967afc83f`
