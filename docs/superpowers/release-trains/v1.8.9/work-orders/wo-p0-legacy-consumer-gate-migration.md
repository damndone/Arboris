# Work Order: v1.8.9 P0 legacy consumer gate migration

## Owner

Foundation Integration follow-up, limited to compatibility tests and golden
fixtures that are stale against the v1.8.9 typed contracts.

## Dependencies

- v1.8.9 contract lock and P0 workflow/evidence boundaries;
- current server-owned report-document and proposal-store test seams;
- central consumer projection reader.

## Owned paths

- `tests/models/arma_garch/test_deliverables.py`
- `tests/predictive_research/test_consumer_projection_v186.py`
- `tests/test_agent_analysis_loop_lifecycle.py`
- `tests/test_engine_golden.py`
- `tests/golden/*.json`
- this objective/work-order and the formal handoff

## Protected boundaries

Do not modify statistical estimators, evidence persistence, report admission,
runtime authority, frontend, data operations, catalog declarations, or
provider execution. If a production defect is proven, stop and open a separate
formal line with an exact new path allowlist.

## Acceptance

- The required focused command is green on the candidate worktree, with any
  unavailable result represented by the typed contract and stable reason code.
- A reviewer confirms that no raw-result or unbound-writer fallback was
  reintroduced.
- Formal events, verification, and retrospective are generated through
  `scripts/devline_control.py`.

## Known gates

Browser-visible acceptance, external provider behavior, production identity
resolver, multi-worker/restart durability, full host gate, merge, tag, and
release are outside this work order and remain `NOT VERIFIED`.
