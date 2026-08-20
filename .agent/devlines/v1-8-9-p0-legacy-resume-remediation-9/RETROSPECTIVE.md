# Retrospective — v1-8-9-p0-legacy-resume-remediation-9

## Goal

# Workbench v1.8.9 P0 Legacy/Resume Remediation-9 Objective  ## Objective  Close the independent P2 handoff/evidence gap at exact baseline \`621ee442084c4f34b9d42413a7140a39506df988\`: remediation-8's handoff records only its formal parent closeout tip/tree (\`e6c21cb2\` / \`ab1efd9b2\`), while the current final implementation/docs tip is \`621ee442\` / \`07856f3\`. Add an explicit real authority copy/pickle regression to the focused evidence; the existing product fail-closed behavior is already present and product code is out of scope.  ## Required outcomes  - Add a real regression that exercises the module-owned live proposal authority   through both \`copy\` and \`pickle\` paths and proves the authority cannot be   cloned or serialized across its trust boundary. - Keep the regression side-effect aware: proposal bytes, repository branch   entries, and agent event entries must remain unchanged when the authority   boundary rejects the operation. - Preserve all remediation-8 security behavior and route-owned positive paths;   do not modify product code. - Record the accurate implementation/docs baseline tip and final exact   HEAD/tree digests in this line's handoff, including the corrected remediation-8   formal closeout tip/tree and the later docs tip/tree. - Preserve remediation-8's known GAP classifications and every   \`NOT VERIFIED\` boundary; do not reopen or edit predecessor records.  ## Boundary  Affected paths:  - \`tests/test_v189_legacy_resume_remediation8.py\` - \`docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-9-objective.md\` - \`docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-resume-remediation-9-handoff.md\`  Protected paths include all predecessor \`.agent/devlines/*\` records, remediation-8 objective/plan/handoff files, \`backend/workbench/**\`, the root checkout, other worktrees, and unrelated source/tests/docs. Product code is explicitly out of scope.  Baseline: \`621ee442084c4f34b9d42413a7140a39506df988\`.  Dependencies: \`v1-8-9-p0-legacy-resume-remediation-8\`, its formal closeout \`e6c21cb2a8f42cf7d8f5d50b0f0c49f24b8cb9e2\` / \`ab1efd9b8b34032069c77a6eef920cf52030c005\`, current docs tip \`621ee442084c4f34b9d42413a7140a39506df988\` / \`07856f3002e2381dd4a4f8d39e0f5e26b814ae4e\`, and the legacy/resume authority, route, compiler, workflow-truth, and contract-lock evidence.  ## Tests and gates  - TDD/coverage regression: \`tests/test_v189_legacy_resume_remediation8.py\`. - Focused remediation-8 adversarial suite plus remediation-7, remediation-6,   remediation-5, remediation-2, route authority, Agent Notebook compiler,   workflow-resume, and relevant workflow seam positive-path suites. - \`PYTHONPYCACHEPREFIX=/private/tmp/workbench-v189-remediation9-pycache PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests\`. - \`git diff --check\` and frozen-scope/path verification. - Formal line verify, final GATE, retrospective, and exact HEAD/tree digest   handoff through \`scripts/devline_control.py\`.  Known GAPs remain open and must be carried forward: the historical direct service suite's stale 19 fixtures and the inherited workflow seam fixtures that omit \`active_head_run_id\`. Browser acceptance, external provider/runtime, host restart, true multi-worker deployment, full repository gate, integration, release, merge, tag, and push remain \`NOT VERIFIED\` unless directly run and evidenced here. No dependency installation, reset, checkout, destructive cleanup, root write, other-worktree write, product-code edit, push, merge, tag, or release operation is authorized.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/8 (37.5%; 37.5 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- #7 2026-08-20T12:07:00.000Z `formal_review_artifact_digest_format`; cause_status: `known`; cause: The first append attempt for the handoff review supplied the 40-character Git tree digest in the event field that requires a 64-character SHA-256 artifact digest; the event was rejected before append.; resolution: `resolved`; lesson: Validate formal event field digest widths before appending closeout review evidence.

## All gaps

- #3 2026-08-20T12:01:00.000Z `historical_direct_service_19_failures`; cause_status: `known`; cause: The historical direct-service suite still constructs WorkbenchOrchestrator without a server-owned proposal capability and asserts the removed direct-service mutation/response contract.; resolution: `open`; lesson: Keep the server-owned mutation boundary strict and classify stale direct-service fixtures as a known GAP instead of restoring the bypass.
- #4 2026-08-20T12:02:00.000Z `inherited_workflow_seam_scope_gap`; cause_status: `known`; cause: The inherited workflow seam suite uses fixtures without active_head_run_id, so compile_workflow rejects them at the existing WORKFLOW_SCOPE_MISSING boundary before seam assertions execute.; resolution: `open`; lesson: Keep the existing workflow scope admission contract strict and classify inherited fixtures that omit active_head_run_id separately from this test-only evidence line.

## All waste

- None recorded.

## Root causes and solutions

- `formal-event-digest-width-remediation9`: occurrences=1; cause_status: `known`; root cause: The first append attempt for the handoff review supplied the 40-character Git tree digest in the event field that requires a 64-character SHA-256 artifact digest; the event was rejected before append.; solution: `resolved`
- `historical-direct-service-19-failures-remediation9`: occurrences=1; cause_status: `known`; root cause: The historical direct-service suite still constructs WorkbenchOrchestrator without a server-owned proposal capability and asserts the removed direct-service mutation/response contract.; solution: `open`
- `inherited-workflow-seam-scope-gap-remediation9`: occurrences=1; cause_status: `known`; root cause: The inherited workflow seam suite uses fixtures without active_head_run_id, so compile_workflow rejects them at the existing WORKFLOW_SCOPE_MISSING boundary before seam assertions execute.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `formal-event-digest-width-remediation9`: line experience occurrence(s)=1
- `historical-direct-service-19-failures-remediation9`: line experience occurrence(s)=1
- `inherited-workflow-seam-scope-gap-remediation9`: line experience occurrence(s)=1

## Future guidance

- Handoffs must distinguish current implementation/docs evidence, formal parent closeout, test-only follow-up, known fixture gaps, and NOT VERIFIED release boundaries.
- Keep the existing workflow scope admission contract strict and classify inherited fixtures that omit active_head_run_id separately from this test-only evidence line.
- Keep the server-owned mutation boundary strict and classify stale direct-service fixtures as a known GAP instead of restoring the bypass.
- Validate formal event field digest widths before appending closeout review evidence.

## Event index

- #1: `7ca5733b-e7c7-4fca-b63c-3ba665b596a5` | 2026-08-20T05:57:59.988Z | STATE_CHANGE/line_started | incident=`5416436c-6305-4316-a17f-3a05e58ce71a` | lesson_key=`frozen-context-before-start` | event_sha256=`999165f58e7fdf9ed0650545a1930ec490adc7f97255f1e333a47c989d444b37`
- #2: `0f2d6a4c-8b1e-4f79-a3c5-9d7e1b2f6a40` | 2026-08-20T12:00:00.000Z | GATE/focused_adversarial_current | incident=`1a3c5e7f-9b2d-4e6a-8c0f-2b4d6e8a0c12` | lesson_key=`explicit-copy-pickle-authority-evidence` | event_sha256=`c22a04ce2ea12ed72ade996b28fba87ecb7468a3cce620e7f3f202b5f7d63029`
- #3: `2e4f6a8c-0b1d-4f7a-9c2e-5a6d8f0b2c14` | 2026-08-20T12:01:00.000Z | GAP/historical_direct_service_19_failures | incident=`3f5a7c9e-1b2d-4e6f-8a0c-2d4f6b8e1a35` | lesson_key=`historical-direct-service-19-failures-remediation9` | event_sha256=`fa8acf7af380551f42c57da63091acfd3b534a1e22aa5fe893a73b5c4c0974d9`
- #4: `4a6c8e0f-2b3d-5e7f-9a1c-3d5f7b9e2a46` | 2026-08-20T12:02:00.000Z | GAP/inherited_workflow_seam_scope_gap | incident=`5b7d9f1c-3e4a-6f8b-0d2e-4f6a8c1b3d59` | lesson_key=`inherited-workflow-seam-scope-gap-remediation9` | event_sha256=`38d3168a11378942bbb1468b2bbe82fd7658be2418a4feb9cf500d23b384b518`
- #5: `6c8e0f2a-4d6b-7f9c-1e3a-5f7b9d2c4a61` | 2026-08-20T12:03:00.000Z | GATE/compileall_diff_check | incident=`7d9f1b3e-5a7c-8f0d-2e4b-6f8a1c3d5e72` | lesson_key=`isolated-compileall-diff-current-remediation9` | event_sha256=`ac4a67dd30e5624e3c1ac59c48c2c5a847c3b3b781d32360daa0d0e0ea6b36c9`
- #6: `a2e4f6b8-0d1c-3e5a-7f9b-1d2f4a6c8e0f` | 2026-08-20T12:06:00.000Z | STATE_CHANGE/line_completed | incident=`b3d5f7a9-1c2e-4f6b-8d0a-2e4f6a8c0b1d` | lesson_key=`close-formal-line-on-current-evidence-remediation9` | event_sha256=`2861526f63402328799c6f6f6fdb3db2fd0a679ca29e8592da16fe3c26f85988`
- #7: `c4e6a8c0-2d4f-6b8e-0a1c-3e5f7b9d2a46` | 2026-08-20T12:07:00.000Z | ERROR/formal_review_artifact_digest_format | incident=`d5f7a9c1-3e5b-7d9f-1a2c-4e6f8b0d2a47` | lesson_key=`formal-event-digest-width-remediation9` | event_sha256=`276a49214dee3483db1e07286847001f7e2fe663467c25877e0d08897b8856c9`
- #8: `8e0f2a4c-6b8d-9f1a-3e5c-7b9d2f4a6c83` | 2026-08-20T12:05:00.000Z | REVIEW/exact_tip_handoff | incident=`9f1b3d5a-7c9e-0a2e-4f6b-8d1c3e5a7b94` | lesson_key=`exact-tip-remediation9-handoff` | event_sha256=`8c31e74d9470d7140840c392271fa922ae93ac84b2296df2efa84dfd8421c2e3`
