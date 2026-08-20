# Retrospective — v1-8-9-p0-legacy-resume-remediation-5

## Goal

# Workbench v1.8.9 P0 Legacy/Resume Remediation-5 Objective  Remediate the independent spec-review finding against exact remediation-4 tip \`137cc227e6819047c1124d40dbcce0d4255273cf\` without editing remediation-4, any predecessor formal line, the root checkout, or another worktree.  ## Required outcomes  - \`WorkbenchOrchestrator\` must not construct or expose a usable raw   \`ProposalStore\` for a direct caller. Proposal mutation requires an opaque,   server-owned \`ProposalStoreCapabilityV1\` admitted for the current repository   scope; a raw, caller-created, temporary, reconstructed, cross-scope, or   tampered store fails closed before any persistence or transcript write. - \`revise_proposal()\` and \`decline_proposal()\` reject the default/direct   service path with a typed boundary error before disk or memory mutation.   Explicit server-route use is retained only when the route passes its   server-owned capability and the capability root matches the repository. - Agent proposal routes pass the same server-owned capability into the   orchestrator for legitimate create/revise/decline flows. Legacy confirmation   and Resume artifact/output/lineage/model-branch protections remain intact. - Real probes cover direct revise, direct decline, default-store exposure,   raw/temporary/reconstructed/cross-scope/tampered store rejection, replay   rejection, route success, Resume regression, and zero disk/memory side   effects on every rejected path. - Formal evidence records exact reproducible nodeids/counts and current tip;   no historical \`448 passed\` claim is reused without its complete command.  ## Boundary  - Affected paths: \`backend/workbench/agent/orchestrator.py\`,   \`backend/workbench/http/agent_routes.py\`,   \`tests/test_v189_legacy_resume_remediation5.py\`,   \`tests/test_v189_legacy_route_authority.py\`,   \`tests/test_v189_agent_notebook_cutover.py\`,   \`tests/test_v189_resume_authority.py\`,   \`tests/test_workflow_resume.py\`,   \`docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-5-objective.md\`,   \`docs/superpowers/plans/2026-08-20-v1.8.9-p0-legacy-resume-remediation-5.md\` - Allowed paths: exactly the affected paths above. - Protected paths: root-level files, all other worktrees, all predecessor   \`.agent/devlines/*\` records, \`Report\`, \`data\`, \`classification\`, \`survey\`,   \`backend/workbench/providers\`, \`backend/workbench/http/runs_routes.py\`,   \`backend/workbench/report_view_model.py\`, and   \`backend/workbench/engine/stages/estimation.py\`. - Baseline: \`137cc227e6819047c1124d40dbcce0d4255273cf\`. - Dependencies: remediation-4, remediation-3, remediation-2,   legacy-proposal-binding, legacy/resume hardening, Agent compiler core, and   contract-lock formal evidence. - Tests: RED direct revise/decline/default-store and no-side-effect probes;   GREEN exact remediation-5 nodeids plus legacy route, Agent-Notebook,   Resume, and workflow focused suites; isolated compileall; \`git diff --check\`;   formal verify and retrospective. - Known gates: browser acceptance NOT VERIFIED; real provider/external runtime   NOT VERIFIED; host restart NOT VERIFIED; multi-worker/concurrency NOT   VERIFIED; full repository gate NOT VERIFIED; release NOT VERIFIED;   merge/tag NOT VERIFIED. No dependency installation, root write, push, PR,   merge, tag, or release operation.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/18 (11.1%; 11.1 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=690500 ms (sample=2; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: 0 (sample=1)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/3 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T03:31:00.000Z `remediation_5_red_direct_write_bypass`; cause_status: `known`; cause: The baseline WorkbenchOrchestrator exposes a raw ProposalStore by default and direct revise/decline calls write before any server-owned authority check.; resolution: `open`; lesson: Proposal mutation must require a live server-owned capability before proposal reads, authority, repository append, event emission, or replayable writes.
- #9 2026-08-20T03:40:00.000Z `remediation_2_fixture_boundary_red`; cause_status: `known`; cause: The predecessor direct-confirm negative fixture still used a default WorkbenchOrchestrator to create its setup proposal, so remediation-5 correctly rejected setup before the intended legacy confirmation assertion.; resolution: `open`; lesson: When a server-owned boundary changes, migrate positive fixture setup through the real capability before evaluating the legacy negative path.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `direct-proposal-write-bypass`: occurrences=1; cause_status: `known`; root cause: The baseline WorkbenchOrchestrator exposes a raw ProposalStore by default and direct revise/decline calls write before any server-owned authority check.; solution: `open`
- `server-owned-positive-fixture-migration`: occurrences=1; cause_status: `known`; root cause: The predecessor direct-confirm negative fixture still used a default WorkbenchOrchestrator to create its setup proposal, so remediation-5 correctly rejected setup before the intended legacy confirmation assertion.; solution: `open`

## Added tests

- `tests/test_v189_legacy_resume_remediation2.py; 14 passed`
- `tests/test_v189_legacy_resume_remediation5.py; 11 passed`

## New rules

- `direct-proposal-write-bypass`: line experience occurrence(s)=1
- `server-owned-positive-fixture-migration`: line experience occurrence(s)=1

## Future guidance

- A formal handoff must bind the exact implementation tip and current manifest to a reproducible command and explicit unverified boundaries.
- Proposal mutation must require a live server-owned capability before proposal reads, authority, repository append, event emission, or replayable writes.
- When a server-owned boundary changes, migrate positive fixture setup through the real capability before evaluating the legacy negative path.

## Event index

- #1: `a27001e7-0e2d-460f-aa63-bc1d49b80fad` | 2026-08-20T03:24:18.961Z | STATE_CHANGE/line_started | incident=`be19718a-a835-4cfc-b6cb-91c745ed3ec0` | lesson_key=`frozen-context-before-start` | event_sha256=`528f8206ccf8b617a79fe75f241f4496cd921fe65be6f74de08299fb0ed645d7`
- #2: `5e3b0f3e-8bf5-4c1f-9b6a-4b3d6f1e2a70` | 2026-08-20T03:31:00.000Z | FAILURE/remediation_5_red_direct_write_bypass | incident=`8cc6d0c5-3d1e-4f8a-b7c2-9e5a1f0d6b43` | lesson_key=`direct-proposal-write-bypass` | event_sha256=`96cd529643db1495a270a95c3cd413f3aa489dde448862e99e3f48bb05229360`
- #3: `2c36a556-aa23-49b8-9f3c-6fbee921386d` | 2026-08-20T03:36:17.377Z | STATE_CHANGE/context_rescope_required | incident=`c4457e66-0e9f-4f0f-bf53-b4e1959cb7aa` | lesson_key=`context-pack-rescope` | event_sha256=`78beea774074b4c7584271b1170f1d9f8e2cffc9e39a0930658f60e8e971f482`
- #4: `74e45b2e-93ee-4310-9324-500866858f5b` | 2026-08-20T03:36:17.381Z | STATE_CHANGE/context_rescoped | incident=`180a635b-fce1-4316-ae32-99cc468364ac` | lesson_key=`context-pack-rescope` | event_sha256=`c2c89e3642fa20bc75eef38755baa7632f667c4870317b031523d76feae0e71a`
- #5: `f28c29f2-e8a6-4be3-af4b-193343122c8b` | 2026-08-20T03:38:24.792Z | STATE_CHANGE/context_rescope_required | incident=`b89e88d5-f222-4c0f-97f2-c1760648b78e` | lesson_key=`context-pack-rescope` | event_sha256=`a17696fee029307b1347818897e576130d291575582ce9b75c8f6efb07244751`
- #6: `5863465b-1616-4afb-87b1-d23eaa5ae636` | 2026-08-20T03:38:24.797Z | STATE_CHANGE/context_rescoped | incident=`42d84529-e625-4a56-944b-2e2b78dcab02` | lesson_key=`context-pack-rescope` | event_sha256=`fa52defc2d6a508d1eab2d7514681093b0eee38c72196ac9f18705a8e7a5e46c`
- #7: `04a346a1-d220-42da-ab0f-fb040d9e4108` | 2026-08-20T03:41:11.233Z | STATE_CHANGE/context_rescope_required | incident=`37480e96-e19e-4b1c-b2e4-ad4fe4971567` | lesson_key=`context-pack-rescope` | event_sha256=`c20948d8b42f183541a0d8433ab3b94509b2ec827ddc1a3d5a5cfd815e56a527`
- #8: `541034b3-fc6b-4752-82b0-6c153d2eafda` | 2026-08-20T03:41:11.239Z | STATE_CHANGE/context_rescoped | incident=`f6af1a96-f70e-4e33-8791-db1b41cbfce4` | lesson_key=`context-pack-rescope` | event_sha256=`339599a37238d29b17721f8c407e281fe178b4686fe2ae87c564ad49526c9139`
- #9: `6f1b2c3d-4e5a-4678-9a0b-1c2d3e4f5a67` | 2026-08-20T03:40:00.000Z | FAILURE/remediation_2_fixture_boundary_red | incident=`7a2b3c4d-5e6f-4789-0a1b-2c3d4e5f6a78` | lesson_key=`server-owned-positive-fixture-migration` | event_sha256=`b947363c9ce14a4312bd31c7f81ffeb69ce883810dbda976aa6afbe1fedf4de0`
- #10: `6f9b2eb6-bf86-4af9-8f5f-a2dc807b828d` | 2026-08-20T03:44:22.609Z | STATE_CHANGE/context_rescope_required | incident=`71366e3e-c704-464d-b406-1bce78259a84` | lesson_key=`context-pack-rescope` | event_sha256=`13d2dcdd2bcd1ca76b909a383e0ff3a84a776ed50431f206df81b5e7e83fe1a8`
- #11: `69202d83-f5f0-4c6a-95a9-d69ba2c52b8a` | 2026-08-20T03:44:22.616Z | STATE_CHANGE/context_rescoped | incident=`781ebc7f-70c8-4786-86b8-23b1340de8b2` | lesson_key=`context-pack-rescope` | event_sha256=`fea8dbff49a8f6047b359f3973cc964cf94e7981fb95b5d8290899fd9e362030`
- #12: `8f2a4c6e-1b3d-4f5a-9c7e-0d2b4a6f8e1c` | 2026-08-20T03:47:00.000Z | STATE_CHANGE/incident_resolved | incident=`8cc6d0c5-3d1e-4f8a-b7c2-9e5a1f0d6b43` | lesson_key=`direct-proposal-write-bypass` | event_sha256=`d9e3a22b034635a1a341a7a18e825d507ef4a6e4d576867afb93dcd46f977f54`
- #13: `9a3b5d7f-2c4e-4a6b-8d0f-1b3c5e7a9d2f` | 2026-08-20T03:47:01.000Z | STATE_CHANGE/incident_resolved | incident=`7a2b3c4d-5e6f-4789-0a1b-2c3d4e5f6a78` | lesson_key=`server-owned-positive-fixture-migration` | event_sha256=`786e6c1b9809fc824f613112f6e7a1d17e6b238644de22bd6a86da5103d22728`
- #14: `ab4c6e8f-3d5a-4b7c-9e1f-2a4c6e8b0d3f` | 2026-08-20T03:47:02.000Z | GATE/focused_legacy_resume_green | incident=`ac5e7f91-2b4d-6f80-1a3c-5e7f9b2d4c6e` | lesson_key=`current-focused-gate-count-only` | event_sha256=`18610da934575ea45ff4d2ab90ef74370efe8972d29a26724046e0d79ef80645`
- #15: `bc5d7f90-4e6a-4c8b-0f2a-3d5e7f9b1c4a` | 2026-08-20T03:47:03.000Z | GATE/isolated_compileall_and_diff_check | incident=`bd6e8fa0-3c5d-7b91-2e4f-6a8c0d2e4f6b` | lesson_key=`isolated-compileall-zero-remaining` | event_sha256=`5d98975ee3b916dbb26945e8ffe2076f15fa93a54f5acd1d295406c9a6b6ee1c`
- #16: `cd6e8fa1-5b7d-4c9e-0a2f-3d6e8fb1c5a7` | 2026-08-20T03:47:04.000Z | GATE/known_external_acceptance_boundaries | incident=`ce7f90a1-2b4d-6e8f-3c5a-7d9b1f2e4c6a` | lesson_key=`external-gates-remain-not-verified` | event_sha256=`3d3ef313336268aa8e1c037bee35590c1cf79bc7de44d598f0e460209b3b91c5`
- #17: `de7f90a1-6b8c-4d0e-2f3a-5c7e9b1d4a6f` | 2026-08-20T03:47:05.000Z | REVIEW/exact_tip_handoff | incident=`df8a1b2c-3d4e-4f5a-6b7c-8d9e0f1a2b3c` | lesson_key=`exact-tip-remediation-handoff` | event_sha256=`e3f32b12bbb2d31d412a8ac838196811c620ffe542518474f68050f0cdb4e797`
- #18: `ef8a1b2c-3d4e-4f5a-6b7c-8d9e0f1a2b4d` | 2026-08-20T03:47:06.000Z | STATE_CHANGE/line_completed | incident=`f09b2c3d-4e5f-4a6b-7c8d-9e0f1a2b3c4d` | lesson_key=`exact-tip-remediation-handoff` | event_sha256=`19d46747f6d7607794f67f4c0527f6a4e2bb226837e33d51ac406a576977d860`
