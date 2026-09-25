# Retrospective — v1-8-9-p0-workflow-seam-scope-admission

## Goal

# Workbench v1.8.9 P0 Workflow Seam Scope Admission  ## Objective  Update the legacy workflow seam fixtures so they supply the compiler's typed scope admission (\`context_fingerprint\`, target run, and active head) before testing dataset bindings, replay, chained outputs, resume, and identity invalidation. Preserve each test's original assertion about lineage or binding; do not relax the compiler's scope requirement.  ## Scope  - \`tests/test_workflow_seam.py\`  ## Acceptance  - Focused workflow seam tests pass after the fixture admission correction. - Tests for missing/foreign/stale/unknown bindings still reach their intended   typed failure rather than failing earlier with missing scope. - No production default scope, implicit active head, or unbound fallback is   introduced.  ## Boundary  - Affected paths: \`tests/test_workflow_seam.py\` - Allowed paths: \`tests/test_workflow_seam.py\` - Protected paths: production compiler/workflow scope validation - Dependencies: current v1.8.9 workflow compiler receipt contract - Tests: \`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -q tests/test_workflow_seam.py\` - Known gates: full backend, browser, production host/provider, and release gates remain separate

## Final status

COMPLETED

## Metrics

- Failure frequency: 6/10 (60.0%; 60.0 per 100 events)
- Repeat rate: 0/6 (0.0%)
- Recurrence rate: 0/6 (0.0%)
- MTTR: N/A (sample=0; unresolved=6)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T09:51:46.876Z `workflow_scope_admission_fixture`; cause_status: `known`; cause: The legacy workflow seam fixture supplies context_fingerprint but omits the target run's active_head_run_id, so compiler scope admission rejects the setup before binding and lineage assertions execute.; resolution: `open`; lesson: Shared workflow fixtures must provide the full typed scope admission before tests exercise downstream binding and lineage contracts.
- #3 2026-08-21T09:55:56.505Z `workflow_runtime_fixture_admission`; cause_status: `known`; cause: After compiler scope admission is complete, legacy seam calls still invoke the write-capable callback without the server-issued step admission receipt or run execution through the deployment-owned workflow evidence endpoint.; resolution: `open`; lesson: Legacy workflow seam fixtures must use the current server-owned evidence port and step admission receipt while preserving the test's original binding assertion.
- #5 2026-08-21T10:32:26.884Z `workflow_model_dependency_selection`; cause_status: `known`; cause: The consuming joint step declares both a model producer and an ordinary dataset dependency; production branch selection treats the ordinary dependency as a model result without canonical model bindings.; resolution: `open`; lesson: Model post-estimation branch selection must inspect only model-producing dependencies while retaining all dependencies for frame resolution.

## All errors

- None recorded.

## All gaps

- #4 2026-08-21T10:02:10.833Z `protected_runtime_identity_gate`; cause_status: `known`; cause: The current protected workflow runtime refuses to merge a second numeric derivation into the existing node_index.json and raises numeric derivation node identity is not deterministic.; resolution: `open`; lesson: Do not bypass a protected runtime identity conflict in a scope-admission fixture; hand it off as a separate production runtime gate.
- #6 2026-08-21T10:32:27.006Z `workflow_resume_authority_gate`; cause_status: `known`; cause: A typed output binding removed from the workflow state is rejected by the server completion and state consistency gate before the legacy persistence-gap diagnostic can run.; resolution: `open`; lesson: Resume tests must distinguish server-authoritative completion mismatch from a downstream missing-binding diagnostic.
- #8 2026-08-21T10:33:51.279Z `workflow_model_auto_source_variant`; cause_status: `known`; cause: The lineage meta fixture supplies model.auto with a generic frame spec plus a source commitment, but the production contract accepts only the branches or exact generic variant shape and rejects the mixed shape before execution.; resolution: `open`; lesson: model.auto source commitments need an explicit contract-compatible variant before lineage coverage can execute.

## All waste

- None recorded.

## Root causes and solutions

- `workflow-model-auto-source-variant`: occurrences=1; cause_status: `known`; root cause: The lineage meta fixture supplies model.auto with a generic frame spec plus a source commitment, but the production contract accepts only the branches or exact generic variant shape and rejects the mixed shape before execution.; solution: `open`
- `workflow-model-dependency-selection`: occurrences=1; cause_status: `known`; root cause: The consuming joint step declares both a model producer and an ordinary dataset dependency; production branch selection treats the ordinary dependency as a model result without canonical model bindings.; solution: `open`
- `workflow-resume-authority-gate`: occurrences=1; cause_status: `known`; root cause: A typed output binding removed from the workflow state is rejected by the server completion and state consistency gate before the legacy persistence-gap diagnostic can run.; solution: `open`
- `workflow-runtime-fixture-admission`: occurrences=1; cause_status: `known`; root cause: After compiler scope admission is complete, legacy seam calls still invoke the write-capable callback without the server-issued step admission receipt or run execution through the deployment-owned workflow evidence endpoint.; solution: `open`
- `workflow-scope-admission-fixture`: occurrences=1; cause_status: `known`; root cause: The legacy workflow seam fixture supplies context_fingerprint but omits the target run's active_head_run_id, so compiler scope admission rejects the setup before binding and lineage assertions execute.; solution: `open`
- `workflow-seam-runtime-identity-gate`: occurrences=1; cause_status: `known`; root cause: The current protected workflow runtime refuses to merge a second numeric derivation into the existing node_index.json and raises numeric derivation node identity is not deterministic.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `workflow-model-auto-source-variant`: line experience occurrence(s)=1
- `workflow-model-dependency-selection`: line experience occurrence(s)=1
- `workflow-resume-authority-gate`: line experience occurrence(s)=1
- `workflow-runtime-fixture-admission`: line experience occurrence(s)=1
- `workflow-scope-admission-fixture`: line experience occurrence(s)=1
- `workflow-seam-runtime-identity-gate`: line experience occurrence(s)=1

## Future guidance

- Do not bypass a protected runtime identity conflict in a scope-admission fixture; hand it off as a separate production runtime gate.
- Legacy workflow seam fixtures must use the current server-owned evidence port and step admission receipt while preserving the test's original binding assertion.
- Model post-estimation branch selection must inspect only model-producing dependencies while retaining all dependencies for frame resolution.
- Resume tests must distinguish server-authoritative completion mismatch from a downstream missing-binding diagnostic.
- Shared workflow fixtures must provide the full typed scope admission before tests exercise downstream binding and lineage contracts.
- Test fixtures must exercise the current server admission and typed state contracts without widening production permissions.
- model.auto source commitments need an explicit contract-compatible variant before lineage coverage can execute.

## Event index

- #1: `485cd6cb-0b11-40b8-b667-af8bec21b792` | 2026-08-21T09:48:15.481Z | STATE_CHANGE/line_started | incident=`7db0f6f2-119e-4018-8c75-d0f08b5c7463` | lesson_key=`frozen-context-before-start` | event_sha256=`74d2827cb3bad663217ed6377538bf6bec888ccd3a790230c1d9ba4ff53e2774`
- #2: `8e5b82ae-4d67-4b7d-b9d8-3c750e24b4d6` | 2026-08-21T09:51:46.876Z | FAILURE/workflow_scope_admission_fixture | incident=`f4a142ea-8ff8-4e05-bc0f-6f4a3a66d3f4` | lesson_key=`workflow-scope-admission-fixture` | event_sha256=`5fe9cb1232c9f6de9b6a335bc47abdd428cf5e5eed5bda7e3c48cbc8d372fc23`
- #3: `5b99e54b-ff09-49f2-bb55-1bd12a984d02` | 2026-08-21T09:55:56.505Z | FAILURE/workflow_runtime_fixture_admission | incident=`a7fa20f6-8b3a-40cf-b60d-4bfb08fef572` | lesson_key=`workflow-runtime-fixture-admission` | event_sha256=`657a0c182e89d53bb74446832e399f123fbf04a76eae3a917579e0a2eeae121a`
- #4: `f2f61ab7-35f5-4a2c-a15f-9cb2b5ad9a82` | 2026-08-21T10:02:10.833Z | GAP/protected_runtime_identity_gate | incident=`d9e9f6cc-3006-4b77-8fbf-9b3228e17c30` | lesson_key=`workflow-seam-runtime-identity-gate` | event_sha256=`ed84ccc32870975dbb671cc070296a848862c2a9b23684771de360a7be7d0d22`
- #5: `3f4b1a8e-1e5a-4f8b-a1bc-68f15fbf3ef4` | 2026-08-21T10:32:26.884Z | FAILURE/workflow_model_dependency_selection | incident=`e7c1f0fd-2f61-4f62-8a91-8d581e5b63cd` | lesson_key=`workflow-model-dependency-selection` | event_sha256=`5c4f4773351dcb0942cc433abd53e42a7b696081d0ac36baecc99f781e2a0a8c`
- #6: `7e2d7a65-ec19-4ca7-86c3-2fc48d03f2f2` | 2026-08-21T10:32:27.006Z | GAP/workflow_resume_authority_gate | incident=`53cd0c7f-4e9c-4d27-9e66-b4bc2213fd52` | lesson_key=`workflow-resume-authority-gate` | event_sha256=`fcffae9e8270433be31c6b58889ae8b8c99dc577673bbb75574e4459693f90df`
- #7: `d8d750ac-fb2c-4312-9c8f-5a20eddbde4b` | 2026-08-21T10:32:27.130Z | REVIEW/workflow_seam_test_contract_migration | incident=`bc677524-6d04-4113-b1d5-2c82b3d21435` | lesson_key=`workflow-seam-test-contract-migration` | event_sha256=`6c0bbf5afc68380bf23ae6ef14de5501c9ee4e3e617e7661b20695dd1fa93cdf`
- #8: `5dcb9359-2b0d-4707-87bb-2f842cb3d320` | 2026-08-21T10:33:51.279Z | GAP/workflow_model_auto_source_variant | incident=`b8d4d30a-98b0-47bf-8bb8-e05aef669b23` | lesson_key=`workflow-model-auto-source-variant` | event_sha256=`a6415dc039da8693be3b6b6555dfe6f7e2297454b6254811f062ca24a09855e0`
- #9: `f4a8c2e6-1b7d-49d0-835c-2a6f7d1b9e4c` | 2026-08-21T10:38:20.870Z | GATE/workflow_seam_focused_gate | incident=`a6e2c8f4-1b7d-49d0-835c-2a6f7d1b9e4c` | lesson_key=`workflow-seam-scoped-green` | event_sha256=`e890dc85348c3ea93950ac66f0ce1de27406a06eaa1bb3ffa1796bd862f7c7b2`
- #10: `b7d3f9a1-6e2c-4a80-b5d1-9c7e3f2a6b84` | 2026-08-21T10:38:39.354Z | STATE_CHANGE/line_completed | incident=`c8e4a2f6-1b7d-49d0-835c-2a6f7d1b9e4c` | lesson_key=`workflow-seam-test-closeout` | event_sha256=`932b5e34c7ed380247598d833f1562472492076679607e1dba0df58c6f46cf85`
