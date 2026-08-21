# Work order: v1.8.9 P0 Agent route identity closure

- Objective: `docs/superpowers/objectives/2026-08-21-v1.8.9-p0-agent-route-identity-closure-objective.md`
- Formal line: `v1-8-9-p0-agent-route-identity-closure`
- Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Allowed paths

- `backend/workbench/http/agent_routes.py`
- `tests/test_agent_routes.py`
- `tests/test_v189_agent_route_identity_boundary.py`
- this objective and work order

## Protected paths

- `backend/workbench/agent/**`
- `backend/workbench/evidence/**`
- `backend/workbench/providers/**`
- `backend/workbench/engine/**`
- `frontend/**`
- all prior formal records, root checkout, and other worktrees

## Required tests

```text
PYTHONPATH=backend:tests .venv/bin/python -m pytest tests/test_v189_agent_route_identity_boundary.py tests/test_agent_routes.py tests/test_v189_agent_natural_language_route.py tests/test_v189_agent_notebook_cutover.py -q --disable-warnings
PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench/http/agent_routes.py tests/test_agent_routes.py tests/test_v189_agent_route_identity_boundary.py
git diff --check
```

## Safety rule

Do not restore a direct-call compatibility bypass. The only valid positive
test seam is a typed, server-owned host binding with exact scope/session/
principal checks and zero caller-controlled authority metadata.

