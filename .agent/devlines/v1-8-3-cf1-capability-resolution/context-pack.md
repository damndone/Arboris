# Frozen Context Pack

Line: `v1-8-3-cf1-capability-resolution`
Baseline SHA: `d351779f4e24a3854a2d45d9da6ce43e42799160`

## Objective
# v1.8.3 CF1 Capability Factory resolution

Implement the CF1 capability contracts, append-only stores, native-pack projection,
fixed trust-order resolution, and shared validity cursor semantics. Define
immutable requirement/profile/implementation/policy/candidate/selection/binding
records; reject mutable identity and stale validity; represent unavailable,
incomparable, tied, and no-dominant-choice outcomes explicitly. Consume only
verified B0/B1 references and cursors; do not execute capability code, install
dependencies, access user data, mount routes, or modify Agent, Notebook, Graph,
Draft, Run, frontend, native containment, identity, custom capability, sandbox,
or code.execute paths. Keep trace contracts package-local and defer Core Trace
registration to Integration.

Acceptance is limited to CF1 protocol, registry, resolver, freshness, and trace
tests plus engine capability and naming gates. It does not claim Agent readiness,
dependency acquisition, statistical validation, containment acceptance, or
Notebook execution.

## Boundary
- Affected paths: `backend/workbench/capability_factory`, `tests/test_capability_factory_contracts.py`, `tests/test_capability_factory_control.py`, `tests/test_capability_factory_registry.py`, `tests/test_capability_factory_resolver.py`, `tests/test_capability_factory_freshness.py`, `tests/test_capability_factory_trace.py`
- Allowed paths: `backend/workbench/capability_factory/__init__.py`, `backend/workbench/capability_factory/contracts.py`, `backend/workbench/capability_factory/store.py`, `backend/workbench/capability_factory/policy.py`, `backend/workbench/capability_factory/control.py`, `backend/workbench/capability_factory/native.py`, `backend/workbench/capability_factory/registry.py`, `backend/workbench/capability_factory/resolver.py`, `backend/workbench/capability_factory/freshness.py`, `backend/workbench/capability_factory/trace_contracts.py`, `tests/test_capability_factory_contracts.py`, `tests/test_capability_factory_control.py`, `tests/test_capability_factory_registry.py`, `tests/test_capability_factory_resolver.py`, `tests/test_capability_factory_freshness.py`, `tests/test_capability_factory_trace.py`, `tests/test_engine_capabilities.py`
- Protected paths: `backend/workbench/agent`, `backend/workbench/identity`, `backend/workbench/custom_capability`, `backend/workbench/native_containment`, `backend/workbench/engine/registry.py`, `backend/workbench/sandbox.py`, `backend/workbench/code_execution.py`, `tests/test_sandbox.py`, `tests/test_code_execution.py`, `frontend`, `scripts`, `docs/superpowers`
- Dependencies: `v1-8-3-b0-authority-verifier-core`, `v1-8-3-core1-local-identity`, `v1-8-3-b1-native-containment`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_capability_factory_contracts.py tests/test_capability_factory_control.py tests/test_capability_factory_registry.py tests/test_capability_factory_resolver.py tests/test_capability_factory_freshness.py tests/test_capability_factory_trace.py tests/test_engine_capabilities.py tests/test_no_exercise_specific_naming.py`, `git diff --check`, `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 .venv/bin/python scripts/devline_control.py verify --line v1-8-3-cf1-capability-resolution`
- Known gates: `CF1 does not modify or integrate Agent, Notebook, Draft, Run, Graph, frontend, or Core Trace seams.`, `CF1 never executes capability code, installs dependencies, or treats a resolver decision as statistical or containment evidence.`, `Unavailable, stale, tied, incomparable, and no-dominant-choice outcomes remain explicit; no weaker fallback or fabricated unique winner.`, `B1 native containment is a separate evidence gate; the current macOS host may report typed unsupported and CF1 must not convert that into support.`, `Do not push, open a PR, merge, tag, or release without explicit user authorization.`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
