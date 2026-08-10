# Retrospective — v1-8-8-p7-qa-trust-recovery

## Goal

# v1.8.8 P7 QA trust and legacy recovery objective  ## Objective  Harden the P7 acceptance coordinator so its durable ledger remains useful for recoverable QA without presenting caller-authored browser metadata as proof of a human action. Add a reusable witness-attestation boundary that binds a browser observation to one frozen submission and rejects missing, stale, replayed, malformed, or unverifiable witness evidence. Keep the trust labels honest: a local coordinator or local witness does not prove human identity against a malicious same-host operator.  Add an explicit, idempotent migration path for legacy attempt ledgers that have persisted events but no \`.control.json\`. Migration must validate the existing hash chain and manifest authority, preserve the old bytes, write provenance without overwriting existing control, and keep legacy completion records unwitnessed until new witness evidence is collected. Ordinary status, next, and resume operations must not silently migrate.  ## Acceptance  - A witness challenge and signed attestation bind the manifest, submission,   attempt, operation set, Notebook option revision, browser session, visible   confirmation observation, and durable result chain. - The runner accepts only the witness protocol for new verified completion;   arbitrary caller-provided observation/snapshot files cannot upgrade a result   to verified completion. - Missing, invalid, stale, replayed, wrong-submission, wrong-operation,   tampered-payload, and unavailable-witness cases fail closed with an explicit   \`NOT VERIFIED\`/blocked outcome. - Trust output distinguishes coordinator-only, witness-attested, and   human-identity-verified claims. No local path claims the last level. - A valid legacy ledger can be migrated only by the explicit migration command;   malformed, drifted, ambiguous, or already-controlled ledgers are rejected.   Migration is idempotent, append/history preserving, and never silently runs   from status/next/resume. - Historical legacy completed records remain visible but are not counted as   witness-attested acceptance. - Tests are written red-first and every new guard has a behavior-changing   mutation check. Existing P7 acceptance, notebook evidence, golden, and full   gate regressions remain green.  ## Explicit non-scope  - No change to P0/P1/P2 capability contracts or reachability semantics. - No change to Agent production routing, workflow execution, statistical   estimators, artifact formats, or frontend product behavior. - No claim that a same-host process can provide cryptographic proof of human   identity; a future remote/browser-attestation provider remains a separate   adapter. - No automatic rewrite, deletion, or in-place conversion of a legacy ledger.  ## Known gates  - Focused QA witness and P7 acceptance tests. - Backend golden and relevant notebook evidence tests. - \`git diff --check\`. - Formal devline verification. - Host full gate when the focused implementation is complete.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/7 (28.6%; 28.6 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=0 ms (sample=2; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- #2 2026-08-10T04:30:04.000Z `formal_test_path_metadata`; cause_status: `known`; cause: The frozen devline test metadata named tests/test_notebook_acceptance_evidence.py, but the live repository file is tests/test_notebook_evidence.py.; resolution: `resolved`; lesson: Resolve every frozen test path with rg --files before starting a formal devline.
- #6 2026-08-10T05:00:00.000Z `devline_start_metadata`; cause_status: `known`; cause: The first two formal devline start attempts used invalid tag spellings and were rejected before any implementation state was changed.; resolution: `resolved`; lesson: Validate formal identifiers against the live CLI contract before starting a development line.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `formal-test-path-metadata`: occurrences=1; cause_status: `known`; root cause: The frozen devline test metadata named tests/test_notebook_acceptance_evidence.py, but the live repository file is tests/test_notebook_evidence.py.; solution: `resolved`
- `validate-formal-identifiers-first`: occurrences=1; cause_status: `known`; root cause: The first two formal devline start attempts used invalid tag spellings and were rejected before any implementation state was changed.; solution: `resolved`

## Added tests

- `tests/test_qa_witness.py`

## New rules

- `formal-test-path-metadata`: line experience occurrence(s)=1
- `validate-formal-identifiers-first`: line experience occurrence(s)=1

## Future guidance

- A mutation must bypass later guards or use a validly signed altered payload so its own behavior is proven.
- Resolve every frozen test path with rg --files before starting a formal devline.
- Validate formal identifiers against the live CLI contract before starting a development line.

## Event index

- #1: `b36ce05c-d82e-42ac-8d05-22448d61e399` | 2026-08-10T04:13:43.081Z | STATE_CHANGE/line_started | incident=`3a40a086-5a83-493d-a420-e9faaefae835` | lesson_key=`frozen-context-before-start` | event_sha256=`3d21ade93c9693f6719611c2ac6b140724d8f45d5ea4e50494c3d63368869b4e`
- #2: `4c1f1bb4-95c0-4e77-9a84-5b38f7b6f7a1` | 2026-08-10T04:30:04.000Z | ERROR/formal_test_path_metadata | incident=`8d34fd9a-b3d8-4bb2-81da-3dbb6f4f7f22` | lesson_key=`formal-test-path-metadata` | event_sha256=`b182c3794557142918917d4b2ce4afe02f1d8606ca52c9144d83f96980516112`
- #3: `f64e5d4b-5c96-4a92-9e8f-2d8c9312c8c2` | 2026-08-10T04:58:00.000Z | GATE/focused_qa | incident=`3ea8f5d5-4a3d-4f1d-90b1-5b0d4fbc4a61` | lesson_key=`focused-qa-before-full-gate` | event_sha256=`b325f33ea75d7510cb3235ee138a80e5837b1b91ee82158dc56a28534f35dad5`
- #4: `24ed680d-6a7e-4e3d-b90a-4741c4b75bb1` | 2026-08-10T04:59:00.000Z | REVIEW/mutation_guards | incident=`e5bf8f54-5bf8-40ba-9c8d-39d10c6d21b1` | lesson_key=`behavior-changing-mutation-only` | event_sha256=`c608c69e4f9c7219992637e93bf037b2fcb42660559dc56d4374299d197e9502`
- #5: `c50c6b5c-1d4d-46f0-9daa-0c1b7d3dd9fc` | 2026-08-10T04:57:13.000Z | GATE/full_gate_environment | incident=`d6bc8d26-77ae-4ba2-87c7-c66a1a32e14f` | lesson_key=`host-gate-for-containment` | event_sha256=`bba5ce5ee367ff73ab0e496005cbe4fcfb4b01e27a65021fd6a439cc6a6e9e9a`
- #6: `0fb5d377-2eea-4a7a-8f50-40aa3e2afae7` | 2026-08-10T05:00:00.000Z | ERROR/devline_start_metadata | incident=`7e9aa1c8-f404-44bb-a85e-4b37dfd6cf5f` | lesson_key=`validate-formal-identifiers-first` | event_sha256=`e48c8f87335f3f430004b90998fe5a351579028ebb4431cd7a3b279e5a3f1382`
- #7: `8f15bc49-d7cf-41a2-98e8-a61e0acbe5e7` | 2026-08-10T05:02:00.000Z | STATE_CHANGE/line_completed | incident=`a5dcdccf-0957-42cc-b88c-7e8e7f5bcff2` | lesson_key=`separate-local-and-external-proof` | event_sha256=`c149c807a89533cfbe182d391a17b4c6b991c9ebeaedb0f201ed52c6693415af`
