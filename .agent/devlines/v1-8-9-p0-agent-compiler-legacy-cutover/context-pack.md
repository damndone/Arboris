# Frozen Context Pack

Line: `v1-8-9-p0-agent-compiler-legacy-cutover`
Baseline SHA: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`

## Objective
# Workbench v1.8.9 — Agent Compiler C0 Legacy Authority Cutover

## Objective

Migrate the Agent Compiler's current production callers away from the retired
`ServerCompilationRecordIssuerV1`. `PlanCompiler` and the agent-local planning
facade must not construct, invoke, or re-export that issuer. Compilation must
either use an explicitly injected host compiler authority port or fail closed
through a stable typed integration-required failure. A test-only adapter may
exercise the existing local fixtures, but it must not become a production
authority path.

This line covers only the Agent Compiler downstream callers. It does not modify
the Workflow Truth, Evidence Core, frontend, contract-lock files, or the real
deployment host implementation.

Baseline: Contract Lock C0 `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`
Dependency: `v1-8-9-p0-agent-compiler-remediation-5`; C0 legacy issuer cutover
is an upstream integration dependency.

## Required outcomes

- `PlanCompiler` has no live import, construction, or call to
  `ServerCompilationRecordIssuerV1`.
- `planning_contracts` does not re-export the retired issuer and exposes only
  the host compiler port plus typed rejection seam needed by downstream code.
- No caller-provided local object, store, or test fixture can silently become a
  production compiler authority.
- Host-backed compilation is represented by a typed port result and is checked
  before it enters the replay store; malformed or unavailable host results fail
  closed.
- Existing compiler validation, scope binding, selection, effect/risk/port
  checks, and durable replay guards remain unchanged in scope.

## Boundary

Affected paths:

- `backend/workbench/agent/plan_compiler.py`
- `backend/workbench/agent/planning_contracts.py`
- `backend/workbench/agent/compilation_store.py`
- `tests/test_v189_agent_compiler.py`
- `tests/test_v189_capability_manifest.py`
- this objective, work order, and handoff

Protected paths: `backend/workbench/contracts`, `backend/workbench/evidence`,
`frontend`, Workflow Truth files, and all other lanes.

## Verification

- `cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_agent_compiler.py ../tests/test_v189_capability_manifest.py -q`
- `.venv/bin/python -m compileall -q backend/workbench/agent`
- `git diff --check`

## Known gates

- Real supervisor-owned host compiler channel, OS identity binding, production
  resolver wiring, Agent/Notebook production cutover, provider, browser, full
  gate, release, merge, push, and tag remain `NOT VERIFIED`.
- No commit, merge, push, or tag is authorized by this line.

## Boundary
- Affected paths: `backend/workbench/agent/plan_compiler.py`, `backend/workbench/agent/planning_contracts.py`, `backend/workbench/agent/compilation_store.py`, `backend/workbench/agent/failure_contract.py`, `tests/test_v189_agent_compiler.py`, `tests/test_v189_capability_manifest.py`, `docs/superpowers/objectives/2026-08-16-v1.8.9-p0-agent-compiler-legacy-cutover-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-agent-compiler-legacy-cutover.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-p0-agent-compiler-legacy-cutover-handoff.md`
- Allowed paths: `backend/workbench/agent/plan_compiler.py`, `backend/workbench/agent/planning_contracts.py`, `backend/workbench/agent/compilation_store.py`, `backend/workbench/agent/failure_contract.py`, `tests/test_v189_agent_compiler.py`, `tests/test_v189_capability_manifest.py`, `docs/superpowers/objectives/2026-08-16-v1.8.9-p0-agent-compiler-legacy-cutover-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-agent-compiler-legacy-cutover.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-p0-agent-compiler-legacy-cutover-handoff.md`
- Protected paths: `backend/workbench/contracts`, `backend/workbench/evidence`, `frontend`
- Dependencies: `v1-8-9-p0-agent-compiler-remediation-5`, `v1-8-9-p0-legacy-compilation-authority-cutover`
- Tests: `cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_agent_compiler.py ../tests/test_v189_capability_manifest.py -q`, `.venv/bin/python -m compileall -q backend/workbench/agent`, `git diff --check`
- Known gates: `real supervisor-owned host compiler integration is NOT VERIFIED`, `production Agent/Notebook cutover, provider, browser, full gate, release and tags are NOT VERIFIED`, `no commit, merge, push or tag`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-9-p0-agent-compiler-remediation-4 (2026-08-16T13:45:00.000Z)

Completed formal devline v1-8-9-p0-agent-compiler-remediation-4; final_state=COMPLETED; failure_lesson_keys=compiler-proof-copy-must-fail-closed, compiler-remediation4-host-authority-and-fd-reservation, compiler-remediation4-red-tests-before-fix

### v1-8-9-p0-agent-compiler-remediation-3 (2026-08-16T12:20:00.000Z)

Completed formal devline v1-8-9-p0-agent-compiler-remediation-3; final_state=COMPLETED; failure_lesson_keys=compiler-bootstrap-proof, compiler-durable-reservation, compiler-public-durable-store, compiler-sealed-scope-authority, compiler-selection-admission, discovery-server-scope-binding, legacy-c0-issuer-dependency

### v1-8-9-p0-agent-compiler-remediation-2 (2026-08-16T11:08:02.000Z)

Completed formal devline v1-8-9-p0-agent-compiler-remediation-2; final_state=COMPLETED; failure_lesson_keys=agent-compiler-atomic-reservation, agent-compiler-effect-binding, agent-compiler-exact-connections, agent-compiler-natural-language-allowlist, agent-compiler-readonly-capabilities, agent-compiler-runtime-shadow, agent-compiler-server-scope-authority, formal-event-redaction-retry, formal-gate-enum-validation

### v1-8-9-p0-agent-compiler-remediation (2026-08-16T10:38:00.000Z)

Completed formal devline v1-8-9-p0-agent-compiler-remediation; final_state=COMPLETED; failure_lesson_keys=adversarial-authority-probes-before-green, discovery-budget-fails-closed, discovery-receipt-issuer-bound, exact-port-contract-before-green, registry-manifest-authority-before-compile

### v1-8-9-p0-agent-compiler-core (2026-08-16T09:55:00.000Z)

Completed formal devline v1-8-9-p0-agent-compiler-core; final_state=COMPLETED; failure_lesson_keys=protected-provider-denominator-boundary, quality-tool-not-verified, shadow-core-not-runtime-acceptance, tdd-red-before-implementation

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none
