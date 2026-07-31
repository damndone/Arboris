# Frozen Context Pack

Line: `v1-8-4-model-term-reuse`
Baseline SHA: `6607c2dd51600e1bdb25bdd1fe75487c819127bc`

## Objective
v1.8.4 Model Term Reuse

Objective

Let a declared polynomial term reuse a persisted derived column when that
column provably is the requested term, matching the semantics categorical
expansion already applies to persisted indicators. A workflow that composes a
model on a dataset already carrying a derived power column from an earlier
composed workflow currently fails before fitting, even when the existing
column holds exactly the requested power of exactly the requested source.

Reuse is admitted only after an explicit value comparison against the
server-derived term: identical missing-value positions, and finite values
equal within a strict floating-point tolerance that admits a serialization
round trip while rejecting any difference of analytical consequence. Any other
same-named column is refused, so the workflow fails closed rather than
silently overwriting a column or fitting against a term it did not derive.

Non-goals

No change to categorical reuse, which already compares values. No formula
evaluator, no relaxation of the collision rule for columns that do not match,
and no reuse based on name equality alone. No change to how derived columns
are named or persisted.

Acceptance

Focused tests prove that an exactly equal persisted power column is reused,
that a same-named column whose values differ fails closed, that a column
differing only by serialization round trip is still reused, and that mismatched
missing-value positions are refused. Existing categorical reuse behaviour is
unchanged and the full gate stays green.

## Boundary
- Affected paths: `backend/workbench/model_terms.py`, `tests/test_model_terms.py`, `tests/test_workflow_runtime.py`
- Allowed paths: `backend/workbench/model_terms.py`, `tests/test_model_terms.py`, `tests/test_workflow_runtime.py`
- Protected paths: `.agent/devlines`, `docs/superpowers/specs`, `docs/superpowers/plans`, `scripts/devline_control.py`, `backend/workbench/native_containment`, `backend/workbench/engine/registry.py`
- Dependencies: `v1-8-4-agent-model-composition`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_model_terms.py tests/test_workflow_runtime.py`, `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 bash scripts/gate.sh --full`
- Known gates: `Derived-term reuse must compare values, never names; a same-named column that does not match fails closed.`, `Stop any vite dev server before gating; scripts/gate.sh refuses to run alongside one.`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
