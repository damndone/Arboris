# Retrospective — v1-8-9-p0-legacy-resume-remediation-7

## Goal

# Workbench v1.8.9 P0 Legacy/Resume Remediation-7 Objective  ## Objective  Close the P0 authority bypass found at baseline \`4764a97b2093940417eeb9303d06aacc086ff82c\`: caller-created \`ProposalStoreCapabilityIssuerV1\` objects must not be able to self-register mutation admission or service-entry admission and then mint a proposal-store capability that reaches \`WorkbenchOrchestrator.decline_proposal\` side effects.  ## Required outcomes  - Make issuer and service admission server-owned opaque authority. A caller may   consume only an already issued, non-forgeable service-entry handle; it cannot   register or upgrade an issuer. - Bind every issuer and capability to the existing registry, server secret,   owner identity, nonce, process generation, PID, and exact store-root identity   boundaries. Copying, serialization, reconstruction, and cross-process use   must fail closed. - Keep the formal compiler, route, and workflow proposal paths valid. - Add adversarial TDD regressions for caller-created issuer plus self-registered   service handle, and imported/default route issuer directly registered then   minted. Both must reject before proposal, repository, or event side effects. - Run focused legacy/resume/route/compiler/workflow suites, the adversarial   suite, compileall, and diff-check. - Record the historical \`tests/test_agent_proposal_operations.py\` 19 direct-   service failures as a known GAP; do not weaken the authority boundary.  ## Boundary  Affected paths:  - \`backend/workbench/agent/proposals.py\` - \`backend/workbench/agent/orchestrator.py\` - \`tests/test_v189_legacy_resume_remediation7.py\` - \`docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-7-objective.md\` - \`docs/superpowers/plans/2026-08-20-v1.8.9-p0-legacy-resume-remediation-7.md\` - \`docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-resume-remediation-7-handoff.md\`  Allowed paths are exactly the affected paths above. Protected paths include the root checkout, all other worktrees, all predecessor \`.agent/devlines/*\` records, Report/data/classification/survey/provider paths, unrelated HTTP routes, and predecessor remediation source/test files unless a regression proves a narrowly necessary compatibility edit.  Baseline: \`4764a97b2093940417eeb9303d06aacc086ff82c\`.  Dependencies: legacy/resume remediation-6 and its predecessor authority hardening lines, Agent compiler cutover, route authority, workflow truth, and contract-lock evidence. Historical closeout counts are inputs only, not this line's evidence.  ## Tests and gates  - RED then GREEN: \`tests/test_v189_legacy_resume_remediation7.py\`. - Focused legacy/resume/route/compiler/workflow suites and the historical   direct-service suite, with its 19 failures recorded as a known GAP if still   present. - \`PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests\`. - \`git diff --check\`. - Formal line verify, final GATE, retrospective, and exact HEAD/digest handoff.  Known external gates remain outside this line: browser acceptance, external provider runtime, host restart, true multi-worker deployment, full repository gate, integration/release/merge/tag. They remain \`NOT VERIFIED\` unless directly run and evidenced here. No dependency installation, root write, other-worktree write, push, merge, tag, or release operation is authorized.

## Final status

COMPLETED

## Metrics

- Failure frequency: 4/9 (44.4%; 44.4 per 100 events)
- Repeat rate: 0/4 (0.0%)
- Recurrence rate: 0/4 (0.0%)
- MTTR: N/A (sample=0; unresolved=4)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T05:00:00.000Z `remediation7_red_self_registered_service_admission`; cause_status: `known`; cause: The baseline issuer constructor registers caller-created issuers and its internal mutation/service admission methods can be called directly, so both a caller-created issuer and the imported default route issuer can self-register and mint a capability.; resolution: `open`; lesson: Keep both self-registration adversarial probes red until mutation and service admission are issued only by server-owned authority.

## All errors

- None recorded.

## All gaps

- #3 2026-08-20T05:10:00.000Z `historical_direct_service_19_failures`; cause_status: `known`; cause: The historical tests/test_agent_proposal_operations.py suite still constructs WorkbenchOrchestrator without a server-owned proposal capability and expects the removed direct-service mutation/response contract.; resolution: `open`; lesson: Keep the server-owned mutation boundary strict and classify stale direct-service fixtures as a known GAP instead of restoring the bypass.
- #4 2026-08-20T05:11:00.000Z `inherited_workflow_seam_scope_gap`; cause_status: `known`; cause: The inherited tests/test_workflow_seam.py fixtures omit active_head_run_id, so compile_workflow refuses them at the pre-existing WORKFLOW_SCOPE_MISSING boundary before the seam assertions run.; resolution: `open`; lesson: Keep the existing workflow admission scope contract strict and classify inherited fixtures that omit active_head_run_id separately from this authority fix.
- #5 2026-08-20T05:12:00.000Z `inherited_workflow_seam_scope_gap_exact_count`; cause_status: `known`; cause: The full inherited tests/test_workflow_seam.py run has fixtures that omit active_head_run_id, so compile_workflow rejects them at the pre-existing WORKFLOW_SCOPE_MISSING boundary before seam assertions execute.; resolution: `open`; lesson: Report the complete inherited fixture count separately and do not weaken the existing workflow scope admission contract.

## All waste

- None recorded.

## Root causes and solutions

- `historical-direct-service-19-failures`: occurrences=1; cause_status: `known`; root cause: The historical tests/test_agent_proposal_operations.py suite still constructs WorkbenchOrchestrator without a server-owned proposal capability and expects the removed direct-service mutation/response contract.; solution: `open`
- `inherited-workflow-seam-scope-gap`: occurrences=1; cause_status: `known`; root cause: The inherited tests/test_workflow_seam.py fixtures omit active_head_run_id, so compile_workflow refuses them at the pre-existing WORKFLOW_SCOPE_MISSING boundary before the seam assertions run.; solution: `open`
- `inherited-workflow-seam-scope-gap-exact-count`: occurrences=1; cause_status: `known`; root cause: The full inherited tests/test_workflow_seam.py run has fixtures that omit active_head_run_id, so compile_workflow rejects them at the pre-existing WORKFLOW_SCOPE_MISSING boundary before seam assertions execute.; solution: `open`
- `remediation7-red-self-registered-service-admission`: occurrences=1; cause_status: `known`; root cause: The baseline issuer constructor registers caller-created issuers and its internal mutation/service admission methods can be called directly, so both a caller-created issuer and the imported default route issuer can self-register and mint a capability.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `historical-direct-service-19-failures`: line experience occurrence(s)=1
- `inherited-workflow-seam-scope-gap`: line experience occurrence(s)=1
- `inherited-workflow-seam-scope-gap-exact-count`: line experience occurrence(s)=1
- `remediation7-red-self-registered-service-admission`: line experience occurrence(s)=1

## Future guidance

- Handoffs must distinguish current security evidence, known fixture gaps, and NOT VERIFIED release boundaries.
- Keep both self-registration adversarial probes red until mutation and service admission are issued only by server-owned authority.
- Keep the existing workflow admission scope contract strict and classify inherited fixtures that omit active_head_run_id separately from this authority fix.
- Keep the server-owned mutation boundary strict and classify stale direct-service fixtures as a known GAP instead of restoring the bypass.
- Report the complete inherited fixture count separately and do not weaken the existing workflow scope admission contract.

## Event index

- #1: `ff2f8b70-9a21-48ca-9bb8-95232956243b` | 2026-08-20T05:12:39.419Z | STATE_CHANGE/line_started | incident=`c6416487-8de3-41ff-84db-5cd579823ebf` | lesson_key=`frozen-context-before-start` | event_sha256=`b5b5de731bd5db3a87860a29dde35560ee6e1e6c0f2cf876cefea02e7d20a12d`
- #2: `e1b2c3d4-5f67-489a-bcde-f0123456789a` | 2026-08-20T05:00:00.000Z | FAILURE/remediation7_red_self_registered_service_admission | incident=`f0a1b2c3-d4e5-4678-9abc-def012345678` | lesson_key=`remediation7-red-self-registered-service-admission` | event_sha256=`49cd699dd540d7cfe6fcca78435fc269f598b96137045408929c8ab8bc51f7d9`
- #3: `f2c3d4e5-6789-4abc-def0-1234567890ab` | 2026-08-20T05:10:00.000Z | GAP/historical_direct_service_19_failures | incident=`a2b3c4d5-e6f7-4890-ab12-cd3456789012` | lesson_key=`historical-direct-service-19-failures` | event_sha256=`e0b87917a69847928fc1d52e4be3a07c2776ae05c310c8d77769eb4470426ca5`
- #4: `a3d4e5f6-7890-4abc-def1-234567890abc` | 2026-08-20T05:11:00.000Z | GAP/inherited_workflow_seam_scope_gap | incident=`b3c4d5e6-f789-4abc-def1-234567890abc` | lesson_key=`inherited-workflow-seam-scope-gap` | event_sha256=`0857c1304f3d6bdf77669721d796db92e9a1af9ad80442519defc5e4e3ee9aac`
- #5: `c4e5f6a7-8901-4bcd-ef23-4567890123cd` | 2026-08-20T05:12:00.000Z | GAP/inherited_workflow_seam_scope_gap_exact_count | incident=`d4e5f6a7-8901-4bcd-ef23-4567890123cd` | lesson_key=`inherited-workflow-seam-scope-gap-exact-count` | event_sha256=`cd4762a1cc025da0881d64b373ac05be7da5f6832103787a090442a91b2098d1`
- #6: `e5f6a7b8-9012-4cde-f345-6789012345ef` | 2026-08-20T05:15:00.000Z | GATE/remediation7_focused_current | incident=`e5f6a7b8-9012-4cde-f345-6789012345ef` | lesson_key=`remediation7-focused-gate-count-only` | event_sha256=`e4a0ebd8fbc086a1d24ed2d9ca0e0dad94030ff7841d259b99509fbfb90a5732`
- #7: `f6a7b8c9-0123-4def-4567-8901234567f0` | 2026-08-20T05:16:00.000Z | GATE/compileall_diff_check | incident=`f6a7b8c9-0123-4def-4567-8901234567f0` | lesson_key=`isolated-compileall-diff-current` | event_sha256=`dfb109399cd83bae0598120d4139e68f11602b46211008c9227071b94799cf8b`
- #8: `a7b8c9d0-1234-4ef5-6789-0123456789ab` | 2026-08-20T05:17:00.000Z | REVIEW/exact_tip_handoff | incident=`a7b8c9d0-1234-4ef5-6789-0123456789ab` | lesson_key=`exact-tip-remediation7-handoff` | event_sha256=`185f72e86d31f5162dd89169b9a6aff8704b7d3ccd24606b446a4655046e26e9`
- #9: `b8c9d0e1-2345-4f67-8901-2345678901bc` | 2026-08-20T05:20:00.000Z | STATE_CHANGE/line_completed | incident=`b8c9d0e1-2345-4f67-8901-2345678901bc` | lesson_key=`close-formal-line-on-current-evidence` | event_sha256=`d2d64994b98d538c3bac5ee53c4d11f1264fe68efda91069fd1f2699bca859d3`
