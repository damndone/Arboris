# Survey remediation-5 formal/document-only repair plan

## Boundary and intent

This line repairs formal/document truth only. It does not introduce a new
statistical feature, change Survey or Agent/Notebook/Report product code, or
rerun the remediation-4 P1 implementation. The exact starting baseline is
`8571606b97c6bde5a9ad2a5264c302d4ada0b3ce`.

## 1. Formal freeze and historical audit

- [x] Start `v1-8-9-p1-survey-remediation-5` through
  `scripts/devline_control.py start` at the exact baseline.
- [x] Read the new Context Pack, its frozen global-rule snapshot, and the
  selected historical lessons plus remediation-2/3/4 retrospectives.
- [x] Preserve remediation-4 events, Context Pack, retrospective, objective,
  plan, and handoff as immutable historical evidence.
- [x] Record the independent review as a new `GAP` and `REVIEW`: the old
  ordered state transitions contain one non-contiguous repeat, while the old
  handoff says `state_chain_mismatch=0` and the old plan has four pending
  formal closeout items.

## 2. Resolution evidence and documentation

- [x] Create the new remediation-5 objective with an explicit document-only
  scope, exact baseline, protected old records, state-chain semantics, and
  unchanged `NOT VERIFIED` boundaries.
- [x] Create this plan with every completed item marked `[x]`; no product-code
  or statistical implementation task is claimed.
- [x] Create and freeze the remediation-5 handoff with exact old/new evidence
  digests, inherited P1 projection status, the old mismatch count, new state
  chain semantics, and final status.
- [x] Keep central Notebook/Report cutover, browser, provider/oracle, host,
  full gate, release readiness, merge, tag, and push as `NOT VERIFIED`.

## 3. Formal closeout

- [x] Append the new line's continuous state transition from `STARTED` to
  `AUDIT_REVIEWED` after the historical audit.
- [x] Append a documentation-reconciliation state event bound to the frozen
  remediation-5 handoff digest.
- [x] Append the final state event bound to the same frozen handoff digest,
  ending the new line at `COMPLETED`.
- [x] Run formal `verify` and `retrospective` through the CLI.
- [x] Run `git diff --check`, confirm exact baseline ancestry/current HEAD,
  remove only temporary planning/event-source files, and finish with a clean
  target worktree.

## State-chain semantics

For this line, `state_chain_mismatch` is the count of each ordered
`STATE_CHANGE` whose `state_from` does not equal the preceding state event's
`state_to`. Non-state events do not advance the chain. The new sequence is
`CREATED -> STARTED -> AUDIT_REVIEWED -> DOCUMENTATION_RECONCILED -> COMPLETED`,
so the new line's mismatch count is zero. This does not alter the historical
remediation-4 mismatch count of one.

## Final boundary

The repair is `COMPLETED` as a formal/document-only reconciliation. Product
and statistical claims are inherited from the remediation-4 evidence; no new
statistical functionality is claimed. All external acceptance boundaries
listed above remain `NOT VERIFIED`.
