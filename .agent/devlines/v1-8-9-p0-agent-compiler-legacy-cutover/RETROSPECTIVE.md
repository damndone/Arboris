# Retrospective — v1-8-9-p0-agent-compiler-legacy-cutover

## Goal

# Workbench v1.8.9 — Agent Compiler C0 Legacy Authority Cutover  ## Objective  Migrate the Agent Compiler's current production callers away from the retired \`ServerCompilationRecordIssuerV1\`. \`PlanCompiler\` and the agent-local planning facade must not construct, invoke, or re-export that issuer. Compilation must either use an explicitly injected host compiler authority port or fail closed through a stable typed integration-required failure. A test-only adapter may exercise the existing local fixtures, but it must not become a production authority path.  This line covers only the Agent Compiler downstream callers. It does not modify the Workflow Truth, Evidence Core, frontend, contract-lock files, or the real deployment host implementation.  Baseline: Contract Lock C0 \`c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749\` Dependency: \`v1-8-9-p0-agent-compiler-remediation-5\`; C0 legacy issuer cutover is an upstream integration dependency.  ## Required outcomes  - \`PlanCompiler\` has no live import, construction, or call to   \`ServerCompilationRecordIssuerV1\`. - \`planning_contracts\` does not re-export the retired issuer and exposes only   the host compiler port plus typed rejection seam needed by downstream code. - No caller-provided local object, store, or test fixture can silently become a   production compiler authority. - Host-backed compilation is represented by a typed port result and is checked   before it enters the replay store; malformed or unavailable host results fail   closed. - Existing compiler validation, scope binding, selection, effect/risk/port   checks, and durable replay guards remain unchanged in scope.  ## Boundary  Affected paths:  - \`backend/workbench/agent/plan_compiler.py\` - \`backend/workbench/agent/planning_contracts.py\` - \`backend/workbench/agent/compilation_store.py\` - \`tests/test_v189_agent_compiler.py\` - \`tests/test_v189_capability_manifest.py\` - this objective, work order, and handoff  Protected paths: \`backend/workbench/contracts\`, \`backend/workbench/evidence\`, \`frontend\`, Workflow Truth files, and all other lanes.  ## Verification  - \`cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_agent_compiler.py ../tests/test_v189_capability_manifest.py -q\` - \`.venv/bin/python -m compileall -q backend/workbench/agent\` - \`git diff --check\`  ## Known gates  - Real supervisor-owned host compiler channel, OS identity binding, production   resolver wiring, Agent/Notebook production cutover, provider, browser, full   gate, release, merge, push, and tag remain \`NOT VERIFIED\`. - No commit, merge, push, or tag is authorized by this line.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/10 (30.0%; 30.0 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: median=0 ms (sample=3; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #4 2026-08-16T15:12:00.000Z `legacy_issuer_downstream_red`; cause_status: `known`; cause: PlanCompiler still constructed the retired issuer and planning_contracts still exported its symbol before the cutover.; resolution: `resolved`; lesson: Write source-level and runtime boundary tests before migrating legacy authority callers.
- #5 2026-08-16T15:13:00.000Z `sandbox_socket_access`; cause_status: `external`; cause: The default sandbox denied the real pathname Unix socket used by the compiler authority fixture.; resolution: `resolved`; lesson: Use the smallest controlled OS access for real endpoint tests and keep the environment limitation separate from product evidence.
- #9 2026-08-16T15:24:46.000Z `host_result_snapshot_binding_gap`; cause_status: `known`; cause: A host compiler could return a record with a valid digest and identity while changing record policy or snapshot fields that were not compared with the compiled workflow.; resolution: `resolved`; lesson: Validate every duplicated identity and snapshot field across a host result before durable replay admission; valid shape and digest are not sufficient binding.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `compiler-os-fixture-needs-controlled-access`: occurrences=1; cause_status: `external`; root cause: The default sandbox denied the real pathname Unix socket used by the compiler authority fixture.; solution: `resolved`
- `host-result-cross-object-binding`: occurrences=1; cause_status: `known`; root cause: A host compiler could return a record with a valid digest and identity while changing record policy or snapshot fields that were not compared with the compiled workflow.; solution: `resolved`
- `legacy-issuer-cutover-red-first`: occurrences=1; cause_status: `known`; root cause: PlanCompiler still constructed the retired issuer and planning_contracts still exported its symbol before the cutover.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `compiler-os-fixture-needs-controlled-access`: line experience occurrence(s)=1
- `host-result-cross-object-binding`: line experience occurrence(s)=1
- `legacy-issuer-cutover-red-first`: line experience occurrence(s)=1

## Future guidance

- Keep the compiler caller cutover separate from real host deployment and verify malformed host results before replay admission.
- Use the smallest controlled OS access for real endpoint tests and keep the environment limitation separate from product evidence.
- Validate every duplicated identity and snapshot field across a host result before durable replay admission; valid shape and digest are not sufficient binding.
- Write source-level and runtime boundary tests before migrating legacy authority callers.

## Event index

- #1: `743d9316-e42a-4949-979d-de6398bb4523` | 2026-08-16T15:06:09.136Z | STATE_CHANGE/line_started | incident=`4fb377bd-1ce0-46ae-a51a-5e767921cf6f` | lesson_key=`frozen-context-before-start` | event_sha256=`998d7c02ab82df330c28ed759aa0a0fe887905e3c7dbd88af9bb6b1207f222ca`
- #2: `eb59ccb9-2c12-461f-9363-6208a95103fc` | 2026-08-16T15:08:25.270Z | STATE_CHANGE/context_rescope_required | incident=`e5c95e7b-61b6-4429-b4b2-db4783d37016` | lesson_key=`context-pack-rescope` | event_sha256=`5feddf13536913e0f6cdf971124a3318f51f44e14acf32c4cdb3832f387f856c`
- #3: `dd316ace-72d1-464b-b11f-1841d876a318` | 2026-08-16T15:08:25.274Z | STATE_CHANGE/context_rescoped | incident=`5c4a07ec-08ed-458b-8d05-e85f1ae0141d` | lesson_key=`context-pack-rescope` | event_sha256=`792f0c4e007742b76ef4c142a8acb798619771693bf96d895713c39a463763c4`
- #4: `0b4e8b35-1a58-4c5e-8a62-4a7e2e730001` | 2026-08-16T15:12:00.000Z | FAILURE/legacy_issuer_downstream_red | incident=`0b4e8b35-1a58-4c5e-8a62-4a7e2e730011` | lesson_key=`legacy-issuer-cutover-red-first` | event_sha256=`2bcac27668f2d94753c620dee67eef130d2728517794d40a52cd605bab5b9070`
- #5: `0b4e8b35-1a58-4c5e-8a62-4a7e2e730002` | 2026-08-16T15:13:00.000Z | FAILURE/sandbox_socket_access | incident=`0b4e8b35-1a58-4c5e-8a62-4a7e2e730012` | lesson_key=`compiler-os-fixture-needs-controlled-access` | event_sha256=`77dc484f6bb0acf50d53ef27f4f5fba9e5ac23cee2f865973d336bb4404bdeaf`
- #6: `0b4e8b35-1a58-4c5e-8a62-4a7e2e730003` | 2026-08-16T15:16:00.000Z | REVIEW/legacy_cutover_self_review | incident=`0b4e8b35-1a58-4c5e-8a62-4a7e2e730013` | lesson_key=`compiler-cutover-review-before-gate` | event_sha256=`8eeb7ebb2be225cc97f236e4d5bf0798015f14850d328c2729501315145215b7`
- #7: `0b4e8b35-1a58-4c5e-8a62-4a7e2e730004` | 2026-08-16T15:17:00.000Z | GATE/legacy_cutover_focused_gate | incident=`0b4e8b35-1a58-4c5e-8a62-4a7e2e730014` | lesson_key=`compiler-package-gate-separate-from-host` | event_sha256=`f5d61e7e7e31c573bba2a5e84a8da58c81e5fa8ca500a65ee56c21b1f0bcc778`
- #8: `0b4e8b35-1a58-4c5e-8a62-4a7e2e730005` | 2026-08-16T15:18:00.000Z | STATE_CHANGE/package_local_completed | incident=`0b4e8b35-1a58-4c5e-8a62-4a7e2e730015` | lesson_key=`compiler-cutover-scoped-closeout` | event_sha256=`9aa74f44347a7a9de3bc6275cb6604d50c188c3b452ace41511897141d8a2da4`
- #9: `6e4f3a2b-1c0d-4e5f-6a7b-890123456789` | 2026-08-16T15:24:46.000Z | FAILURE/host_result_snapshot_binding_gap | incident=`3b2a1c0d-9e8f-4a7b-6c5d-4321098765fe` | lesson_key=`host-result-cross-object-binding` | event_sha256=`bcbd890e3ee3a25979ba333055ee1a0f200230b25c89ab6d8a54da373c879a38`
- #10: `7f5e3d1c-9b8a-4c6d-2e1f-34567890abcd` | 2026-08-16T15:26:30.000Z | GATE/host_result_binding_hardening_gate | incident=`4d3c2b1a-0f9e-4d8c-7b6a-5432109876fe` | lesson_key=`rerun-gate-after-validation-hardening` | event_sha256=`4c0eb57f0d6748e54a6763b22f9e60fbff9e455fb42ad6e8ded50212214dec37`
