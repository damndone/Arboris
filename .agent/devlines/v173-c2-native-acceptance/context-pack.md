# Frozen Context Pack

Line: `v173-c2-native-acceptance`
Baseline SHA: `b5258e966a28d95d2facd2c89a776fe7719b22cc`

## Objective
# C2 Native Acceptance Objective

## Objective

Turn the existing C2 policy and fake-adapter test coverage into a bounded,
native macOS Seatbelt acceptance path for the exact v1.7.3 Integration
candidate. The parent must construct every command, require a fresh canary,
write the audit receipt, and remain the only possible source of an evaluator
verdict.

## Boundary

This line adds only a reviewed native C2 adapter, host identity/probe support,
trusted canary evidence, and collector integration after its reviewed manifest
is bound to one exact candidate SHA. It must keep C1 source-only refusal
intact. It must not weaken `code.execute`, add raw host-Python fallback, admit
caller commands, or make a C2 capability serializable/public.

## Acceptance

The real local Seatbelt canary proves all seven assertions and records an
audit receipt. The exact candidate uses the reviewed collector for bounded,
parent-verified evidence. Any failed canary, policy mismatch, unsupported host,
or malformed output remains non-passing with no fallback.

## Boundary
- Affected paths: `docs/superpowers/release-trains/v1.7.3/integration-foundation/c2-native-acceptance-objective.md`, `backend/workbench/frozen_containment_c2.py`, `backend/workbench/frozen_containment_adapters.py`, `backend/workbench/frozen_containment_canary.py`, `backend/workbench/frozen_containment_execution.py`, `tests/test_frozen_containment_c2_policy.py`, `tests/test_frozen_containment_adapters.py`, `tests/test_frozen_containment_canary.py`, `tests/test_frozen_containment_execution.py`, `docs/superpowers/release-trains/v1.7.3/evidence`
- Allowed paths: `docs/superpowers/release-trains/v1.7.3/integration-foundation/c2-native-acceptance-objective.md`, `backend/workbench/frozen_containment_c2.py`, `backend/workbench/frozen_containment_adapters.py`, `backend/workbench/frozen_containment_canary.py`, `backend/workbench/frozen_containment_execution.py`, `tests/test_frozen_containment_c2_policy.py`, `tests/test_frozen_containment_adapters.py`, `tests/test_frozen_containment_canary.py`, `tests/test_frozen_containment_execution.py`, `docs/superpowers/release-trains/v1.7.3/evidence`
- Protected paths: `backend/workbench/frozen_containment.py`, `backend/workbench/sandbox.py`, `backend/workbench/code_execution.py`, `frontend`, `requirements.txt`, `pyproject.toml`
- Dependencies: `exact integration baseline b5258e9`, `WO-D harness is imported only after manifest review and SHA binding`
- Tests: `C2 policy adapter canary execution tests plus exact native Seatbelt canary`
- Known gates: `C1 remains source-only and no raw Python fallback is permitted`, `C2 pass requires a real native Seatbelt canary and parent-owned audit receipt`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
