# Frozen Context Pack

Line: `v1-8-8-p7-qa-trust-recovery`
Baseline SHA: `b732abe93e4854fe589a47b83eff2fcdcd841ea1`

## Objective
# v1.8.8 P7 QA trust and legacy recovery objective

## Objective

Harden the P7 acceptance coordinator so its durable ledger remains useful for
recoverable QA without presenting caller-authored browser metadata as proof of
a human action. Add a reusable witness-attestation boundary that binds a
browser observation to one frozen submission and rejects missing, stale,
replayed, malformed, or unverifiable witness evidence. Keep the trust labels
honest: a local coordinator or local witness does not prove human identity
against a malicious same-host operator.

Add an explicit, idempotent migration path for legacy attempt ledgers that have
persisted events but no `.control.json`. Migration must validate the existing
hash chain and manifest authority, preserve the old bytes, write provenance
without overwriting existing control, and keep legacy completion records
unwitnessed until new witness evidence is collected. Ordinary status, next, and
resume operations must not silently migrate.

## Acceptance

- A witness challenge and signed attestation bind the manifest, submission,
  attempt, operation set, Notebook option revision, browser session, visible
  confirmation observation, and durable result chain.
- The runner accepts only the witness protocol for new verified completion;
  arbitrary caller-provided observation/snapshot files cannot upgrade a result
  to verified completion.
- Missing, invalid, stale, replayed, wrong-submission, wrong-operation,
  tampered-payload, and unavailable-witness cases fail closed with an explicit
  `NOT VERIFIED`/blocked outcome.
- Trust output distinguishes coordinator-only, witness-attested, and
  human-identity-verified claims. No local path claims the last level.
- A valid legacy ledger can be migrated only by the explicit migration command;
  malformed, drifted, ambiguous, or already-controlled ledgers are rejected.
  Migration is idempotent, append/history preserving, and never silently runs
  from status/next/resume.
- Historical legacy completed records remain visible but are not counted as
  witness-attested acceptance.
- Tests are written red-first and every new guard has a behavior-changing
  mutation check. Existing P7 acceptance, notebook evidence, golden, and full
  gate regressions remain green.

## Explicit non-scope

- No change to P0/P1/P2 capability contracts or reachability semantics.
- No change to Agent production routing, workflow execution, statistical
  estimators, artifact formats, or frontend product behavior.
- No claim that a same-host process can provide cryptographic proof of human
  identity; a future remote/browser-attestation provider remains a separate
  adapter.
- No automatic rewrite, deletion, or in-place conversion of a legacy ledger.

## Known gates

- Focused QA witness and P7 acceptance tests.
- Backend golden and relevant notebook evidence tests.
- `git diff --check`.
- Formal devline verification.
- Host full gate when the focused implementation is complete.

## Boundary
- Affected paths: `docs/superpowers/objectives/2026-08-10-v1.8.8-p7-qa-trust-recovery-objective.md`, `backend/workbench/qa/p7_acceptance.py`, `backend/workbench/qa/notebook_acceptance_evidence.py`, `backend/workbench/qa/witness.py`, `scripts/p7_acceptance_runner.py`, `tests/test_p7_acceptance_matrix.py`, `tests/test_qa_witness.py`
- Allowed paths: `docs/superpowers/objectives/2026-08-10-v1.8.8-p7-qa-trust-recovery-objective.md`, `backend/workbench/qa/p7_acceptance.py`, `backend/workbench/qa/notebook_acceptance_evidence.py`, `backend/workbench/qa/witness.py`, `scripts/p7_acceptance_runner.py`, `tests/test_p7_acceptance_matrix.py`, `tests/test_qa_witness.py`
- Protected paths: `backend/workbench/agent`, `backend/workbench/engine`, `frontend/src`, `scripts/gate.sh`
- Dependencies: `b732abe`
- Tests: `PYTHONPATH=backend .venv/bin/pytest -q tests/test_p7_acceptance_matrix.py tests/test_qa_witness.py`, `PYTHONPATH=backend .venv/bin/pytest -q tests/test_p7_acceptance_matrix.py tests/test_notebook_acceptance_evidence.py`
- Known gates: `git diff --check`, `PYTHONPATH=backend .venv/bin/pytest -q tests/test_p7_acceptance_matrix.py tests/test_qa_witness.py`, `bash scripts/gate.sh --full`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none
