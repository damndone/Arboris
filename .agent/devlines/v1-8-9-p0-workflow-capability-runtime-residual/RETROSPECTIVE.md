# Retrospective — v1-8-9-p0-workflow-capability-runtime-residual

## Goal

# Workbench v1.8.9 P0 Workflow Capability Runtime Residuals  ## Objective  Bring the remaining generic workflow capability and post-estimation tests onto the current admitted workflow host and server-owned artifact binding seam. Preserve the fail-closed behavior for missing, changed, foreign, or non-object evidence; do not add a production default endpoint or raw-file fallback.  ## Scope  - \`tests/test_workflow_capability_runtime.py\`  ## Acceptance  - Focused tests pass with explicit host admission where a real workflow is   executed. - Invalid capability outputs and post-estimation artifacts are rejected before   publication or are typed unavailable. - Production workflow runtime remains unchanged unless a separately approved   rescope is required by a demonstrated implementation defect.  ## Boundary  - Affected paths: \`tests/test_workflow_capability_runtime.py\` - Allowed paths: \`tests/test_workflow_capability_runtime.py\` - Protected paths: production workflow runtime and artifact persistence - Dependencies: current v1.8.9 workflow host admission and result binding - Tests: \`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -q tests/test_workflow_capability_runtime.py\` - Known gates: full backend, browser, production host/provider, and release gates remain separate

## Final status

COMPLETED

## Metrics

- Failure frequency: 4/7 (57.1%; 57.1 per 100 events)
- Repeat rate: 0/4 (0.0%)
- Recurrence rate: 0/4 (0.0%)
- MTTR: N/A (sample=0; unresolved=4)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T09:53:53.769Z `baseline_red`; cause_status: `known`; cause: The focused workflow capability runtime suite still calls write-capable execution without the current server admission receipt and host seam.; resolution: `open`; lesson: Keep real workflow tests on the deployment-owned host admission and server receipt seam before claiming focused green.
- #3 2026-08-21T09:59:05.395Z `contract_fixture_red`; cause_status: `known`; cause: After host admission was supplied, the residual tests exposed legacy source registry metadata, stale prepared-dataset paths, a normalized source variant mismatch, and canonical index digest rejection.; resolution: `open`; lesson: Align residual workflow fixtures with the current canonical registry and server-owned output contract before diagnosing remaining runtime behavior.
- #4 2026-08-21T10:03:03.077Z `scoped_red`; cause_status: `known`; cause: The admitted-host fixture reached the real model.genesis child run, which blocked on the configured 30-row modeling minimum; the replay test still searched for a removed workflow_datasets metadata path.; resolution: `open`; lesson: Use a model-sized fixture and assert tamper detection against the current server-owned workflow capability metadata path.
- #5 2026-08-21T10:10:07.505Z `replay_assertion_red`; cause_status: `known`; cause: The reference WorkflowExecutor replay correctly rejected tampered server-owned metadata with the admitted artifact content digest error, while the test assertion expected a broader legacy fingerprint or registry phrase.; resolution: `open`; lesson: Assert the canonical admitted artifact digest failure for replay tampering rather than a legacy path or generic registry phrase.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `prepared-dataset-consumer-child-run-red`: occurrences=1; cause_status: `known`; root cause: The admitted-host fixture reached the real model.genesis child run, which blocked on the configured 30-row modeling minimum; the replay test still searched for a removed workflow_datasets metadata path.; solution: `open`
- `replay-digest-assertion-contract`: occurrences=1; cause_status: `known`; root cause: The reference WorkflowExecutor replay correctly rejected tampered server-owned metadata with the admitted artifact content digest error, while the test assertion expected a broader legacy fingerprint or registry phrase.; solution: `open`
- `test-fixture-server-contract-alignment`: occurrences=1; cause_status: `known`; root cause: After host admission was supplied, the residual tests exposed legacy source registry metadata, stale prepared-dataset paths, a normalized source variant mismatch, and canonical index digest rejection.; solution: `open`
- `workflow-test-host-admission-red`: occurrences=1; cause_status: `known`; root cause: The focused workflow capability runtime suite still calls write-capable execution without the current server admission receipt and host seam.; solution: `open`

## Added tests

- `tests/test_workflow_capability_runtime.py`

## New rules

- `prepared-dataset-consumer-child-run-red`: line experience occurrence(s)=1
- `replay-digest-assertion-contract`: line experience occurrence(s)=1
- `test-fixture-server-contract-alignment`: line experience occurrence(s)=1
- `workflow-test-host-admission-red`: line experience occurrence(s)=1

## Future guidance

- Align residual workflow fixtures with the current canonical registry and server-owned output contract before diagnosing remaining runtime behavior.
- Assert the canonical admitted artifact digest failure for replay tampering rather than a legacy path or generic registry phrase.
- Keep real workflow tests on the deployment-owned host admission and server receipt seam before claiming focused green.
- Use a model-sized fixture and assert tamper detection against the current server-owned workflow capability metadata path.

## Event index

- #1: `479b20c2-a7c1-47f2-8837-bc130a34a2c8` | 2026-08-21T09:48:08.170Z | STATE_CHANGE/line_started | incident=`10e966db-f091-438c-89e5-e5dc263a388e` | lesson_key=`frozen-context-before-start` | event_sha256=`c041568c646e14c42e2eb4798e645f9217a14d21c0516c123fffc5144a068557`
- #2: `e11a3c8f-8b1a-47d4-a3a3-5a52b1a9a6d7` | 2026-08-21T09:53:53.769Z | FAILURE/baseline_red | incident=`4a6a9f1e-2e3b-4c4e-9f8f-0c6fd21f4a19` | lesson_key=`workflow-test-host-admission-red` | event_sha256=`e5bf813a35be0a42e97ae1e5d316425b6a40ded07d8b6944f7c9c02d4464de19`
- #3: `a4d0d6d7-6a76-4d2b-bbe3-8c3a5b7e4d91` | 2026-08-21T09:59:05.395Z | FAILURE/contract_fixture_red | incident=`d2d78ca8-9e78-45b0-bf7e-5d9b6c8a12e4` | lesson_key=`test-fixture-server-contract-alignment` | event_sha256=`fbf573d45c04fac4d9e97485f10bebc9b3aa8bd1c99944afbe3e42ddabc5d3de`
- #4: `b6d27d8e-1f4a-4b9a-8d60-3d4b3a7a8f52` | 2026-08-21T10:03:03.077Z | FAILURE/scoped_red | incident=`6b18df0f-7814-4e77-9858-49c1f6ea6b4f` | lesson_key=`prepared-dataset-consumer-child-run-red` | event_sha256=`6ce772f8a9ebc5e97bcc070ba2dae406fb0226e162b353c36b130d05d72fe316`
- #5: `c7a4e0a5-2f19-4a3d-9f72-8f22fb9f43aa` | 2026-08-21T10:10:07.505Z | FAILURE/replay_assertion_red | incident=`f343e2a6-0c58-4c72-a8cf-cc2d9a8c4b72` | lesson_key=`replay-digest-assertion-contract` | event_sha256=`f1d46dd753f57db754ac102131c3ca669f6c8e1b720b2fc2de52346898af74b8`
- #6: `d8e5a1c4-7b92-4f60-9a31-5c2e8d7f4b16` | 2026-08-21T10:12:14.948Z | GATE/workflow_capability_runtime_green | incident=`e1f7b3c9-5a28-4d60-8b14-6c2e9f0a7d35` | lesson_key=`workflow-capability-runtime-green` | event_sha256=`11261a719fa784aeb0638e55e072d8f1d4d603be39440f7971cc49204ab2ab82`
- #7: `f2a9c6e1-4b73-5d80-9e26-7c1a8f4d0b35` | 2026-08-21T10:12:29.955Z | STATE_CHANGE/line_completed | incident=`a7d3f9b5-1c6e-4a82-9f0b-5d2e8c7a4b16` | lesson_key=`formal-closeout` | event_sha256=`6acdb32cedb2d7ae7804dbd49b4cd907216433d25a0266896fb83f8400a2c615`
