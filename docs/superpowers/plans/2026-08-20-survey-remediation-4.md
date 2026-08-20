# Survey remediation-4 implementation plan

Goal: close P1-A term/nested omission, P1-B numeric fail-closed validation,
and P1-C bounded P7 recursion at the owned Agent/Notebook/Report projection
boundary, then close one exact-tip formal handoff.

## 1. Formal freeze and audit

- [x] Start only `v1-8-9-p1-survey-remediation-4` at baseline
  `945da48f91101aad99548cf273088a97ad19d163`.
- [x] Read and verify the generated Context Pack, global rules, remediation-3
  Context Pack/retrospective/handoff, and prior spec findings.
- [x] Record review, objective EOF/selector/digest audit, and prior formal
  open/accepted-versus-resolved incident contradictions through the CLI.

## 2. RED probes first

- [x] Add pure probes for empty/overlong terms, empty nested coefficient maps,
  invalid artifact p-values/counts/SE/CI, and deep P7 payloads.
- [x] Add real Agent/Notebook/Report probes proving invalid values do not cross
  packet or LLM context boundaries.
- [x] Run the new probes and record expected RED evidence through the CLI.

## 3. Minimal implementation

- [x] Add bounded term/key and nested-map admission helpers without changing
  Survey engine or Report model code.
- [x] Centralize artifact numeric finite/range/order validation and typed
  unavailable projection behavior.
- [x] Add an explicit iterative or depth-capped P7 nested projection path that
  returns typed unavailable at the cap and never leaks or raises recursion.

## 4. Verification

- [x] Run focused pure and real Agent/Notebook/Report GREEN probes.
- [x] Run Agent context/reads, Report view and selected export projections;
  retain foreign/admitted failures as `NOT VERIFIED`.
- [x] Run full Survey regression, deep payload probes, compileall, and diff
  check.
- [ ] Append GREEN/GAP/GATE/state events through the CLI.

## 5. Exact-tip closeout

- [ ] Commit implementation/tests and capture exact product tip.
- [ ] Freeze remediation-4 handoff with exact tip, selector, digests, and
  explicit `NOT VERIFIED` boundaries.
- [ ] Append final CLI state event referencing the exact handoff digest; run
  formal verify and retrospective until state-chain mismatch and owned
  unresolved findings are zero.
- [ ] Commit handoff and CLI-generated formal records together; no post-closeout
  doc-only commit.
