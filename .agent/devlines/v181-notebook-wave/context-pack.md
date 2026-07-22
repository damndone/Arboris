# Frozen Context Pack

Line: `v181-notebook-wave`
Baseline SHA: `d26d079e4daec6920b0f6527b919c6df1892c635`

## Objective
v1.8.1 Notebook wave (Gate 4/5/6) under ADR-PD-001: 3 feature lanes + 1 evaluation lane from a single contract lock.

## Boundary
- Affected paths: `backend/workbench/contracts/agent/notebook_option.py`, `backend/workbench/contracts/model/ets.py`, `backend/workbench/agent/notebook/`, `backend/workbench/engine/packs/ets/`, `frontend/src/notebook/`, `tests/evaluation/v181/`
- Allowed paths: none
- Protected paths: none
- Dependencies: none
- Tests: none
- Known gates: `scripts/gate.sh`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### wo-b-model-pack (2026-07-20T17:44:54.000Z)

Completed formal devline wo-b-model-pack; final_state=CLOSED; failure_lesson_keys=versioned-public-result-contract
