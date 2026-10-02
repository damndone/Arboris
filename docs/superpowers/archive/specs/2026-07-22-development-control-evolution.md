# Making the Failure-Memory / Development-Efficiency systems *evolve*, not just record

> Status: proposal. Written 2026-07-22 after the v1.8.1 Notebook wave, whose
> failures were backfilled into `.agent/devlines/v181-notebook-wave/`.
> Some parts are already done (marked ✅); the algorithm changes are flagged
> **NEEDS SIGN-OFF** because they alter accepted control-plane semantics.

## The loop that already exists

```
events.py        record a failure (hash-chained, fsync'd, anchored)
      │
context_pack.py  freeze a Context Pack when a line starts, carrying forward
      │            the enabled global rules + ≤10 recent lessons
promotion.py     a lesson with a registered PromotionPolicy promotes:
      │            1st occurrence → line-local
      │            2nd distinct incident → one candidate rule
      │            3rd + a source citing the test marker → mechanical rule ENABLED
retrospective.py deterministic per-line summary
```

This is already a feedback loop, not a passive log. The v1.8.1 backfill exercised
it: five events recorded, three registered as `line_experience` (honest first
occurrence), none prematurely promoted.

## Why it currently *records* more than it *evolves* — four gaps

**G1 — the carry-forward step is skippable, so it gets skipped.**
Nothing forces a new line to start from a Context Pack. I proved this the hard
way: I ran v1.8.1 Gate 1/2/3 in one worktree and never consulted ADR-PD-001,
which a pack start would have surfaced. A loop whose most valuable step is
optional is a loop that degrades to a log.

**G2 — promotion is threshold-only; a catastrophic one-off never promotes.**
`PROMOTABLE_EVENT_TYPES` even excludes `WASTE`, and everything needs 3 distinct
incidents. The single most expensive lesson of this wave
(`check-accepted-adrs-before-starting`) is therefore un-promotable by construction
— it will only ever become a rule if it recurs, i.e. if I make the same class of
mistake two more times. That is backwards for high-severity, low-frequency failures.

**G3 — rules accrete but are never retired or scored.**
`promote()` only ever appends to `global-rules.json`. Nothing asks whether an
enabled rule actually prevented recurrence, and nothing retires a rule that has
gone quiet. A Context Pack that carries 200 stale rules is as useless as one that
carries none. Recording without pruning is not evolution.

**G4 — enabled rules are prose, not enforcement.**
`global_rules.md` is Markdown. A mechanical rule only bites if its `test_marker`
is wired into `scripts/gate.sh`. Until then "enabled" means "documented".

## What is already done (✅)

- ✅ **Backfilled this wave** into `.agent/devlines/v181-notebook-wave/` through
  the controlled writer (`create_context_pack` + `append_event`), chain verified
  (6 events, tail `561164d9`). The line was *started from a Context Pack* — the
  first time in v1.8.1 that discipline was actually followed.
- ✅ **Registered PromotionPolicies** for the wave's four durable lessons in
  `DEFAULT_PROMOTION_POLICIES`, so recurrence now enters the pipeline instead of
  vanishing. One is mechanical (`packet-parsers-reject-unknown-fields`, marker
  `tests/contracts/test_v181_contract_lock.py`); three are behavior policies.
- ✅ **Ran `promote()` and generated the retrospective** so the systems actually
  processed the events rather than merely holding them.

## The four evolution mechanisms (proposed)

### E1 — enforce "start from a Context Pack" (closes G1) — **the highest-leverage one**
Add a `scripts/gate.sh` preflight and a matching test that refuse feature work on
a devline lacking a frozen, non-drifted Context Pack, and that fail if any
`docs/superpowers/specs/adr-*` changed since the pack was frozen. This is the
mechanical form of the lesson I filed as `check-accepted-adrs-before-starting`.
**NEEDS SIGN-OFF**: `scripts/gate.sh` is an ADR §6 protected shared file; wiring
it mid-wave affects every lane, so this lands after the current wave merges.

### E2 — a severity fast-path (closes G2)
Let an event carry `severity: high` (a new optional field) and let `promote()`
create a candidate on the **first** high-severity occurrence rather than the
second, and enable on the second rather than the third. High-cost/low-frequency
failures should not have to happen three times to earn a rule.
**NEEDS SIGN-OFF**: changes `promote()` counting semantics + the event schema.

### E3 — rule efficacy feedback + retirement (closes G3)
When a `lesson_key` recurs **after** its rule was enabled, `promote()` emits a
`REVIEW` event flagging the rule as *ineffective* — a signal to refine or
strengthen it, not silently re-count. Symmetrically, a rule with no recurrence
across N lines and M days is proposed for archival. This is the step that turns
"accretes rules" into "watches whether its own rules work" — the actual meaning
of evolution here.
**NEEDS SIGN-OFF**: new `promote()` outputs + a retirement policy field.

### E4 — wire enabled mechanical rules into the gate (closes G4)
`gate.sh` reads `global-rules.json`, and for each enabled mechanical rule runs
its `test_marker`, failing the gate if the marker is missing or red. An enabled
rule then means "enforced", not "written down".
**NEEDS SIGN-OFF**: `scripts/gate.sh` (protected).

## Recommended order

E1 first (it would have prevented this wave's biggest failure), then E4 (makes
existing enabled rules bite), then E3 (keeps the set lean and honest), then E2
(catches the rare-but-costly). E1 and E4 both touch the protected gate and should
land in a dedicated control-plane change, not folded into a feature wave.

## The durable norm (written down here so it is followable now)

Until E1 is mechanically enforced, the standing rule is:

> **Every new version or lane starts by (a) `grep docs/superpowers/specs` for
> accepted ADRs and obeying them, and (b) starting its devline from a frozen
> Context Pack via `create_context_pack`, which emits the `line_started` event.
> Every failure, gap, waste, or external error encountered is recorded as a
> devline event through `append_event` at the time it happens — not in a commit
> message, which `promotion.py` cannot read.**
