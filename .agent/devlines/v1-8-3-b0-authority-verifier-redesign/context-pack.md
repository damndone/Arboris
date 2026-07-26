# Frozen Context Pack

Line: `v1-8-3-b0-authority-verifier-redesign`
Baseline SHA: `cc6ae25cb3319b4eda488d327a50c4e9a3f9bb3a`

## Objective
v1.8.3 B0 authority/verifier redesign

Revise the existing v1.8.3 custom capability specification and existing execution plans so B0 is a small, model-agnostic attestation authority/verifier core. B0 must not execute untrusted code or claim native host containment. Real execution, platform sandboxing, process-tree control, and containment assessment move to a later native containment adapter/broker phase.

Keep the design generic and fail closed:
- Python module privacy is not a security boundary.
- Untrusted callers cannot mint verified, source-eligible, evidence, or containment claims.
- Attestations bind protocol, capability, operation, input, policy, backend subject, attempt, output, validity, and replay state.
- Unsupported or stale authority/containment evidence is rejected.
- No algorithm-, dataset-, column-, software-, or year-specific contract fields.

Modify only the four existing authoritative documents listed in the development-line allowlist. Do not create additional specs, objectives, plans, reviews, or handoff documents. Generated FMS evidence is the only permitted new documentation state.

## Boundary
- Affected paths: `docs/superpowers/specs/2026-07-25-v1.8.3-custom-capability-runtime-design.md`, `docs/superpowers/specs/2026-07-25-v1.8.3-capability-factory-design.md`, `docs/superpowers/plans/2026-07-25-v1.8.3-capability-lane.md`, `docs/superpowers/plans/2026-07-25-v1.8.3-execution-control.md`
- Allowed paths: `docs/superpowers/specs/2026-07-25-v1.8.3-custom-capability-runtime-design.md`, `docs/superpowers/specs/2026-07-25-v1.8.3-capability-factory-design.md`, `docs/superpowers/plans/2026-07-25-v1.8.3-capability-lane.md`, `docs/superpowers/plans/2026-07-25-v1.8.3-execution-control.md`
- Protected paths: `backend`, `frontend`, `tests`, `scripts`, `docs/superpowers/specs/2026-07-25-v1.8.3-domain-memory-design.md`, `docs/superpowers/plans/2026-07-25-v1.8.3-memory-lane.md`
- Dependencies: `AGENTS.md`, `.agent/development/global_rules.md`, `.agent/devlines/v1-8-3-document-authority-consolidation/RETROSPECTIVE.md`, `.agent/devlines/v1-8-3-implementation-planning-review/RETROSPECTIVE.md`
- Tests: `git diff --check`, `PYTHONPATH=backend .venv/bin/pytest -q tests/test_no_exercise_specific_naming.py`, `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 .venv/bin/python scripts/devline_control.py verify --line v1-8-3-b0-authority-verifier-redesign`
- Known gates: `Modify only the four existing authoritative v1.8.3 documents; do not create retained spec, objective, plan, review, or handoff documents.`, `Generated .agent/devlines evidence is required FMS state and must be produced only by scripts/devline_control.py.`, `B0 must not execute untrusted code or claim native containment; unsupported or stale authority and containment evidence fails closed.`, `Do not push, open a PR, merge, tag, or release without explicit user authorization.`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
