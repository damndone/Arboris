# Retrospective — v1-8-9-p0-legacy-proposal-binding-remediation

## Goal

# Workbench v1.8.9 P0 Legacy Agent Proposal-Binding Remediation Objective  Close the remaining legacy Agent confirmation proposal-binding bypass found by the independent code-quality review. A retained legacy confirmation handle must be server-bound to the exact proposal identity at proposal/compile/ confirmation creation time, and execution must accept only that persisted server-owned binding.  Required outcomes:  - \`ServerConfirmationReceiptV1\` persists and validates proposal id, revision,   fingerprint, semantic plan hash, actor, session, and project identity. - Proposal, compilation, and confirmation creation bind the complete identity   on the server; execution never accepts caller-supplied identity as authority. - A first claim whose proposal identity mismatches the retained confirmation   fails closed before compiler execution and does not create a binding. - The exact same proposal succeeds once its server binding is valid; replay,   cross-scope, serialization, and tamper cases fail closed before execution. - Compatibility response shapes remain separate from the security/correctness   gate. No Report/data/classification/survey or central unrelated paths change.  ## Boundary  - Affected paths: \`backend/workbench/http/agent_routes.py\`,   \`backend/workbench/agent/orchestrator.py\`,   \`backend/workbench/agent/proposals.py\`,   \`backend/workbench/agent/compiler.py\`,   \`tests/test_v189_legacy_route_authority.py\`,   \`tests/test_v189_legacy_proposal_binding.py\` - Allowed paths: same as affected paths - Protected paths: \`backend/workbench/http/runs_routes.py\`,   \`backend/workbench/report_view_model.py\`, \`frontend/src/report\`,   \`backend/workbench/engine/stages/estimation.py\`,   \`backend/workbench/providers\`, all Report/data/classification/survey paths,   and central unrelated Agent/workflow paths - Dependencies: \`v1-8-9-p0-legacy-resume-hardening\`,   \`v1-8-9-p0-agent-compiler-core\`, \`v1-8-9-contract-lock\` - Tests: focused legacy/resume/compiler/workflow suites, the new RED to GREEN   proposal-binding tests, \`PYTHONPATH=backend .venv/bin/python -m compileall   -q backend/workbench tests\`, \`git diff --check\`, formal verification - Known gates: browser/provider/full gate/release remain \`NOT VERIFIED\`;   commit is local only and push/PR/merge/tag remain approval-gated

## Final status

CONTEXT_RESCOPED

## Metrics

- Failure frequency: 2/6 (33.3%; 33.3 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=0 ms (sample=2; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #5 2026-08-19T19:55:00.000Z `legacy_proposal_binding_red`; cause_status: `known`; cause: The adversarial first-claim test initially completed proposal B with a confirmation-like receipt carrying proposal A because the route created legacy_proposal_bindings during execution and the receipt lacked proposal identity.; resolution: `resolved`; lesson: Bind proposal identity into the server confirmation receipt and validate it before any first-use claim or compiler execution.

## All errors

- #2 2026-08-19T19:45:00.000Z `rescope_command_surface`; cause_status: `known`; cause: The first rescope CLI invocation supplied protected-path flags that are not accepted by the rescope command surface.; resolution: `resolved`; lesson: Use the formal rescope command's exact supported flags and preserve protected-path declarations from the existing Context Pack.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `formal-rescope-command-surface`: occurrences=1; cause_status: `known`; root cause: The first rescope CLI invocation supplied protected-path flags that are not accepted by the rescope command surface.; solution: `resolved`
- `legacy-first-claim-receipt-identity`: occurrences=1; cause_status: `known`; root cause: The adversarial first-claim test initially completed proposal B with a confirmation-like receipt carrying proposal A because the route created legacy_proposal_bindings during execution and the receipt lacked proposal identity.; solution: `resolved`

## Added tests

- `tests/test_v189_legacy_route_authority.py::test_first_legacy_claim_uses_server_receipt_proposal_identity_before_execute`
- `tests/test_v189_legacy_route_authority.py;tests/test_v189_resume_authority.py;tests/test_v189_workflow_truth.py;tests/test_workflow_resume.py;tests/test_v189_agent_notebook_cutover.py;tests/test_v189_agent_notebook_runtime_bridge.py;tests/test_workflow_runtime.py;tests/contracts/test_v189_contract_lock.py`

## New rules

- `formal-rescope-command-surface`: line experience occurrence(s)=1
- `legacy-first-claim-receipt-identity`: line experience occurrence(s)=1

## Future guidance

- Bind proposal identity into the server confirmation receipt and validate it before any first-use claim or compiler execution.
- Use the formal rescope command's exact supported flags and preserve protected-path declarations from the existing Context Pack.

## Event index

- #1: `45bbc769-20ba-465b-a1ee-fb5fbe39deda` | 2026-08-19T23:49:48.546Z | STATE_CHANGE/line_started | incident=`09683ad7-1a4d-43f2-ab9b-347c2d438fad` | lesson_key=`frozen-context-before-start` | event_sha256=`5dcdf9ef760065365dd5e654b663986fdeedd30ab6a945e544678f46ec3a3499`
- #2: `b7a1c9e2-4d56-4f80-91ab-2c3e5d7f8a90` | 2026-08-19T19:45:00.000Z | ERROR/rescope_command_surface | incident=`c8b2d0f3-5e67-4a91-82bc-3d4f6e8a9012` | lesson_key=`formal-rescope-command-surface` | event_sha256=`409106acdfe057625be53af8c332c9886506519891a8f114c650ca6c6947bf24`
- #3: `8b506b01-346b-4205-a2b9-68bc7d4ce021` | 2026-08-19T23:53:58.719Z | STATE_CHANGE/context_rescope_required | incident=`77312e9e-1f95-4674-bc91-5d97d86a7f22` | lesson_key=`context-pack-rescope` | event_sha256=`576e95ef719e4e555ab2a52eb8d83d4bee218f8f27f989deee82f79748f41a50`
- #4: `eb14a77d-ffd6-4005-bbaf-193149595d83` | 2026-08-19T23:53:58.722Z | STATE_CHANGE/context_rescoped | incident=`a8c24226-61bc-416d-a632-ef8ca4895e40` | lesson_key=`context-pack-rescope` | event_sha256=`a759be8cc52f19c3abf1d1e38cdc29f1302e89ab113f4bd8ab4e9589afb2289b`
- #5: `d9e3f7a1-2b45-4c67-8d90-1e3f5a7b9c02` | 2026-08-19T19:55:00.000Z | FAILURE/legacy_proposal_binding_red | incident=`e0f4a8b2-3c56-4d78-9e01-2f4a6b8c0d13` | lesson_key=`legacy-first-claim-receipt-identity` | event_sha256=`fb9fb97744e69413ef447ffca5088277407804aa63e5bf2d2adc805ca07fd94f`
- #6: `f1a5c9e3-7b24-4d68-90ab-2c6e8f0a1d35` | 2026-08-19T20:10:00.000Z | GATE/legacy_proposal_binding_green | incident=`a2c6e0f4-8b35-4d79-91ab-3e5f7a9c0d24` | lesson_key=`legacy-proposal-binding-green-gate` | event_sha256=`56a7a0c3dcd54f3e29e718abe424599c31be4acdffdb8c2d22e91bd651721776`
