# Work Order: v1.8.9 P0 Legacy Consumer Gate Migration

## Baseline

- Formal line: `v1-8-9-p0-legacy-consumer-gate-migration`
- Baseline SHA: `f3836408` (the exact full SHA is frozen by formal start)
- Worktree: current integration worktree `/Users/jiayuanren/项目规划`
- Mode: test/fixture/documentation only

## Owned write set

- `tests/models/arma_garch/test_deliverables.py`
- `tests/predictive_research/test_consumer_projection_v186.py`
- `tests/test_agent_analysis_loop_lifecycle.py`
- `tests/test_engine_golden.py`
- `tests/golden/*.json`
- `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-consumer-gate-migration-objective.md`
- `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-legacy-consumer-gate-migration.md`
- `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-consumer-gate-migration-handoff.md`

Formal `.agent/devlines/v1-8-9-p0-legacy-consumer-gate-migration/` records are
managed only by `scripts/devline_control.py`.

## Required tests and gates

```bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  tests/models/arma_garch/test_deliverables.py \
  tests/predictive_research/test_consumer_projection_v186.py \
  tests/test_agent_analysis_loop_lifecycle.py \
  tests/test_engine_golden.py -q
PYTHONPATH=backend .venv/bin/python -m compileall -q backend
git diff --check
```

The first test run is diagnostic and must preserve the complete failure list.
Each correction follows RED evidence and is limited to the owned tests or
golden fixtures. If a failure requires a production change, stop and report it.

## Protected behavior

Do not restore raw model-result, unbound report, caller-owned executor/path, or
untyped proposal-store fallbacks. Do not touch unrelated dirty changes.
