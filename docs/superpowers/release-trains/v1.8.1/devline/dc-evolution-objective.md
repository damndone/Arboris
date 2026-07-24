# Objective — development-control evolution (E1–E4)

Make the Failure-Memory and Development-Efficiency systems enforce their own
use and begin to improve themselves, per
docs/superpowers/specs/2026-07-22-development-control-evolution.md.

E1  gate refuses feature changes not covered by a non-drifted devline Context Pack.
E2  severity fast-path: a high-severity event promotes one occurrence earlier.
E3  rule-efficacy feedback (recurrence-after-enable) + quiet-rule retirement proposal.
E4  gate runs each enabled mechanical rule's test marker, so "enabled" means "enforced".

Constraints: do not break the existing 26 development-control tests or the gate's
current behaviour for non-feature changes; every step is TDD-first.
