# Work Order — v1.8.9 Candidate Acceptance Hardening

work_package: v1-8-9-candidate-acceptance-hardening
lane: acceptance-hardening
baseline_commit: 91ee6a05eab2a1892844c8a3057e1e607359a29e
formal_line: v1-8-9-candidate-acceptance-hardening
worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-hardening-integration

## Owned paths

- `backend/workbench/qa/v189_foundation_acceptance.py`
- `scripts/v189_foundation_acceptance_runner.py`
- `tests/test_v189_foundation_acceptance.py`
- `docs/superpowers/objectives/2026-08-21-v1.8.9-candidate-acceptance-hardening-objective.md`
- `docs/superpowers/release-trains/v1.8.9/work-orders/wo-candidate-acceptance-hardening.md`

## Protected boundaries

- Product Agent, Notebook, Report, estimator, provider, and release paths.
- The historical `v1-8-9-foundation-integration` event log; it is append-only
  and must not be repaired by hand.

## Tests and gates

- `PYTHONPATH=backend:tests .venv/bin/pytest tests/test_v189_foundation_acceptance.py -q --disable-warnings`
- candidate-owned deterministic runner on an exact clean SHA
- provider mode returns `NOT_VERIFIED` without fallback
- `PYTHONPATH=backend:tests .venv/bin/python -m compileall -q backend/workbench/qa/v189_foundation_acceptance.py scripts/v189_foundation_acceptance_runner.py tests/test_v189_foundation_acceptance.py`
- `git diff --check`

Known gates: browser, real provider, cross-process, full host gate, full
repository gate, merge, tag, release and deployment remain `NOT_VERIFIED`.
