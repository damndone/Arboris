# Survey remediation-6 formal/document-only correction plan

## Boundary and intent

This line corrects one evidence-source statement in the remediation-5
handoff. It does not change product code, tests, Survey behavior, statistical
results, or any historical record. The exact baseline is
`7a3f0cc301622ffd11e2aceff7aea6ae243d7025`.

## 1. Formal freeze and historical audit

- [x] Create the objective and start
  `v1-8-9-p1-survey-remediation-6` through
  `scripts/devline_control.py start` at the exact baseline.
- [x] Read the resulting Context Pack, global rules, and the relevant
  remediation-4/remediation-5 retrospectives and evidence.
- [x] Run the initial formal `verify` before appending the correction events.
- [x] Preserve remediation-4 and remediation-5 records byte-for-byte.
- [x] Establish from remediation-4 `events.jsonl` that the ordered-stream
  mismatch is `1`: the repeated
  `FOCUSED_PROJECTION_GREEN -> REGRESSION_GREEN` transition is non-contiguous.
- [x] Identify event `15151515-aaaa-4aaa-8aaa-aaaaaaaaaaaa` as the source of
  the separate `impact.state_chain_mismatch=0` value; it is not the
  remediation-4 handoff.

## 2. Append-only source correction

- [x] Append a `GAP` recording the source-authority correction with direct
  evidence to the remediation-4 event stream and target event.
- [x] Append a `REVIEW` recording that remediation-5's handoff attribution
  must be corrected in this new line while the old handoff remains unchanged.
- [x] Append a continuous state audit transition and explicitly record the
  remediation-5 new-line mismatch `0` and remediation-6 new-line mismatch `0`.
- [x] Create and freeze this plan and the new handoff with exact source
  digests, the old/new mismatch distinction, and all remaining boundaries.

## 3. Formal closeout

- [x] Append a state transition binding the frozen handoff digest to
  `DOCUMENTATION_RECONCILED`.
- [x] Append the final state transition binding the same handoff digest to
  `COMPLETED`.
- [x] Append a final `GATE` after the completed state, with the source
  correction resolved and all external boundaries still `NOT VERIFIED`.
- [x] Run formal `verify` and `retrospective` through the CLI.
- [x] Run `git diff --check`, verify exact HEAD and final clean status, remove
  only temporary event-source files, and commit without push, merge, or tag.

## Evidence contract

The historical remediation-4 ordered event stream has mismatch `1`. Its event
`15151515-aaaa-4aaa-8aaa-aaaaaaaaaaaa` carries `impact.state_chain_mismatch=0`,
which is a value in that event's closeout impact, not a handoff-derived value.
The remediation-5 line itself has mismatch `0`; this remediation-6 line also
has mismatch `0`. These facts are recorded append-only and no old record is
rewritten.

## Verification boundary

Formal closeout is `COMPLETED` for documentation only. Product/statistical
revalidation, central Notebook/Report cutover, browser acceptance, external
provider/oracle evidence, host acceptance, full gate, release readiness,
merge, tag, and push remain `NOT VERIFIED`.
