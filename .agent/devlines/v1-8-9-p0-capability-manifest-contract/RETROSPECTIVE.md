# Retrospective — v1-8-9-p0-capability-manifest-contract

## Goal

# Workbench v1.8.9 P0 Capability Manifest Contract  ## Objective  Align the built-in Agent compiler manifest assertion with the published declaration contract. A typed \`compiler_receipt\` fact kind is a result/evidence declaration and must not be confused with an execution authority or client receipt.  ## Scope  - \`tests/test_v189_capability_manifest.py\`  ## Acceptance  - The manifest test rejects execution authority fields while permitting the   declared typed compiler evidence fact kind.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/6 (50.0%; 50.0 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: N/A (sample=0; unresolved=3)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T09:15:38.638Z `manifest_receipt_assertion_red`; cause_status: `known`; cause: The declaration-only provider assertion searched the full encoded manifest for receipt and rejected the published typed fact kind compiler_receipt.; resolution: `open`; lesson: Manifest tests must inspect typed declaration fields and reject authority fields without banning evidence fact-kind names.

## All errors

- #4 2026-08-21T09:15:38.881Z `formal_cli_wrong_import_root`; cause_status: `known`; cause: The first formal CLI invocation from the worktree root imported the linked v1.8.6 backend and lacked the current context-pack symbol.; resolution: `mitigated`; lesson: Run formal control commands with the current worktree backend first on PYTHONPATH when linked environments can shadow imports.

## All gaps

- #3 2026-08-21T09:15:38.758Z `managed_host_socket_probe_blocked`; cause_status: `external`; cause: The focused discovery probe child could not bind its Unix socket because the managed macOS host denied the operation with PermissionError.; resolution: `open`; lesson: Keep managed-host socket and containment failures separate from pure manifest declaration-contract evidence.

## All waste

- None recorded.

## Root causes and solutions

- `managed-host-socket-probe-gap`: occurrences=1; cause_status: `external`; root cause: The focused discovery probe child could not bind its Unix socket because the managed macOS host denied the operation with PermissionError.; solution: `open`
- `typed-evidence-is-not-execution-authority`: occurrences=1; cause_status: `known`; root cause: The declaration-only provider assertion searched the full encoded manifest for receipt and rejected the published typed fact kind compiler_receipt.; solution: `open`
- `worktree-pythonpath-before-formal-cli`: occurrences=1; cause_status: `known`; root cause: The first formal CLI invocation from the worktree root imported the linked v1.8.6 backend and lacked the current context-pack symbol.; solution: `mitigated`

## Added tests

- No test evidence recorded.

## New rules

- `managed-host-socket-probe-gap`: line experience occurrence(s)=1
- `typed-evidence-is-not-execution-authority`: line experience occurrence(s)=1
- `worktree-pythonpath-before-formal-cli`: line experience occurrence(s)=1

## Future guidance

- Keep managed-host socket and containment failures separate from pure manifest declaration-contract evidence.
- Manifest tests must inspect typed declaration fields and reject authority fields without banning evidence fact-kind names.
- Run formal control commands with the current worktree backend first on PYTHONPATH when linked environments can shadow imports.

## Event index

- #1: `b6d8e9fd-fbd3-42c0-a348-aad1ada19125` | 2026-08-21T09:08:07.789Z | STATE_CHANGE/line_started | incident=`46e904f4-8c42-41c4-87ba-06efb49c8edd` | lesson_key=`frozen-context-before-start` | event_sha256=`cc7609f38c819fdb69cc44fcf9f5223710df1fff17f059e3ad52bc434eb15f99`
- #2: `f189c2a1-7d64-4e2b-9c50-1a6b8d3e4f70` | 2026-08-21T09:15:38.638Z | FAILURE/manifest_receipt_assertion_red | incident=`c2a1f189-6d73-4b0e-9f52-8a4d1e7c3b60` | lesson_key=`typed-evidence-is-not-execution-authority` | event_sha256=`a4c948c223e87a16e117fc7f32bf98969652fdb6451e549719cd7092c2f66de6`
- #3: `a189e3c5-7b21-4d60-8f94-2c6a1e5b7d30` | 2026-08-21T09:15:38.758Z | GAP/managed_host_socket_probe_blocked | incident=`b3d2f1a0-8c74-4e59-9a61-5c2b7d0e4f83` | lesson_key=`managed-host-socket-probe-gap` | event_sha256=`1eed2bc980f0e8aaab183a4a485af8fe56e9498e51054315befd770d3496b622`
- #4: `e189b4c6-2a75-4f08-9d31-6c7e5b0a2f94` | 2026-08-21T09:15:38.881Z | ERROR/formal_cli_wrong_import_root | incident=`d4c3b2a1-9e87-4f60-8b52-7a1d5c3e9f04` | lesson_key=`worktree-pythonpath-before-formal-cli` | event_sha256=`9d9de65c9235b50e74193acfd28ab9531800149729bb43e10588d81104baf0f4`
- #5: `c189d5e7-3a86-4f10-9b42-7e1c5d0a8f63` | 2026-08-21T09:18:23.327Z | GATE/manifest_declaration_contract_green | incident=`e5d4c3b2-a190-4f87-9b63-2c7e1a5d8f04` | lesson_key=`scoped-contract-gate-separates-host-gap` | event_sha256=`8d547dfe7da7064a312a482df25769e02b7e6e8ecf12032b497517c4bcdae0af`
- #6: `d189e6f8-4b97-4a21-8c53-6f0d2e7b1a85` | 2026-08-21T09:18:58.618Z | STATE_CHANGE/line_completed | incident=`f6e5d4c3-b2a1-4098-7e63-5d2c1a0f8b74` | lesson_key=`close-only-at-scoped-verification-boundary` | event_sha256=`9505637352a5c704560baf7b036e951e06b7108c07e9e9c800076fc3faeb4f11`
