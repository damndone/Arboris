# Retrospective — v1-8-9-p0-legacy-resume-remediation-4

## Goal

# Workbench v1.8.9 P0 Legacy/Resume Remediation-4 Objective  Remediate the independent spec-review finding against exact remediation-3 tip \`8003f27b95bf8f8f2dcad4c35f556d68238c079e\` without editing remediation-3 or any other formal line, root checkout, or worktree.  ## Required outcomes  - ProposalStore admission is an opaque, server-issued capability rather than a   \`type(ProposalStore)\` check. A caller-created, temporary, forged, copied, or   reconstructed store is rejected even when it points at a complete file. The   compiler binds only a capability admitted by its server authority, and the   persisted compilation record and confirmation identity come from that same   authority and exactly match proposal id, revision, fingerprint, semantic   plan hash, actor, session, project, target, chain, and operation. - The legacy route reloads a canonical persisted proposal through the   server-owned store capability before parsing any precondition or consulting   authority, record, execute, claim, or write state. \`SimpleNamespace\`, a   synthetic/reconstructed ProposalRevision, forged caller revision, stale   receipt, replay, and persisted tamper all fail closed with no side effect. - Real repository and route probes cover caller-store admission, incomplete and   cross-scope compilation, persisted target tamper with an old fingerprint,   forged revision/receipt/replay, and synthetic direct-service calls. Positive   paths use the server-owned persisted proposal lifecycle. - Existing Resume artifact/output/lineage/model-branch and Agent/Notebook   focused safety coverage remains green. The remediation-3 \`COMPLETED\` versus   \`unresolved=5\` contradiction is recorded as a new formal review/gap and   resolved by this line's exact evidence; historical counts are not reused.  ## Boundary  - Affected paths: \`backend/workbench/agent/proposals.py\`,   \`backend/workbench/agent/orchestrator.py\`,   \`backend/workbench/http/agent_routes.py\`,   \`tests/test_v189_legacy_resume_remediation4.py\`,   \`tests/test_v189_legacy_resume_remediation3.py\`,   \`tests/test_v189_legacy_resume_remediation2.py\`,   \`tests/test_v189_agent_notebook_cutover.py\`,   \`tests/test_v189_legacy_route_authority.py\`,   \`docs/superpowers/objectives/2026-08-19-v1.8.9-p0-legacy-resume-remediation-4-objective.md\`,   \`docs/superpowers/plans/2026-08-19-v1.8.9-p0-legacy-resume-remediation-4.md\` - Allowed paths: exactly the affected paths above. - Protected paths: all root-level files, all other worktrees, all prior   \`.agent/devlines/*\` records, \`Report\`, \`data\`, \`classification\`, \`survey\`,   \`backend/workbench/providers\`, \`backend/workbench/http/runs_routes.py\`,   \`backend/workbench/report_view_model.py\`, and   \`backend/workbench/engine/stages/estimation.py\`. - Baseline: \`8003f27b95bf8f8f2dcad4c35f556d68238c079e\`. - Dependencies: remediation-3 predecessor and its review, remediation-2,   legacy proposal-binding remediation, legacy/resume hardening, Agent compiler   core, and contract-lock. - Tests: RED then GREEN real ProposalStore/compiler/route probes; focused   legacy route/proposal/compiler/resume/workflow/Agent-Notebook suites;   isolated compileall with cleanup; \`git diff --check\`; formal verify and   retrospective. - Known gates: browser acceptance NOT VERIFIED; provider/external runtime NOT   VERIFIED; full repository gate NOT VERIFIED; release NOT VERIFIED;   merge/tag NOT VERIFIED. No dependency installation, root write, push, PR,   merge, tag, or release operation.

## Final status

COMPLETED

## Metrics

- Failure frequency: 5/17 (29.4%; 29.4 per 100 events)
- Repeat rate: 0/5 (0.0%)
- Recurrence rate: 0/5 (0.0%)
- MTTR: median=1583000 ms (sample=5; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/3 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T02:29:58.000Z `tdd_red_legacy_resume_remediation_4`; cause_status: `known`; cause: The remediation-4 probes showed that a raw caller-created or reconstructed ProposalStore was accepted by the compiler, and synthetic or reconstructed legacy proposal objects reached precondition and receipt handling before canonical admission.; resolution: `open`; lesson: Prove opaque store admission and canonical proposal identity with real side-effect spies before implementing the server boundary.
- #4 2026-08-20T02:35:31.000Z `focused_fixture_migration_after_capability_cutover`; cause_status: `known`; cause: The first focused run after enforcing opaque store and route-reference admission exposed historical positive fixtures and direct route tests that still passed raw ProposalStore or synthetic proposal objects; the production boundary correctly rejected them.; resolution: `open`; lesson: Migrate positive fixtures to the real server-owned lifecycle rather than weakening a newly enforced authority boundary.
- #5 2026-08-20T02:38:50.000Z `focused_fixture_migration_after_capability_cutover`; cause_status: `known`; cause: The second focused run reduced the migration surface to 15 historical route and remediation-3 fixture failures: direct route tests still construct synthetic proposals, and incomplete/cross-scope compiler tests still pass a raw store instead of a server-issued capability.; resolution: `open`; lesson: Keep synthetic compatibility probes as explicit canonical-admission negatives and migrate only positive persisted lifecycle fixtures to the server-owned capability.
- #6 2026-08-20T02:47:09.000Z `tdd_red_receipt_authority_and_real_route_probes`; cause_status: `known`; cause: New real-lifecycle probes reached the existing route receipt store with a compiler-issued receipt but the store had no server-authority admission parameter; the four probes failed before proving success, replay, receipt tamper, or persisted-target tamper behavior.; resolution: `open`; lesson: Add the receipt authority admission and real persisted route probes before claiming the synthetic route tests cover receipt security.
- #8 2026-08-20T02:53:06.000Z `extended_focused_gate_environment_and_predecessor_contracts`; cause_status: `known`; cause: The extended command returned 87 failed, 463 passed, and 53 warnings. The compiler-core tests could not bind their external host Unix socket because this sandbox returned PermissionError; legacy direct WorkbenchOrchestrator tests still expect the historical confirmation bypass that remediation-4 intentionally typed-fails closed; unrelated workflow-seam fixtures omit the active_head_run_id now required by the existing workflow receipt contract.; resolution: `open`; lesson: Separate the remediation boundary from environment-blocked external-host tests and historical fixtures that encode a bypass the current fail-closed contract deliberately removed.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `canonical-negative-and-server-owned-positive-fixtures`: occurrences=1; cause_status: `known`; root cause: The second focused run reduced the migration surface to 15 historical route and remediation-3 fixture failures: direct route tests still construct synthetic proposals, and incomplete/cross-scope compiler tests still pass a raw store instead of a server-issued capability.; solution: `open`
- `extended-gate-boundary-separation`: occurrences=1; cause_status: `known`; root cause: The extended command returned 87 failed, 463 passed, and 53 warnings. The compiler-core tests could not bind their external host Unix socket because this sandbox returned PermissionError; legacy direct WorkbenchOrchestrator tests still expect the historical confirmation bypass that remediation-4 intentionally typed-fails closed; unrelated workflow-seam fixtures omit the active_head_run_id now required by the existing workflow receipt contract.; solution: `open`
- `receipt-authority-real-route-red`: occurrences=1; cause_status: `known`; root cause: New real-lifecycle probes reached the existing route receipt store with a compiler-issued receipt but the store had no server-authority admission parameter; the four probes failed before proving success, replay, receipt tamper, or persisted-target tamper behavior.; solution: `open`
- `server-owned-positive-fixtures`: occurrences=1; cause_status: `known`; root cause: The first focused run after enforcing opaque store and route-reference admission exposed historical positive fixtures and direct route tests that still passed raw ProposalStore or synthetic proposal objects; the production boundary correctly rejected them.; solution: `open`
- `server-owned-proposal-store-capability`: occurrences=1; cause_status: `known`; root cause: The remediation-4 probes showed that a raw caller-created or reconstructed ProposalStore was accepted by the compiler, and synthetic or reconstructed legacy proposal objects reached precondition and receipt handling before canonical admission.; solution: `open`

## Added tests

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_agent_notebook_cutover.py tests/test_v189_legacy_resume_remediation2.py tests/test_v189_legacy_resume_remediation3.py tests/test_v189_legacy_resume_remediation4.py tests/test_v189_legacy_route_authority.py -q; 70 passed`
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_legacy_route_authority.py tests/test_v189_legacy_compilation_authority.py tests/test_v189_legacy_resume_remediation2.py tests/test_v189_legacy_resume_remediation3.py tests/test_v189_legacy_resume_remediation4.py tests/test_v189_agent_compiler.py tests/test_v189_agent_notebook_cutover.py tests/test_v189_notebook_cutover_route.py tests/test_v189_agent_notebook_runtime_bridge.py tests/test_v189_resume_authority.py tests/test_v189_workflow_truth.py tests/test_agent_proposal_operations.py tests/test_agent_generic_workflow.py tests/test_agent_workflow_integration.py tests/test_workflow_resume.py tests/test_workflow_runtime.py tests/test_workflow_seam.py tests/contracts/test_v189_contract_lock.py -q; 87 failed, 463 passed, 53 warnings`
- `focused remediation-4 pytest command; 448 passed, 78 warnings in 61.65s`
- `legacy route/proposal/compiler focused suites; 448 passed`
- `remediation-2/3/4 and legacy route authority focused suites; 448 passed`
- `tests/test_v189_agent_notebook_cutover.py tests/test_v189_legacy_resume_remediation2.py tests/test_v189_legacy_resume_remediation3.py tests/test_v189_legacy_route_authority.py; 25 passed, 37 failed`
- `tests/test_v189_agent_notebook_cutover.py tests/test_v189_legacy_resume_remediation2.py tests/test_v189_legacy_resume_remediation3.py; PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_agent_notebook_cutover.py tests/test_v189_legacy_resume_remediation2.py tests/test_v189_legacy_resume_remediation3.py -q; 30 passed, 15 failed`
- `tests/test_v189_legacy_resume_remediation4.py and focused remediation-4 gate; 448 passed`
- `tests/test_v189_legacy_resume_remediation4.py real route lifecycle probes; 8 passed`
- `tests/test_v189_legacy_resume_remediation4.py; PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_legacy_resume_remediation4.py -q; 4 failed, 0 passed`
- `tests/test_v189_legacy_resume_remediation4.py; PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_legacy_resume_remediation4.py -q; 4 passed, 4 failed`

## New rules

- `canonical-negative-and-server-owned-positive-fixtures`: line experience occurrence(s)=1
- `extended-gate-boundary-separation`: line experience occurrence(s)=1
- `receipt-authority-real-route-red`: line experience occurrence(s)=1
- `server-owned-positive-fixtures`: line experience occurrence(s)=1
- `server-owned-proposal-store-capability`: line experience occurrence(s)=1

## Future guidance

- Add the receipt authority admission and real persisted route probes before claiming the synthetic route tests cover receipt security.
- Keep synthetic compatibility probes as explicit canonical-admission negatives and migrate only positive persisted lifecycle fixtures to the server-owned capability.
- Migrate positive fixtures to the real server-owned lifecycle rather than weakening a newly enforced authority boundary.
- Prove opaque store admission and canonical proposal identity with real side-effect spies before implementing the server boundary.
- Reconcile a predecessor completion contradiction with a new review event and exact current evidence rather than rewriting the old formal line.
- Resolve predecessor completion contradictions only through a new formal line and exact-tip evidence, never by editing historical records.
- Separate the remediation boundary from environment-blocked external-host tests and historical fixtures that encode a bypass the current fail-closed contract deliberately removed.

## Event index

- #1: `2781237f-df5b-40f3-b7b7-3bd6df45b615` | 2026-08-20T02:26:32.885Z | STATE_CHANGE/line_started | incident=`b6ac8f19-c4c9-437d-885f-e93d4f6bf1ec` | lesson_key=`frozen-context-before-start` | event_sha256=`0f67499898227f51f3d7978acf06eae580e58ed379409c1958f532d839c9d8c6`
- #2: `f4d8b5e2-6a1c-4d9f-8b37-2c0e5a7d1f64` | 2026-08-20T02:29:58.000Z | FAILURE/tdd_red_legacy_resume_remediation_4 | incident=`b7a2e9c4-1d6f-4b83-9e50-2c7a8d1f6b43` | lesson_key=`server-owned-proposal-store-capability` | event_sha256=`df679d2ae8a60bca7f4daf4675e95c8e43f860f2214c05c927aabf298f88e94c`
- #3: `c1e7a4d9-5b2f-4680-93c6-1a7d4e8b205f` | 2026-08-20T02:30:32.000Z | REVIEW/predecessor_completion_contradiction | incident=`d9b3f7a1-6c2e-4d80-95b7-1a4e8c2f603d` | lesson_key=`predecessor-completion-contradiction-reconciled` | event_sha256=`17756824eaa9d4b4c3ff687c557a41364aebad6c70fa7f6f5718cf56a11dcef7`
- #4: `e6b1c8f4-2a7d-49e0-93b5-1c6f8a2d704e` | 2026-08-20T02:35:31.000Z | FAILURE/focused_fixture_migration_after_capability_cutover | incident=`a4f9c2d7-1e6b-48a0-93c5-7d2f8b1e604a` | lesson_key=`server-owned-positive-fixtures` | event_sha256=`ac7d3a48056f10bc0ca19124a631e7b1d20cbff047923b912c6518f12594d5ec`
- #5: `b7c2d9e4-5f1a-4680-93b6-2c7d8e4f105a` | 2026-08-20T02:38:50.000Z | FAILURE/focused_fixture_migration_after_capability_cutover | incident=`c8d3eaf5-6a2b-4791-a4c7-3d8e9f502b16` | lesson_key=`canonical-negative-and-server-owned-positive-fixtures` | event_sha256=`b78a3aa99b049ebd3ee7de6af0aeffb8b4c3774968e392bc7405cf77f630bf6d`
- #6: `d8e3fa06-7b2c-49a1-b5d8-4e9f603c2717` | 2026-08-20T02:47:09.000Z | FAILURE/tdd_red_receipt_authority_and_real_route_probes | incident=`e9f4ab17-8c3d-4a2b-b6e9-5f0a714d3828` | lesson_key=`receipt-authority-real-route-red` | event_sha256=`ec193b7e64c43597795932b2a03921a4d0d279be8a6803bcf9aa8f13b69fea81`
- #7: `e9f4ab17-8c3d-4a2b-b6e9-5f0a714d3828` | 2026-08-20T02:50:12.000Z | GATE/focused_server_owned_legacy_route_green | incident=`f0a5bc28-9d4e-4b3c-c7fa-6a1b825e4939` | lesson_key=`remediation4-focused-green-current-count` | event_sha256=`51ce8026853b63156f1f09b11b9ef6a9751446904c869e981ebb8488624fd4eb`
- #8: `f0a5bc28-9d4e-4b3c-c7fa-6a1b825e4939` | 2026-08-20T02:53:06.000Z | FAILURE/extended_focused_gate_environment_and_predecessor_contracts | incident=`a1b6cd39-0e5f-4c4d-d80b-7b2c936f504a` | lesson_key=`extended-gate-boundary-separation` | event_sha256=`5e59af981ab20fa291c51a97200fa2897786fd1ec11267ed90317b80448b614b`
- #9: `1a2b3c4d-5e6f-4789-8a0b-1c2d3e4f5a60` | 2026-08-20T03:02:39.000Z | GATE/focused_remediation_green | incident=`2b3c4d5e-6f70-489a-9b0c-1d2e3f4a5b61` | lesson_key=`remediation4-focused-green-448` | event_sha256=`3ff39156a4dc3b4a4b33dd6ec314b3602fb73a46651395f68ec27e635c363baa`
- #10: `3c4d5e6f-7081-49a2-b3c4-d5e6f708192a` | 2026-08-20T03:04:42.000Z | GATE/compileall_diff_check_green | incident=`4d5e6f70-8192-4a3b-c4d5-e6f708192a3b` | lesson_key=`isolated-compileall-cleanup` | event_sha256=`e2ece4817f1bbb0ec2ef240fc2f187c2767c812e08f6dc8db354c18353ac5381`
- #11: `5e6f7081-92a3-4b4c-d5e6-f708192a3b4c` | 2026-08-20T03:05:10.000Z | REVIEW/predecessor_completion_contradiction_resolved | incident=`d9b3f7a1-6c2e-4d80-95b7-1a4e8c2f603d` | lesson_key=`predecessor-completion-contradiction-resolved` | event_sha256=`022b536a0f3eda0e16ff8087c57cfb995f18b7b2507a5e9f593d608dd5b9a4a1`
- #12: `6f708192-a3b4-4c5d-e6f7-08192a3b4c5d` | 2026-08-20T03:05:11.000Z | STATE_CHANGE/incident_resolved | incident=`b7a2e9c4-1d6f-4b83-9e50-2c7a8d1f6b43` | lesson_key=`tdd-red-legacy-resume-remediation-4-resolved` | event_sha256=`6dcecd032edf5d2c24147e931b88134dff065df898151e4ca94a9d7858e7636b`
- #13: `708192a3-b4c5-4d6e-f708-192a3b4c5d6e` | 2026-08-20T03:05:12.000Z | STATE_CHANGE/incident_resolved | incident=`a4f9c2d7-1e6b-48a0-93c5-7d2f8b1e604a` | lesson_key=`server-owned-positive-fixtures-resolved` | event_sha256=`56e8c837a46307bf11fcf0ff8295acbe6f127721f08899116cf3158fd47e8c77`
- #14: `8192a3b4-c5d6-4e7f-0819-2a3b4c5d6e7f` | 2026-08-20T03:05:13.000Z | STATE_CHANGE/incident_resolved | incident=`c8d3eaf5-6a2b-4791-a4c7-3d8e9f502b16` | lesson_key=`canonical-negative-and-server-owned-positive-fixtures-resolved` | event_sha256=`ae56852c250ce02f058b722956187e447e1a03a712bb5b2c10b43b0b6702d39e`
- #15: `92a3b4c5-d6e7-4f08-192a-3b4c5d6e7f08` | 2026-08-20T03:05:14.000Z | STATE_CHANGE/incident_resolved | incident=`e9f4ab17-8c3d-4a2b-b6e9-5f0a714d3828` | lesson_key=`receipt-authority-real-route-red-resolved` | event_sha256=`e0a89b099fee50ccee2a54bb29beb75aaf5825608267ec3f952d9398c1384e32`
- #16: `a3b4c5d6-e7f0-4819-2a3b-4c5d6e7f0819` | 2026-08-20T03:05:15.000Z | STATE_CHANGE/incident_resolved | incident=`a1b6cd39-0e5f-4c4d-d80b-7b2c936f504a` | lesson_key=`extended-gate-boundary-separation-resolved` | event_sha256=`7fcd7d7bf511cf9f0ca939fa78b49a5893b69ca53f1df84f63e8338fc0e5c9be`
- #17: `b4c5d6e7-f081-492a-3b4c-5d6e7f08192a` | 2026-08-20T03:07:54.000Z | STATE_CHANGE/line_completed | incident=`c5d6e7f0-8192-4a3b-4c5d-6e7f08192a3b` | lesson_key=`remediation4-exact-tip-handoff` | event_sha256=`d7e815c3c1e9228d51cfeadf1e589f7a15dc325f4a1f4173200b508e1c901ff5`
