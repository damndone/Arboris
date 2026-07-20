# Frozen Context Pack

Line: `integration-v1-7-3`
Baseline SHA: `0251f0a30d984bdbb2cfab404e6c646deab60cae`

## Objective
Assemble one evidence-bound v1.7.3 Integration candidate without treating control-plane, lane-local, browser, performance, or containment evidence as interchangeable.

## Boundary
- Affected paths: `frontend/src/workbench/views/TableView.tsx`, `frontend/src/workbench/views/TableView.test.tsx`
- Allowed paths: `frontend/src/workbench/views/TableView.tsx`, `frontend/src/workbench/views/TableView.test.tsx`
- Protected paths: `scripts/gate.sh`
- Dependencies: none
- Tests: none
- Known gates: `full-release-gate`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
