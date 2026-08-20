# Retrospective — v1-8-9-p0-legacy-resume-remediation-2

## Goal

# Workbench v1.8.9 P0 Legacy/Resume Remediation-2 Objective  Close the remaining P0 bypasses found after the prior legacy/resume rehardening line at exact baseline \`8c48813868d789266635990769d783f4603ab346\`. This remediation line owns the server-side proposal boundary, legacy route receipt gate, direct historical Agent service boundary, and regression probes.  Required outcomes:  - \`compile_for_proposal()\` and \`bind_proposal()\` cannot accept a caller-created   \`ProposalRevision\` or a synthetic \`proposal:compilation-record\` identity.   The only proposal binding input is a real \`ProposalStore\` plus the exact   server proposal id; the implementation rereads the persisted latest   revision, fingerprint, semantic plan hash, actor/session/project, and scope.   A missing, forged, stale, or cross-scope server proposal fails closed. - The legacy route validates the complete server-owned proposal and typed   confirmation receipt, including a required semantic-plan hash, actor,   session, project, scope, canonical serialization/digest, tamper state, and   replay state before \`_cutover_authority\`, compiler record lookup/record, or   execution. A first-claim mismatch leaves authority and claim stores   untouched; the actual spy records \`authority/record/execute == []\`. - Direct \`WorkbenchOrchestrator.confirm_proposal()\` and historical Agent   operation paths cannot create a pending operation outside the   \`AgentNotebookCompilerV1\` server-owned boundary. They either use that   boundary or return a typed fail-closed error before proposal/operation   writes; a direct-service negative probe proves this without HTTP. - Existing \`validate_resumed_step_state()\` model-branch validation remains   active, including terminal model steps with no downstream branch consumer,   and the adversarial probe proves callback/persistence is not reached. - Focused tests, compileall, diff checks, and formal verification use only   current remediation-2 evidence. Prior line metrics, including its 341   passed claim, are historical evidence and are not reused as this line's   result.  ## Boundary  - Affected paths: \`backend/workbench/http/agent_routes.py\`,   \`backend/workbench/agent/orchestrator.py\`,   \`backend/workbench/agent/workflow_runtime.py\`,   \`tests/test_v189_agent_notebook_cutover.py\`,   \`tests/test_v189_legacy_route_authority.py\`,   \`tests/test_v189_resume_authority.py\`,   \`tests/test_v189_legacy_resume_remediation2.py\`,   \`docs/superpowers/objectives/2026-08-19-v1.8.9-p0-legacy-resume-remediation-2-objective.md\`,   \`docs/superpowers/plans/2026-08-19-v1.8.9-p0-legacy-resume-remediation-2.md\` - Allowed paths: exactly the affected paths above - Protected paths: \`backend/workbench/http/runs_routes.py\`,   \`backend/workbench/report_view_model.py\`, \`frontend/src/report\`,   \`backend/workbench/engine/stages/estimation.py\`,   \`backend/workbench/providers\`, all Report/data/classification/survey paths,   root-level files, and all prior \`.agent/devlines/*\` records - Baseline: \`8c48813868d789266635990769d783f4603ab346\` - Dependencies: \`v1-8-9-p0-legacy-resume-authority-rehardening\`,   \`v1-8-9-p0-legacy-proposal-binding-remediation\`,   \`v1-8-9-p0-legacy-resume-hardening\`,   \`v1-8-9-p0-agent-compiler-core\`, \`v1-8-9-contract-lock\` - Tests: RED probes followed by GREEN focused legacy route/proposal/compiler,   resume/workflow, and direct Agent-notebook service suites; isolated   compileall; \`git diff --check\`; formal verify; formal retrospective - Known gates: browser acceptance, provider/external runtime, full repository   gate, release, merge, and tag remain \`NOT VERIFIED\`; no dependency install,   push, PR, or release operation

## Final status

COMPLETED

## Metrics

- Failure frequency: 4/8 (50.0%; 50.0 per 100 events)
- Repeat rate: 0/4 (0.0%)
- Recurrence rate: 0/4 (0.0%)
- MTTR: median=0 ms (sample=3; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-19T23:15:00.000Z `tdd_red_legacy_resume_remediation_2`; cause_status: `known`; cause: The baseline compiler trusted caller-created ProposalRevision values and a synthetic compile binding, the legacy route allowed an omitted semantic hash to reach authority, and direct WorkbenchOrchestrator confirmation wrote through the historical stores.; resolution: `accepted`; lesson: Keep actual authority, semantic preflight ordering, and direct-service bypass probes red before implementing the smallest server-owned fix.

## All errors

- #3 2026-08-20T01:25:33.000Z `compileall_temp_cleanup`; cause_status: `known`; cause: The first isolated compileall cleanup used depth-first empty-directory deletion that removed its temporary root before the explicit cleanup checks, producing cleanup-path errors despite no compile failure.; resolution: `resolved`; lesson: Use mindepth when deleting empty directories under an explicitly retained temporary root.
- #4 2026-08-20T01:26:03.000Z `persisted_probe_store_layout`; cause_status: `known`; cause: The first persisted fingerprint-tamper probe addressed the server-proposals root instead of the ProposalStore proposals directory, so the probe failed before reaching its integrity assertion.; resolution: `resolved`; lesson: Read the persisted store layout before targeting tamper probes and record the corrected command evidence.
- #6 2026-08-20T01:27:33.000Z `formal_gate_event_validation`; cause_status: `known`; cause: The first closeout GATE event used an unsupported preventability value and was rejected by the formal CLI before it could mutate the event stream.; resolution: `resolved`; lesson: Validate event vocabulary against the formal contract before appending the closeout gate.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `formal-gate-event-vocabulary`: occurrences=1; cause_status: `known`; root cause: The first closeout GATE event used an unsupported preventability value and was rejected by the formal CLI before it could mutate the event stream.; solution: `resolved`
- `isolated-compileall-cleanup-root`: occurrences=1; cause_status: `known`; root cause: The first isolated compileall cleanup used depth-first empty-directory deletion that removed its temporary root before the explicit cleanup checks, producing cleanup-path errors despite no compile failure.; solution: `resolved`
- `legacy-resume-remediation2-red-before-green`: occurrences=1; cause_status: `known`; root cause: The baseline compiler trusted caller-created ProposalRevision values and a synthetic compile binding, the legacy route allowed an omitted semantic hash to reach authority, and direct WorkbenchOrchestrator confirmation wrote through the historical stores.; solution: `accepted`
- `persisted-probe-store-layout`: occurrences=1; cause_status: `known`; root cause: The first persisted fingerprint-tamper probe addressed the server-proposals root instead of the ProposalStore proposals directory, so the probe failed before reaching its integrity assertion.; solution: `resolved`

## Added tests

- `tests/test_v189_legacy_resume_remediation2.py; corrected isolated compileall later reported compileall_status=0 remaining=0`
- `tests/test_v189_legacy_resume_remediation2.py; corrected probe targets server-proposals/proposals and the focused file reports 14 passed`
- `tests/test_v189_legacy_resume_remediation2.py; focused legacy route/proposal/compiler/resume/workflow/agent-notebook command: 355 passed, 53 warnings; isolated compileall: 0; git diff --check: 0`
- `tests/test_v189_legacy_resume_remediation2.py; focused legacy/resume suite result: 355 passed, 53 warnings`
- `tests/test_v189_legacy_resume_remediation2.py; focused suites: 355 passed, 53 warnings; compileall_status=0 remaining=0; git diff --check passed; formal verify passed`
- `tests/test_v189_legacy_resume_remediation2.py; formal CLI rejected and then accepted the corrected GATE event`
- `tests/test_v189_legacy_resume_remediation2.py; pytest result: 7 failed`

## New rules

- `formal-gate-event-vocabulary`: line experience occurrence(s)=1
- `isolated-compileall-cleanup-root`: line experience occurrence(s)=1
- `legacy-resume-remediation2-red-before-green`: line experience occurrence(s)=1
- `persisted-probe-store-layout`: line experience occurrence(s)=1

## Future guidance

- Keep actual authority, semantic preflight ordering, and direct-service bypass probes red before implementing the smallest server-owned fix.
- Keep the server-owned proposal and receipt checks before every authority or mutation seam, and prove the order with spies.
- Read the persisted store layout before targeting tamper probes and record the corrected command evidence.
- Use mindepth when deleting empty directories under an explicitly retained temporary root.
- Validate event vocabulary against the formal contract before appending the closeout gate.

## Event index

- #1: `6c705a99-a43a-4d3a-ae05-8cc4649f649c` | 2026-08-20T00:59:11.657Z | STATE_CHANGE/line_started | incident=`689c4929-5133-4dd2-8910-78976ffaf239` | lesson_key=`frozen-context-before-start` | event_sha256=`dfe949db1c941bf4467eaec1c8228d64ab1f446fe8453792a7718f033367788b`
- #2: `2f4d6b8a-1c3e-4f50-9a72-b4d6e8f01234` | 2026-08-19T23:15:00.000Z | FAILURE/tdd_red_legacy_resume_remediation_2 | incident=`6a8c0e2f-4b6d-4f91-8a3c-1e5d7b9f0246` | lesson_key=`legacy-resume-remediation2-red-before-green` | event_sha256=`123931a925005e2cb8c2b1c7666ed963eebb36802aa340b5fbe1b84b8e56b2ce`
- #3: `1a5c7e9f-2b4d-4f68-9a10-c3e5d7b9f024` | 2026-08-20T01:25:33.000Z | ERROR/compileall_temp_cleanup | incident=`2b6d8fa1-3c5e-4a79-b012-d4f6e8a0c235` | lesson_key=`isolated-compileall-cleanup-root` | event_sha256=`2fd0acc266e3f00f5f38a7546015605a3f8dd65772f69af5bc4dfa9cea401509`
- #4: `3c7e9a1b-4d6f-4a80-b123-e5f7a9c1d246` | 2026-08-20T01:26:03.000Z | ERROR/persisted_probe_store_layout | incident=`4d8fa2b3-5e7c-4a91-c234-f6a8b0d2e357` | lesson_key=`persisted-probe-store-layout` | event_sha256=`1df553bdf607853921bbb5525ffbce247008adef221893f607189445c1476090`
- #5: `5e9b1c3d-6f8a-4b02-c345-d7f9a1b3e468` | 2026-08-20T01:26:17.000Z | REVIEW/preflight_authority_order | incident=`6fa2b3c4-7d8e-4a13-b456-e8f0a2c4d579` | lesson_key=`preflight-authority-order` | event_sha256=`a8a8f8a4286ea2c8c96c8cb8a6f04d59140c82cb8595f2271efa912725fe0cdb`
- #6: `9c2e4f6a-0b1d-4e73-f5a7-b9c1d3e5f802` | 2026-08-20T01:27:33.000Z | ERROR/formal_gate_event_validation | incident=`0d3f5a7b-1c2e-4e84-f6a8-b0c2d4e6f913` | lesson_key=`formal-gate-event-vocabulary` | event_sha256=`e83d9d1efccccef4519492298164b95b59e74fce72559bd2f0d872d370b2e889`
- #7: `7a0c2e4f-8b1d-4c63-d5e7-f9a1b3c5d680` | 2026-08-20T01:27:01.000Z | GATE/remediation2_current_verification | incident=`8b1d3f5a-9c2e-4d74-e6f8-a0b2c4d6e791` | lesson_key=`remediation2-current-verification` | event_sha256=`e70934dd5a15aea0fadd3f467860eefe69a14684ee9d436c93ceca43b8bb8247`
- #8: `b3e5f7a9-1c2d-4e68-b0a2-c4d6e8f0a135` | 2026-08-20T01:28:03.000Z | STATE_CHANGE/remediation2_completed | incident=`c4f6a8b0-2d3e-4f79-b1c3-d5e7f9a1b246` | lesson_key=`remediation2-closeout-current-evidence` | event_sha256=`10384f9b7b448cee7026d75b2d65252a567ebd63149984da24a403ed097f3bac`
