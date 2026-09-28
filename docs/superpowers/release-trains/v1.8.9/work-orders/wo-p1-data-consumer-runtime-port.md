# Work Order: v1-8-9-p1-data-consumer-runtime-port

## Objective and baseline

- Formal line: `v1-8-9-p1-data-consumer-runtime-port`
- Branch/worktree: `workbench-v1.8.9-p1-data-consumer-runtime-port` at
  `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p1-data-consumer-runtime-port`
- Baseline/wave lock: `f3836408cf15c3e7380823e5c1b303b4467c7aec`
- Objective: issue the default server-owned typed execution port from a
  project/run/source snapshot; fail closed for missing, foreign, stale, or
  unsupported snapshots and all caller-owned execution authority.

## Owned paths

- `backend/workbench/app.py`
- `backend/workbench/agent/runtime_bootstrap.py`
- `backend/workbench/agent/provider_runtime_contributions.py`
- `backend/workbench/services/data_consumer_execution_resolver.py`
- `tests/test_v189_data_host_port.py`
- `tests/test_v189_agent_notebook_runtime_bootstrap.py`
- this objective, this work order, and the closeout handoff

No other production, test, or documentation file is owned. In particular,
`data_operations.py`, Agent/Notebook consumers, Report, frontend, and all
statistical code are read-only.

## Contract and authority boundary

- The normal runtime gets only server-owned project/run/source snapshot facts.
- It must not accept caller filesystem paths, executor instances, registries,
  or arbitrary objects as production authority.
- Explicit injection is a narrowly typed test seam, never a default runtime
  fallback.
- Resolver and bootstrap reject absent, foreign, stale, and unsupported
  references before dispatch; no permissive reconstruction or implicit
  fallback is allowed.

## Focused verification

- `cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_data_host_port.py ../tests/test_v189_agent_notebook_runtime_bootstrap.py -q`
- `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench`
- `git diff --check`

## Known gates and non-goals

Focused tests prove the typed server-owned host-port contract and local runtime
bootstrap only. They do not prove central Agent/Notebook consumer cutover,
browser acceptance, external providers, performance/containment, the host full
gate, merge/release, or a remote receipt.

Rollback is `git revert <scoped-commit>` after a separately authorized merge;
there is no push, PR, merge, tag, or release authorization in this work order.
