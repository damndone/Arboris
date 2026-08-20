# Retrospective — v1-8-9-p0-legacy-resume-remediation-8

## Goal

# Workbench v1.8.9 P0 Legacy/Resume Remediation-8 Objective  ## Objective  Close the remaining P0 proposal authority bypass at exact baseline \`69b5b0079f0532ea7be7b6d8bd2a352dfa9f4294\`: a caller can directly construct \`_ProposalStoreServerAuthorityV1\`, call \`issue()\`, and pass the self-consistent issuer/service entry to \`ProposalStore._issue_server_capability\`, reaching real proposal side effects.  ## Required outcomes  - The module owns exactly one live server authority object. Direct constructor   calls fail closed permanently; \`object.__new__\` instances and field-forged,   copied, or serialized authority/entry objects cannot issue or admit anything. - \`authority.issue()\` succeeds only on the module-initialized singleton and   only creates entries admitted by that authority's registry and secret. - \`ProposalStore._issue_server_capability\` and \`_issue\` validate unique   authority object identity plus registry, secret, owner identity, issuer and   entry nonce, PID, generation, and exact root identity before any proposal,   repository, or event side effect. \`entry_nonce\` equality is explicit. - Add real adversarial RED/GREEN regressions for direct construction,   \`object.__new__\` forgery, caller \`issue()\`, forged entry/issuer bindings, and   zero side effects before and after the attempted path. - Preserve route-owned issuance and compiler/orchestrator positive proposal   paths. - Keep predecessor remediation-7 \`.agent/devlines\` records immutable. The new   handoff records its predecessor's corrected final exact HEAD/tree digest:   \`97c82f5e59e8e3cd104170152f7b53da8eda416a\` /   \`d15da557e1a704e4333fc685a9bfa30beaba1fb8\`.  ## Boundary  Affected paths:  - \`backend/workbench/agent/proposals.py\` - \`tests/test_v189_legacy_resume_remediation8.py\` - \`docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-8-objective.md\` - \`docs/superpowers/plans/2026-08-20-v1.8.9-p0-legacy-resume-remediation-8.md\` - \`docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-resume-remediation-8-handoff.md\`  Protected paths include all predecessor \`.agent/devlines/*\` records, the root checkout, other worktrees, unrelated route/compiler/orchestrator source, Report/data/classification/survey/provider paths, and predecessor source/tests.  Baseline: \`69b5b0079f0532ea7be7b6d8bd2a352dfa9f4294\`.  Dependencies: \`v1-8-9-p0-legacy-resume-remediation-7\`, its corrected handoff digest, legacy/resume authority hardening, route authority, Agent compiler cutover, workflow truth, and contract-lock evidence.  ## Tests and gates  - TDD RED then GREEN: \`tests/test_v189_legacy_resume_remediation8.py\`. - Focused remediation-8 adversarial suite plus remediation-7, remediation-6,   remediation-5, remediation-2, route authority, Agent Notebook compiler,   workflow-resume, and relevant workflow seam positive-path suites. - \`PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests\`. - \`git diff --check\` and scoped diff/path verification. - Formal line verify, final GATE, retrospective, and exact HEAD/tree digest   handoff.  Known external gates remain \`NOT VERIFIED\` unless run here: browser acceptance, external provider runtime, host restart, true multi-worker deployment, full repository gate, integration, release, merge, tag, and push. No dependency installation, destructive cleanup, root write, other-worktree write, push, merge, tag, or release operation is authorized.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/8 (37.5%; 37.5 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: N/A (sample=0; unresolved=3)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T05:40:00.000Z `remediation8_red_singleton_authority`; cause_status: `known`; cause: At the exact baseline, direct and object.__new__ server authorities can issue self-consistent issuer/service entries, and a tampered entry_nonce is not checked before capability admission; the real decline probe reaches proposal, repository, and event writes.; resolution: `open`; lesson: Keep singleton-authority and entry_nonce adversarial probes red until admission requires the exact module authority identity and complete registry binding.

## All errors

- None recorded.

## All gaps

- #3 2026-08-20T05:45:00.000Z `historical_direct_service_19_failures`; cause_status: `known`; cause: The historical direct-service suite still constructs WorkbenchOrchestrator without a server-owned proposal capability and asserts the removed direct-service mutation/response contract.; resolution: `open`; lesson: Keep the server-owned mutation boundary strict and classify stale direct-service fixtures as a known GAP instead of restoring the bypass.
- #4 2026-08-20T05:46:00.000Z `inherited_workflow_seam_scope_gap`; cause_status: `known`; cause: The inherited workflow seam suite uses fixtures without active_head_run_id, so compile_workflow rejects them at the existing WORKFLOW_SCOPE_MISSING boundary before seam assertions execute.; resolution: `open`; lesson: Keep the existing workflow scope admission contract strict and classify inherited fixtures that omit active_head_run_id separately from this authority fix.

## All waste

- None recorded.

## Root causes and solutions

- `historical-direct-service-19-failures-remediation8`: occurrences=1; cause_status: `known`; root cause: The historical direct-service suite still constructs WorkbenchOrchestrator without a server-owned proposal capability and asserts the removed direct-service mutation/response contract.; solution: `open`
- `inherited-workflow-seam-scope-gap-remediation8`: occurrences=1; cause_status: `known`; root cause: The inherited workflow seam suite uses fixtures without active_head_run_id, so compile_workflow rejects them at the existing WORKFLOW_SCOPE_MISSING boundary before seam assertions execute.; solution: `open`
- `remediation8-red-singleton-authority`: occurrences=1; cause_status: `known`; root cause: At the exact baseline, direct and object.__new__ server authorities can issue self-consistent issuer/service entries, and a tampered entry_nonce is not checked before capability admission; the real decline probe reaches proposal, repository, and event writes.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `historical-direct-service-19-failures-remediation8`: line experience occurrence(s)=1
- `inherited-workflow-seam-scope-gap-remediation8`: line experience occurrence(s)=1
- `remediation8-red-singleton-authority`: line experience occurrence(s)=1

## Future guidance

- Handoffs must distinguish current security evidence, known fixture gaps, predecessor exact digests, and NOT VERIFIED release boundaries.
- Keep singleton-authority and entry_nonce adversarial probes red until admission requires the exact module authority identity and complete registry binding.
- Keep the existing workflow scope admission contract strict and classify inherited fixtures that omit active_head_run_id separately from this authority fix.
- Keep the server-owned mutation boundary strict and classify stale direct-service fixtures as a known GAP instead of restoring the bypass.

## Event index

- #1: `4e208893-0cab-4f99-aacc-933a0b8f9deb` | 2026-08-20T05:36:00.876Z | STATE_CHANGE/line_started | incident=`749b4d2b-00a4-4f83-8550-97be7ecda85f` | lesson_key=`frozen-context-before-start` | event_sha256=`9b9e98fd266a5a7fda128ba19841278f3812e0ee66e3a9a559e0030a3d062fa4`
- #2: `b1d7e7b1-88ce-4d1d-a188-2c5b8d8d5f81` | 2026-08-20T05:40:00.000Z | FAILURE/remediation8_red_singleton_authority | incident=`2b4b0e4a-9c77-4c9f-9e72-3f8de3ed91d4` | lesson_key=`remediation8-red-singleton-authority` | event_sha256=`f0acb136f120f1a3ee857d09268ba30f573756b3e0c90dd747b30991d0def4b3`
- #3: `d4e52e8a-c5b8-4f65-8b93-7a1c0f2d6e44` | 2026-08-20T05:45:00.000Z | GAP/historical_direct_service_19_failures | incident=`f3b1c7d9-2e5a-4f80-9c61-8a4d0e7b5c22` | lesson_key=`historical-direct-service-19-failures-remediation8` | event_sha256=`a58a16efddb07ef5c23c60c07fe7c04db500d08d01965278a78e8aed2201bbfa`
- #4: `8f2c6a1d-4b9e-47d0-a5c3-7e1b8d4f9026` | 2026-08-20T05:46:00.000Z | GAP/inherited_workflow_seam_scope_gap | incident=`1c7e5a9d-3f2b-4d80-a6e1-9b5c2f7d8043` | lesson_key=`inherited-workflow-seam-scope-gap-remediation8` | event_sha256=`6a1250c909eb6fb2b2ac7815e1f1cc918604fe105cae5cdf7c2dea568cc67481`
- #5: `4a8d2f7c-1e5b-4c90-a6f3-8b2d7e1c5a49` | 2026-08-20T05:52:00.000Z | GATE/remediation8_focused_current | incident=`6c1e8a4f-9b2d-47f0-a5e3-8d7c2b1f9046` | lesson_key=`remediation8-focused-current` | event_sha256=`b6221573cc629cc2bceb3066b663b5bec7fc5b06732e3b154889894e0a0d8889`
- #6: `9d3f7a1c-5e8b-4d20-a6c9-2f1e7b4d8053` | 2026-08-20T05:53:00.000Z | GATE/compileall_diff_check | incident=`2e8b4c1f-7d5a-4093-a6f2-1c9e7b4d8058` | lesson_key=`isolated-compileall-diff-current-remediation8` | event_sha256=`f135b277542a7ad76b2c00ea55936190961d58307493e08853a85628a6dfbeea`
- #7: `7e1c4a9d-5b2f-48d0-a6e3-9c7b1f2d8054` | 2026-08-20T05:56:00.000Z | REVIEW/exact_tip_handoff | incident=`3d8f1b6c-4a2e-5079-b5c1-7e9d2f4a8063` | lesson_key=`exact-tip-remediation8-handoff` | event_sha256=`c4d8554a61bb592021d26e482fb938681df30f393c6abd550dd7f1cce5c2db80`
- #8: `a5d1e7c3-9b4f-4062-8e1a-7c5d2f9b8046` | 2026-08-20T05:57:00.000Z | STATE_CHANGE/line_completed | incident=`8c2f6a1d-4b9e-5073-a6e1-9d5c2f7b8048` | lesson_key=`close-formal-line-on-current-evidence-remediation8` | event_sha256=`fb6462222c76dca29168fb7638c8f20b654e1c3077ee026446010ad47ccdfabf`
