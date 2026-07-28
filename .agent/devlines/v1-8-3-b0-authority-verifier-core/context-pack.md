# Frozen Context Pack

Line: `v1-8-3-b0-authority-verifier-core`
Baseline SHA: `6d19e1b01021babf3d87cac99029e1bb934762a1`

## Objective
v1.8.3 B0 authority/verifier core implementation

Implement the revised B0 boundary from the existing v1.8.3 runtime design:
immutable generic attestation contracts, canonical encoding/digests, trusted
authority/key-provider interfaces, and a fail-closed verifier. B0 must not
execute code, access host files or capability inputs, open network connections,
persist application facts, compute statistical evidence, or implement native
containment.

The implementation must bind invocation/result claims to capability revision,
operation, input, policy, backend subject, attempt, output digest, protocol
revisions, validity cursors, expiry, revocation and replay state. It must not
export an issuer, signer, test key, unsigned fallback, runner, sandbox, model
fields, dataset fields, column names, or fixed-year compatibility path.

Modify only the B0 package and its three focused test files listed in the
allowlist. No product integration, B1 containment, Agent, registry, workflow,
dependency, or UI changes.

## Boundary
- Affected paths: `backend/workbench/custom_capability/__init__.py`, `backend/workbench/custom_capability/contracts.py`, `backend/workbench/custom_capability/canonical.py`, `backend/workbench/custom_capability/verifier.py`, `tests/test_custom_capability_contracts.py`, `tests/test_custom_capability_canonical.py`, `tests/test_custom_capability_verifier.py`
- Allowed paths: `backend/workbench/custom_capability/__init__.py`, `backend/workbench/custom_capability/contracts.py`, `backend/workbench/custom_capability/canonical.py`, `backend/workbench/custom_capability/verifier.py`, `tests/test_custom_capability_contracts.py`, `tests/test_custom_capability_canonical.py`, `tests/test_custom_capability_verifier.py`
- Protected paths: `backend/workbench/agent`, `backend/workbench/identity`, `backend/workbench/capability_factory`, `backend/workbench/native_containment`, `backend/workbench/sandbox.py`, `backend/workbench/code_execution.py`, `frontend`, `scripts`, `docs/superpowers`
- Dependencies: `docs/superpowers/specs/2026-07-25-v1.8.3-custom-capability-runtime-design.md`, `docs/superpowers/specs/2026-07-25-v1.8.3-capability-factory-design.md`, `docs/superpowers/plans/2026-07-25-v1.8.3-capability-lane.md`, `docs/superpowers/plans/2026-07-25-v1.8.3-execution-control.md`, `.agent/development/global_rules.md`, `.agent/devlines/v1-8-3-b0-authority-verifier-redesign/RETROSPECTIVE.md`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_custom_capability_contracts.py tests/test_custom_capability_canonical.py tests/test_custom_capability_verifier.py`, `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_no_exercise_specific_naming.py`, `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 .venv/bin/python scripts/devline_control.py verify --line v1-8-3-b0-authority-verifier-core`
- Known gates: `New worktree must run bash scripts/link-shared-deps.sh with its absolute path before tests.`, `B0 must not start processes, access host files or inputs, open network, persist application facts, compute evidence, or claim native containment.`, `Production construction fails without an allowed authentication backend; test signing is test-only and no issuer/signer/test key is exported.`, `The existing sandbox/code.execute regression is host-gated on managed Darwin and must remain separate evidence from B0.`, `Do not push, open a PR, merge, tag, or release without explicit user authorization.`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
