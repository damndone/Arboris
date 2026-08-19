# Retrospective — v1-8-9-p0-legacy-compilation-authority-cutover

## Goal

# v1.8.9 P0 Legacy Compilation Authority Cutover Objective  Retire the publicly constructible C0 \`ServerCompilationRecordIssuerV1\` as a security authority. The independent audit proved that a caller can create the issuer, register a typed draft, compile it, issue a server reference and have the record store resolve it without the new PlanCompiler, host authority or supervisor. This is an open P0 bypass.  Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749 Formal line: v1-8-9-p0-legacy-compilation-authority-cutover Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-legacy-cutover  Required outcomes:  - public legacy issuer construction, registration, compile, record and issue   paths fail closed without an authority receipt from the trusted host/compiler   boundary; caller-supplied project/session/principal metadata is not authority; - no public re-export or compatibility alias can silently restore the legacy   signing path; old historical records remain readable as untrusted data but   cannot be upgraded into a server reference; - the new host-bound PlanCompiler integration seam is explicit and typed; no   module-private key, environment variable, JSON, pickle, object.__new__ or   process-local token is treated as the trust root; - focused C0 compatibility tests are migrated to a host-backed test harness or   explicitly marked as non-authoritative fixtures, with negative probes for   caller-created issuer, cross-scope, serialization and fork reuse; - valid host-backed compilation/replay remains possible through the explicit   integration seam; production supervisor wiring remains a separate gate.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/7 (28.6%; 28.6 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-16T14:00:00.000Z `tdd_red_legacy_authority`; cause_status: `known`; cause: The new independent negative probes correctly observed the open C0 legacy issuer bypass before production changes.; resolution: `resolved`; lesson: Write and run independent negative probes before closing a public authority bypass.

## All errors

- None recorded.

## All gaps

- #3 2026-08-16T14:10:00.000Z `dependency_not_in_c0_baseline`; cause_status: `external`; cause: The frozen C0 worktree does not contain the Compiler-5 plan_compiler.py, planning_contracts.py or compilation_store.py files; those remain a separate dependency worktree.; resolution: `accepted`; lesson: Keep a cutover line bounded to its frozen baseline and carry dependency worktrees forward as explicit integration gates.

## All waste

- None recorded.

## Root causes and solutions

- `legacy-authority-red-before-implementation`: occurrences=1; cause_status: `known`; root cause: The new independent negative probes correctly observed the open C0 legacy issuer bypass before production changes.; solution: `resolved`
- `legacy-cutover-keeps-host-dependency-explicit`: occurrences=1; cause_status: `external`; root cause: The frozen C0 worktree does not contain the Compiler-5 plan_compiler.py, planning_contracts.py or compilation_store.py files; those remain a separate dependency worktree.; solution: `accepted`

## Added tests

- No test evidence recorded.

## New rules

- `legacy-authority-red-before-implementation`: line experience occurrence(s)=1
- `legacy-cutover-keeps-host-dependency-explicit`: line experience occurrence(s)=1

## Future guidance

- A compatibility symbol may remain only as a typed rejection guard; it must not retain a hidden local authority implementation.
- Keep a cutover line bounded to its frozen baseline and carry dependency worktrees forward as explicit integration gates.
- Retiring a local authority must be integrated with every production caller before claiming the compile path is available; compatibility re-exports must be removed or remain typed rejection-only.
- Write and run independent negative probes before closing a public authority bypass.

## Event index

- #1: `a5ad5ef1-95a6-4e4c-8543-d2e5a4559eec` | 2026-08-16T13:29:55.965Z | STATE_CHANGE/line_started | incident=`bce315b1-8773-400d-b2f4-e81cf7fd5511` | lesson_key=`frozen-context-before-start` | event_sha256=`078e4d7699b17bf623d1c662e18e874ed388bc44e4d3fc301d3b1a065a11a49c`
- #2: `6c36dc66-9dbf-4e9b-943d-9cf98fd8a5d3` | 2026-08-16T14:00:00.000Z | FAILURE/tdd_red_legacy_authority | incident=`e6debc65-bc2a-4af5-909c-4e6bf9dd69e5` | lesson_key=`legacy-authority-red-before-implementation` | event_sha256=`6ebee8485aea359458eac10f9b8ad21f12557b2f0c3975e038a49ec1b782cc84`
- #3: `d207ac78-0e36-47d7-82b4-a4bd299983e2` | 2026-08-16T14:10:00.000Z | GAP/dependency_not_in_c0_baseline | incident=`1425414d-1dc8-4a6d-87af-c832521f65a9` | lesson_key=`legacy-cutover-keeps-host-dependency-explicit` | event_sha256=`94cddbac15ccef383452067edf3643ff3fe3d808ab97277750190a816511a693`
- #4: `6b7fb2d6-2252-403b-9069-6a4f4fc154f2` | 2026-08-16T14:20:00.000Z | GATE/legacy_cutover_focused_gate | incident=`5ed07768-dfca-49ad-9854-64e4df0a104d` | lesson_key=`legacy-cutover-focused-gate` | event_sha256=`16a64d73e0d06d1f4a21a26e4c36c5124bac61635783bed8e867837ff0071b54`
- #5: `1a9ec890-7aac-4d27-8d66-5445dd7349c6` | 2026-08-16T14:25:00.000Z | REVIEW/legacy_authority_boundary_review | incident=`f14a23bc-3b97-44fb-90bc-1ce70ed67713` | lesson_key=`retired-issuer-is-typed-rejection-only` | event_sha256=`1f788544cec463034513920498f279227ac7b6a5301b043a06fd6bd995ec9367`
- #6: `8d132ed9-a7b6-4f99-93bb-d4f12231d2f4` | 2026-08-16T14:30:00.000Z | STATE_CHANGE/legacy_cutover_completed | incident=`c55d2b19-cd7c-458f-bfdd-21e2cc7435cd` | lesson_key=`close-legacy-cutover-at-package-boundary` | event_sha256=`33c364ecd7b86046a25b875eaf31a7030e2e7aaeb936b235e4a04a04d677dc61`
- #7: `20ea78a8-475e-4c0f-a9dd-941edc7ad7cb` | 2026-08-16T13:55:05.000Z | REVIEW/compiler5_legacy_cutover_integration_blocker | incident=`c6271845-a31d-47a4-a059-3479294ec84b` | lesson_key=`compiler-legacy-cutover-integration` | event_sha256=`44545c0f8d4147371108ace3f5979927bec4153ef7965fca80ed573dd48ab184`
