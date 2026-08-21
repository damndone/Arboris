# Work order: v1.8.9 P0 deployment authority adapter

- Objective: `docs/superpowers/objectives/2026-08-21-v1.8.9-p0-deployment-authority-adapter-objective.md`
- Formal line: `v1-8-9-p0-deployment-authority-adapter`
- Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Owned paths

- `backend/workbench/app.py`
- `backend/workbench/agent/authority.py`
- `backend/workbench/agent/planning_contracts.py`
- `tests/test_v189_deployment_authority_adapter.py`

## Protected boundaries

- Do not implement an in-process authority server or choose project/session
  identity from HTTP input.
- Do not change provider declarations, estimator code, evidence packet schema,
  or frontend files.
- Do not weaken the existing endpoint path, inode, peer credential, handshake,
  or non-serialization checks.

## Acceptance

- A deployment-admitted `HostAuthorityHandleV1` can be wrapped by a typed
  application identity resolver that calls the external authority for every
  binding and returns only the validated actor/session/project tuple.
- Missing/dead/forged handle or missing principal resolver fails closed before
  bootstrap mutates app state.
- The host bundle can install the resolver atomically alongside the existing
  Agent/Notebook compiler and Report owner.
- Focused authority/bootstrap tests, compile checks, and `git diff --check`
  pass.

## Known gates

- A real external supervisor/provider, browser acceptance, multi-worker restart,
  full repository gate, merge, tag, and release remain separate evidence.
