# Frozen Context Pack

Line: `v1-8-9-final-acceptance`
Baseline SHA: `05362b5697e10eb25fd219da003641f96eeec082`

## Objective
# Workbench v1.8.9 Final Acceptance Objective

## Objective

On the immutable v1.8.9 C3 candidate, independently verify the real product
path for the existing P0/P1 design: Agent and Notebook natural-language
planning, server confirmation and admission, workflow truth, persisted
evidence, data-operation consumption, classification evidence, Report
projection, reload durability, unsafe-request blocking, and the remaining
provider/full-gate/release boundaries. This line is evidence-only: it must not
repair product behavior or change the C3 candidate.

## Baseline

- Candidate SHA: `05362b5697e10eb25fd219da003641f96eeec082`
- Candidate worktree: `workbench-v1.8.9-foundation-integration`
- Candidate-bound deterministic evaluation: sidecar run must bind the exact
  candidate SHA and manifest digests.

## Required outcomes

- Run the deterministic candidate-bound acceptance runner and retain its
  immutable result outside the candidate worktree.
- Use a fresh isolated browser/test state to exercise Agent, Notebook, data
  operations, classification, Report evidence, reload/recovery, and blocked
  unsafe or ambiguous requests.
- Record browser-visible evidence with exact candidate SHA, scenario IDs,
  timestamps, commands, screenshots or stable evidence references.
- If an authorized real provider/configuration exists, record provider-bound
  behavior, request/response digests, model/config identity, cost and latency
  without secrets; otherwise record `NOT_VERIFIED` explicitly.
- Run the exact final host gate only in an approved host environment and keep
  formal, browser, provider, full-gate and release claims separate.
- Produce the final acceptance manifest and layered handoff; do not merge,
  push, tag, or release from this line.

## Non-goals

- No product source, test, provider declaration, frontend component, or C3
  lock modification.
- No fallback from provider mode to deterministic mode.
- No inference from focused tests that a browser/provider/release boundary is
  complete.

## Known limits at start

- Historical Notebook runtime/direct workflow routes may remain unmigrated.
- The host identity resolver and real provider may not be configured.
- The full gate may require an approved host outside the restricted sandbox.

## Boundary
- Affected paths: `docs/superpowers/objectives/2026-08-19-v1.8.9-final-acceptance-objective.md`, `docs/superpowers/evidence/v1.8.9/foundation-candidate-manifest.json`, `docs/superpowers/evidence/v1.8.9/browser-acceptance.md`, `docs/superpowers/evidence/v1.8.9/provider-acceptance.md`, `docs/superpowers/handoff/2026-08-19-v1.8.9-final-acceptance-handoff.md`
- Allowed paths: `docs/superpowers/objectives/2026-08-19-v1.8.9-final-acceptance-objective.md`, `docs/superpowers/evidence/v1.8.9/foundation-candidate-manifest.json`, `docs/superpowers/evidence/v1.8.9/browser-acceptance.md`, `docs/superpowers/evidence/v1.8.9/provider-acceptance.md`, `docs/superpowers/handoff/2026-08-19-v1.8.9-final-acceptance-handoff.md`
- Protected paths: `backend/workbench`, `frontend/src`, `scripts/gate.sh`
- Dependencies: `v1-8-9-foundation-integration`, `v1-8-9-independent-evaluation-remediation`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_foundation_acceptance.py -q`, `PYTHONPATH=backend .venv/bin/python scripts/v189_foundation_acceptance_runner.py --candidate-worktree /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-foundation-integration --candidate-sha 05362b5697e10eb25fd219da003641f96eeec082 --deterministic --output-dir /private/tmp/workbench-v189-final-acceptance`, `cd frontend && npm run typecheck`, `bash scripts/gate.sh --full`
- Known gates: `browser acceptance is separate and must use a fresh isolated browser state`, `real provider and host identity resolver are NOT VERIFIED unless explicitly configured and authorized`, `historical Notebook runtime/direct workflow routes are not claimed migrated`, `formal, full-gate, merge, push, tag and release claims remain separate`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none
