# Findings — v1.7.3 Integration

- Integration is a dirty, uncommitted assembly workspace at lock `0251f0a`; it is not yet a release candidate.
- Current native frontend evidence is real Integration evidence: `npm ci --offline --ignore-scripts`, focused repeated-measures tests 38/38, full frontend 1211/1211, and typecheck pass.
- The former full-suite failure was a contract-fixture/test assertion mismatch, not an LMM/UI behavior failure.
- WO-A's risk is filesystem persistence authority: all reads/writes must be capability-bound and not reopen paths or reconstruct authority.
- WO-D's risk is execution attribution: C1 is source-only/fail-closed; C2 must not be represented as executable evidence before host canary acceptance.

## Failure-memory design decisions

- Events are append-only JSONL and validated before append.
- Promotion is deterministic by normalized issue fingerprint: line memory at one event, candidate global rule at two distinct line occurrences, mandatory global rule/automation candidate at three.
- Metrics are computed from event history, not hand-entered totals.
- Token waste is reported as `unknown` unless an event explicitly marks a numeric token measurement as measured; zero is not used as a placeholder.
- The 1/2/3 promotion threshold is event-occurrence based, including repeated churn within one line; limiting it to distinct lines would hide WO-A's repeated persistence boundary failure.
- Token measurements are optional numeric evidence; unknown is recorded as unknown rather than estimated.
