# Retrospective — v1-8-9-p0-legacy-resume-remediation-3

## Goal

# Workbench v1.8.9 P0 Legacy/Resume Remediation-3 Objective  Close the remaining NOT COMPLIANT findings against remediation-2 tip \`d545e9a08d8e3065e482db32852d873710d10edd\`. This line is independent of and must not rewrite \`v1-8-9-p0-legacy-resume-remediation-2\` or any other formal line, root checkout, or worktree.  Required outcomes:  - A ProposalStore proposal without a complete server-owned \`server_compilation\`   record fails closed. The record must contain actor, session, project,   semantic-plan hash, target, chain, operation, compilation record, and   confirmation identity. The persisted proposal target, chain, operation, and   every scope/identity field must exactly match the server compilation record;   generic incomplete proposals and cross-scope proposals never enter a   compiler binding. - The legacy route's \`_proposal_for_session\` or one equivalent route-owned   boundary must reread the persisted proposal, recompute the canonical   ProposalStore fingerprint from persisted fields, and reject any tampered   target or other critical field before \`_cutover_authority\`, compiler   \`record\`, \`execute\`, claim, or write. A stale original fingerprint cannot   authorize mutated persisted content. - Repository/route probes use real ProposalStore files and the route-owned   authority store to cover incomplete compilation, cross-scope identity,   persisted target tamper with the old fingerprint retained, forged caller   revision, forged receipt, and replay. Each rejection is fail closed with no   authority/record/execute/claim/write side effect. - Existing Resume completion, artifact, output, lineage, and model-branch   validation remains protected by the existing focused suites, including the   terminal model-step adversarial path. - Formal evidence records this line's exact baseline, RED failures, review/   gap findings, GREEN results, exact implementation commit, and formal   manifest. No previous \`355 passed\` or other historical metric is reused as   this line's result.  ## Boundary  - Affected paths: \`backend/workbench/agent/orchestrator.py\`,   \`backend/workbench/http/agent_routes.py\`,   \`tests/test_v189_legacy_resume_remediation3.py\`,   \`docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-3-objective.md\`,   \`docs/superpowers/plans/2026-08-20-v1.8.9-p0-legacy-resume-remediation-3.md\` - Allowed paths: exactly the affected paths above - Protected paths: \`backend/workbench/http/runs_routes.py\`,   \`backend/workbench/report_view_model.py\`, \`frontend/src/report\`,   \`backend/workbench/engine/stages/estimation.py\`,   \`backend/workbench/providers\`, all Report/data/classification/survey paths,   root-level files, all other worktrees, and all prior \`.agent/devlines/*\`   records including remediation-2 - Baseline: \`d545e9a08d8e3065e482db32852d873710d10edd\` - Dependencies: \`v1-8-9-p0-legacy-resume-remediation-2\`,   \`v1-8-9-p0-legacy-proposal-binding-remediation\`,   \`v1-8-9-p0-legacy-resume-hardening\`, \`v1-8-9-p0-agent-compiler-core\`,   \`v1-8-9-contract-lock\` - Tests: RED repository/route probes for incomplete/cross-scope/tampered   persisted proposals, forged caller revision/receipt, and replay; GREEN   legacy route/proposal/compiler/resume/workflow/Agent-notebook focused suites;   isolated compileall; \`git diff --check\`; formal verify; formal retrospective - Known gates: browser acceptance NOT VERIFIED, provider/external runtime NOT   VERIFIED, full repository gate NOT VERIFIED, release NOT VERIFIED,   merge/tag NOT VERIFIED; no dependency install, root write, push, PR, merge,   tag, or release operation

## Final status

CONTEXT_RESCOPED

## Metrics

- Failure frequency: 4/11 (36.4%; 36.4 per 100 events)
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

- #2 2026-08-20T01:50:43.000Z `tdd_red_legacy_resume_remediation_3`; cause_status: `known`; cause: The new remediation probes exposed that persisted ProposalStore compilation metadata was optional, target chain and operation were not bound, and the legacy route did not reject a tampered persisted target before execution. The first probe run reported 15 failed and 1 passed; three route cases also need the required active-head request field before they can exercise the boundary.; resolution: `open`; lesson: Keep repository-backed incomplete, scope, tamper, and replay probes red before implementing the smallest server-owned validation boundary.
- #3 2026-08-20T01:51:54.000Z `tdd_red_legacy_resume_remediation_3_corrected_probe`; cause_status: `known`; cause: After correcting the probe request envelope, the repository-backed remediation tests still showed that generic and incomplete server compilations bound successfully, cross-scope target chain and operation metadata was ignored, and the legacy route allowed persisted target tampering, incomplete compilation, and cross-scope compilation to reach the execute seam.; resolution: `open`; lesson: A corrected route request is required before interpreting a security probe, but the corrected red result must remain the implementation gate until all side-effect spies stay empty.
- #6 2026-08-20T01:57:56.000Z `focused_compiler_fixture_requires_server_compilation`; cause_status: `known`; cause: The stricter server-owned ProposalStore contract correctly rejected six pre-existing Agent/Notebook compiler fixtures that still created generic proposals without server_compilation metadata.; resolution: `open`; lesson: When tightening an authority contract, update positive fixtures to exercise the real server-owned lifecycle rather than weakening production validation for historical generic inputs.
- #7 2026-08-20T01:59:16.000Z `legacy_remediation2_fixture_requires_server_compilation`; cause_status: `known`; cause: The remediation-2 reload-before-binding regression fixture still created a generic ProposalStore proposal, so the remediation-3 validator stopped the flow before the intended latest-revision assertion.; resolution: `open`; lesson: Keep remediation history immutable while migrating its positive fixtures to the current server-owned lifecycle in the active remediation line.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `compiler-fixtures-must-persist-server-compilation`: occurrences=1; cause_status: `known`; root cause: The stricter server-owned ProposalStore contract correctly rejected six pre-existing Agent/Notebook compiler fixtures that still created generic proposals without server_compilation metadata.; solution: `open`
- `legacy-remediation-fixture-migrates-without-history-rewrite`: occurrences=1; cause_status: `known`; root cause: The remediation-2 reload-before-binding regression fixture still created a generic ProposalStore proposal, so the remediation-3 validator stopped the flow before the intended latest-revision assertion.; solution: `open`
- `legacy-resume-remediation3-corrected-red`: occurrences=1; cause_status: `known`; root cause: After correcting the probe request envelope, the repository-backed remediation tests still showed that generic and incomplete server compilations bound successfully, cross-scope target chain and operation metadata was ignored, and the legacy route allowed persisted target tampering, incomplete compilation, and cross-scope compilation to reach the execute seam.; solution: `open`
- `legacy-resume-remediation3-red-before-green`: occurrences=1; cause_status: `known`; root cause: The new remediation probes exposed that persisted ProposalStore compilation metadata was optional, target chain and operation were not bound, and the legacy route did not reject a tampered persisted target before execution. The first probe run reported 15 failed and 1 passed; three route cases also need the required active-head request field before they can exercise the boundary.; solution: `open`

## Added tests

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_legacy_route_authority.py tests/test_v189_agent_notebook_cutover.py tests/test_v189_notebook_cutover_route.py tests/test_v189_agent_notebook_runtime_bridge.py tests/test_v189_resume_authority.py tests/test_v189_workflow_truth.py tests/test_workflow_resume.py tests/test_workflow_runtime.py tests/test_v189_legacy_resume_remediation2.py tests/test_v189_legacy_resume_remediation3.py tests/contracts/test_v189_contract_lock.py -q; 371 passed, 53 warnings`
- `tests/test_v189_agent_notebook_cutover.py; PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_agent_notebook_cutover.py -q; 6 failed, 9 passed`
- `tests/test_v189_legacy_resume_remediation2.py; PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_legacy_resume_remediation2.py -q; 1 failed, 13 passed`
- `tests/test_v189_legacy_resume_remediation3.py; PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_legacy_resume_remediation3.py -q; 13 failed, 3 passed`
- `tests/test_v189_legacy_resume_remediation3.py; PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_legacy_resume_remediation3.py -q; 15 failed, 1 passed`

## New rules

- `compiler-fixtures-must-persist-server-compilation`: line experience occurrence(s)=1
- `legacy-remediation-fixture-migrates-without-history-rewrite`: line experience occurrence(s)=1
- `legacy-resume-remediation3-corrected-red`: line experience occurrence(s)=1
- `legacy-resume-remediation3-red-before-green`: line experience occurrence(s)=1

## Future guidance

- A corrected route request is required before interpreting a security probe, but the corrected red result must remain the implementation gate until all side-effect spies stay empty.
- Keep remediation history immutable while migrating its positive fixtures to the current server-owned lifecycle in the active remediation line.
- Keep repository-backed incomplete, scope, tamper, and replay probes red before implementing the smallest server-owned validation boundary.
- When tightening an authority contract, update positive fixtures to exercise the real server-owned lifecycle rather than weakening production validation for historical generic inputs.

## Event index

- #1: `b035d8f9-79d9-421c-b9bc-0902425e361f` | 2026-08-20T01:43:05.622Z | STATE_CHANGE/line_started | incident=`e5aec807-3129-4594-ae88-f85298c0cab9` | lesson_key=`frozen-context-before-start` | event_sha256=`de3854d976e72f9122491eadb9fbde1769670cf68451298755ebd811068dea48`
- #2: `3d6f1b5a-6a8a-4f8e-9f33-2b1f7d4a5c10` | 2026-08-20T01:50:43.000Z | FAILURE/tdd_red_legacy_resume_remediation_3 | incident=`a5e1c4d2-0b9f-4a86-8c21-7d3f6b2e9140` | lesson_key=`legacy-resume-remediation3-red-before-green` | event_sha256=`800142ea3d5a1e8ad83ddc7f447de6fac961a1e5944b57039ef9ab0144921b03`
- #3: `4e7a2c1d-8b9f-43a6-90d2-5c1e7f3b8a24` | 2026-08-20T01:51:54.000Z | FAILURE/tdd_red_legacy_resume_remediation_3_corrected_probe | incident=`b6f2d9a4-1c8e-47f0-9b3d-5a7e2c1f8640` | lesson_key=`legacy-resume-remediation3-corrected-red` | event_sha256=`97de4d07eac666a8d02cd8021326d14aa8461633cab9316a7252e83a3f19c6a7`
- #4: `44da499d-283a-4b26-9b38-0299981f6528` | 2026-08-20T01:53:35.137Z | STATE_CHANGE/context_rescope_required | incident=`f3cf3ed5-3e1f-4dbf-be77-cb3a60a1ecf2` | lesson_key=`context-pack-rescope` | event_sha256=`2a131944c8af376d06802103878b28e069af3b2dc4d7ac942b4b1c4355a1631c`
- #5: `ff9688a3-28e1-4137-b8b0-0bc6409510d5` | 2026-08-20T01:53:35.141Z | STATE_CHANGE/context_rescoped | incident=`80086199-57cc-4ff1-a2fe-edddab077127` | lesson_key=`context-pack-rescope` | event_sha256=`c97d83ad8129e5355f0a75707b5e3a13bce78fe8a05a7360b4d4debbfba4ae84`
- #6: `5f8b2d1c-7a4e-49f0-93c6-1d5e8b2a704f` | 2026-08-20T01:57:56.000Z | FAILURE/focused_compiler_fixture_requires_server_compilation | incident=`c7e3a1b5-9d4f-46e8-82c0-5a7b1d3f9642` | lesson_key=`compiler-fixtures-must-persist-server-compilation` | event_sha256=`12d167f7d93487321398793591c4ee5bf238b9a4559b6c7a6da8e96b73ae81c5`
- #7: `6a2e9f4c-1b7d-48f0-93c5-7e2a4d8b6f10` | 2026-08-20T01:59:16.000Z | FAILURE/legacy_remediation2_fixture_requires_server_compilation | incident=`d8f4b1c7-2e9a-46d0-83f5-1a7c4e9b6203` | lesson_key=`legacy-remediation-fixture-migrates-without-history-rewrite` | event_sha256=`549cbc2870692d6be98a6b23c77ca7e3ae8dbfee87876b890c71075a5874cb88`
- #8: `e88a857f-b96c-4fa1-9166-b4e6e1c1f809` | 2026-08-20T01:59:42.712Z | STATE_CHANGE/context_rescope_required | incident=`c5f7be15-bc67-4631-8d42-9585561b86bd` | lesson_key=`context-pack-rescope` | event_sha256=`573ecb10d6cda824dba83d19932ca5ea77810d19ffa1feb532e90a873467fd22`
- #9: `d5ba761a-010c-443f-9671-d801c78746e3` | 2026-08-20T01:59:42.718Z | STATE_CHANGE/context_rescoped | incident=`8de910bc-4816-486b-a49a-1a1ee8e0a8b5` | lesson_key=`context-pack-rescope` | event_sha256=`6d4f0fbb3e7e99fbbbcc048c29a42dfb1e311de4e1f39671ba2f2e59ef9a8e69`
- #10: `7b3e1d9a-5f2c-46e8-90a7-4d1f6b8c2e53` | 2026-08-20T02:05:40.000Z | GATE/focused_legacy_resume_green | incident=`e1c7a4f9-2b6d-48e0-93f5-7a1d4c8b6203` | lesson_key=`current-focused-gate-count-only` | event_sha256=`4875ba8ca898e4ce15c52b08a97106c37652c3b5746d391b626f7cdf465c02d3`
- #11: `8c4f1a7e-2d9b-46e0-93f5-6b1c7a4d820e` | 2026-08-20T02:06:39.000Z | GATE/isolated_compileall_and_diff_check | incident=`f2d8a4c1-7e9b-45f0-93c6-1a5d8b2e6047` | lesson_key=`isolated-compileall-zero-remaining` | event_sha256=`b20efe2a29cc7f385134e05280228ecee87a277d26aed5486560c269dff75400`
