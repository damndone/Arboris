# Retrospective — v1-8-9-p0-evidence-report-remediation-7

## Goal

# v1.8.9 P0 Evidence/Report Hardening — remediation-7 objective  ## Objective  At the exact clean baseline \`df25a0f5154520423ad45833daf4a1ccd3c1615b\`, close the independent P1-D finding left by remediation-6.  The production orchestrator path must provide \`ReportStage\` with the exact server-owned Report owner/projection pair through \`ctx.artifacts\`, and the ARMA-GARCH report branch must fail closed with typed unavailable state before it reads or constructs a raw deliverable when admission is absent.  ## Required outcomes  1. Exercise the real orchestrator run path, not only a helper: a server-owned    Report owner and its issued projection must be injected into    \`ctx.artifacts\` before the stage pipeline runs, so \`ReportStage.run\` can    receive the valid pair.  The owner/projection must remain exact server    admissions; caller-shaped or copied values must not be accepted. 2. Make the ARMA-GARCH branch perform the same owner/projection admission    before \`build_arma_garch_deliverables\` or any raw deliverable construction    or read.  Missing admission must produce typed unavailable/blocked report    state without invoking the raw builder.  A valid server-admitted owner and    projection must preserve the existing ARMA report path. 3. Add real stage integration probes for orchestrator-to-\`ReportStage\`    wiring, plus missing-admission and valid-admission ARMA-GARCH tests.  The    negative tests must prove the raw builder/read path was not reached and the    positive tests must prove the owner-issued path remains usable. 4. Run focused and impacted tests in a socket-capable host, direct admission    and no-IO/order probes, \`compileall\`, \`git diff --check\`, and formal    verification/retrospective generation.  Record exact RED/GREEN commands,    results, final commit, and digests in the remediation-7 handoff.  ## Boundaries  Only the target worktree may change.  Initial implementation scope is the Evidence/Report stage and its focused boundary tests plus remediation-7 objective/plan/handoff docs.  The orchestrator module is deliberately not in the initial allowlist; if the RED integration probe proves that the production injection requires \`backend/workbench/orchestrator/__init__.py\`, expand the formal Context Pack only with an explicit \`rescope-context\` call naming that exact file and no broader directory.  Do not modify central Agent/Notebook semantic engines, providers, estimators, frontend, dependencies, deployment wiring, the root checkout, or another worktree.  Push, merge, tag, release, and broad fallback behavior remain out of scope.  ## Protected paths  - \`backend/workbench/agent/\` - \`backend/workbench/http/agent_routes.py\` - \`backend/workbench/http/notebook_routes.py\` - \`backend/workbench/providers/\` - \`backend/workbench/estimator/\` - \`backend/workbench/live_host/\`

## Final status

COMPLETED

## Metrics

- Failure frequency: 8/21 (38.1%; 38.1 per 100 events)
- Repeat rate: 1/8 (12.5%)
- Recurrence rate: 1/7 (14.3%)
- MTTR: median=87891 ms (sample=5; unresolved=3)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/3 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #3 2026-08-20T04:55:31.931Z `orchestrator_report_admission_red`; cause_status: `known`; cause: The production orchestrator built the ModelingContext without injecting the exact server-owned Report owner and issued projection.; resolution: `open`; lesson: Inject only the exact server-issued Report owner/projection before the stage pipeline starts.
- #4 2026-08-20T04:55:48.470Z `arma_raw_builder_before_admission_red`; cause_status: `known`; cause: The ARMA-GARCH branch called build_arma_garch_deliverables even though Report owner/projection admission was absent.; resolution: `open`; lesson: Gate every ARMA report raw builder/read behind exact owner/projection admission.
- #7 2026-08-20T04:56:04.883Z `orchestrator_report_admission_red`; cause_status: `known`; cause: The real _run_workflow path did not inject the configured server-owned Report owner and projection into ctx.artifacts before the traced pipeline.; resolution: `open`; lesson: Exercise the production orchestrator entry point and inject only the exact server-owned Report pair before the stage pipeline.
- #8 2026-08-20T04:56:08.039Z `arma_report_admission_red`; cause_status: `known`; cause: The ARMA-GARCH ReportStage branch constructed the raw deliverable before checking for a server-owned Report admission.; resolution: `open`; lesson: Gate ARMA-GARCH raw deliverable construction on the same exact owner/projection admission used by Report rendering.

## All errors

- #2 2026-08-20T04:55:15.071Z `socket_capability_boundary`; cause_status: `external`; cause: The restricted runner rejected the Unix socket required by the server-owned authority fixture before the RED assertions could execute.; resolution: `resolved`; lesson: Record restricted-host socket failures separately and rerun authority probes on a supported host.

## All gaps

- #17 2026-08-20T05:03:13.580Z `legacy_arma_raw_renderer_boundary`; cause_status: `known`; cause: The standalone ARMA impacted test passes the raw deliverable mapping to the post-remediation-6 typed render_html_report writer contract.; resolution: `accepted`; lesson: Keep legacy ARMA raw renderer callers explicitly outside the owner-issued Report admission boundary.
- #18 2026-08-20T05:03:30.357Z `ownerless_normal_report_e2e_boundary_one`; cause_status: `known`; cause: The normal-run traceable-output E2E invokes the orchestrator without a server-owned Report capability and still asserts an ownerless report.html file.; resolution: `accepted`; lesson: Keep ownerless normal-run HTML assertions documented until their fixture injects server-owned Report admission.
- #19 2026-08-20T05:03:43.402Z `ownerless_normal_report_e2e_boundary_two`; cause_status: `known`; cause: The advanced-statistics normal-run E2E invokes the orchestrator without a server-owned Report capability and still reads an ownerless report.html file.; resolution: `accepted`; lesson: Keep ownerless normal-run HTML assertions documented until their fixture injects server-owned Report admission.

## All waste

- None recorded.

## Root causes and solutions

- `arma-report-admission`: occurrences=1; cause_status: `known`; root cause: The ARMA-GARCH ReportStage branch constructed the raw deliverable before checking for a server-owned Report admission.; solution: `open`
- `arma-report-admission-before-raw-read`: occurrences=1; cause_status: `known`; root cause: The ARMA-GARCH branch called build_arma_garch_deliverables even though Report owner/projection admission was absent.; solution: `open`
- `legacy-arma-raw-renderer-boundary`: occurrences=1; cause_status: `known`; root cause: The standalone ARMA impacted test passes the raw deliverable mapping to the post-remediation-6 typed render_html_report writer contract.; solution: `accepted`
- `orchestrator-report-admission`: occurrences=1; cause_status: `known`; root cause: The real _run_workflow path did not inject the configured server-owned Report owner and projection into ctx.artifacts before the traced pipeline.; solution: `open`
- `orchestrator-report-owner-injection`: occurrences=1; cause_status: `known`; root cause: The production orchestrator built the ModelingContext without injecting the exact server-owned Report owner and issued projection.; solution: `open`
- `ownerless-normal-report-e2e-boundary`: occurrences=2; cause_status: `known`; root cause: The normal-run traceable-output E2E invokes the orchestrator without a server-owned Report capability and still asserts an ownerless report.html file.; solution: `accepted`
- `socket-capable-host-evidence`: occurrences=1; cause_status: `external`; root cause: The restricted runner rejected the Unix socket required by the server-owned authority fixture before the RED assertions could execute.; solution: `resolved`

## Added tests

- `tests/models/arma_garch/test_deliverables.py`
- `tests/test_orchestrator_e2e.py`
- `tests/test_v189_evidence_report_boundary.py`
- `tests/test_v189_evidence_report_boundary.py::test_arma_garch_report_admission_missing_is_typed_and_does_not_build_raw_deliverable`
- `tests/test_v189_evidence_report_boundary.py::test_orchestrator_report_admission_injects_exact_pair_before_real_report_stage`

## New rules

- `arma-report-admission`: line experience occurrence(s)=1
- `arma-report-admission-before-raw-read`: line experience occurrence(s)=1
- `legacy-arma-raw-renderer-boundary`: line experience occurrence(s)=1
- `orchestrator-report-admission`: line experience occurrence(s)=1
- `orchestrator-report-owner-injection`: line experience occurrence(s)=1
- `ownerless-normal-report-e2e-boundary`: line experience occurrence(s)=2
- `socket-capable-host-evidence`: line experience occurrence(s)=1

## Future guidance

- Close duplicate RED records by preserving the same direct no-builder and positive owner evidence.
- Exercise the production orchestrator entry point and inject only the exact server-owned Report pair before the stage pipeline.
- Gate ARMA-GARCH raw deliverable construction on the same exact owner/projection admission used by Report rendering.
- Gate every ARMA report raw builder/read behind exact owner/projection admission.
- Gate every ARMA report raw read behind exact owner/projection admission.
- Inject only the exact server-issued Report owner/projection before the stage pipeline starts.
- Keep legacy ARMA raw renderer callers explicitly outside the owner-issued Report admission boundary.
- Keep ownerless normal-run HTML assertions documented until their fixture injects server-owned Report admission.
- Keep production admission injection at the orchestrator boundary and verify exact identity through the real pipeline context.
- Keep the owner-issued pair at the orchestrator context boundary and gate all report family builders behind it.
- Record restricted-host socket failures separately and rerun authority probes on a supported host.
- Resolve each recorded RED incident against its exact incident identity after the same probe is green.
- Use one admission gate before every family-specific Report deliverable builder.

## Event index

- #1: `25ef230e-19f8-4c60-ad39-79556fde5b6d` | 2026-08-20T04:49:49.572Z | STATE_CHANGE/line_started | incident=`0bed526e-687b-4651-b186-c0b1fdd7baba` | lesson_key=`frozen-context-before-start` | event_sha256=`c1ae7384aa7b56e807fc74f9c06f8bf2fcfae68bb7740d81d18f27b5a59248ff`
- #2: `d8e63c41-555d-4c4e-8c3a-6d6a3fcb9c11` | 2026-08-20T04:55:15.071Z | ERROR/socket_capability_boundary | incident=`a5a70f4f-3a54-4d72-88c3-5beefc55b624` | lesson_key=`socket-capable-host-evidence` | event_sha256=`a13db9ccc378cb92d57ccac91fd12f7e7ae75aa047bcf7d0d32051ba5ea433e9`
- #3: `eb0ec2e6-7ec7-4a1d-9d7d-e7ff3af9ce2b` | 2026-08-20T04:55:31.931Z | FAILURE/orchestrator_report_admission_red | incident=`bcdb7c62-2f36-4d80-a5f5-61781fdccf96` | lesson_key=`orchestrator-report-owner-injection` | event_sha256=`44f1d7c4d806a8968a452cb4cc9a773aef0acdd3215c232df3c3e06c5e720a00`
- #4: `f742c239-89ed-4f5a-9c38-4db55f5d93fb` | 2026-08-20T04:55:48.470Z | FAILURE/arma_raw_builder_before_admission_red | incident=`2be9b8b1-7766-4f6e-ae1a-bc0ea85685db` | lesson_key=`arma-report-admission-before-raw-read` | event_sha256=`4cdfa91f0cdf43ff550d646900f3df15f15eb5751cf28d5f746663bd4cf90c38`
- #5: `612cd921-ca7e-4cf8-bf5d-52e9263ace25` | 2026-08-20T04:56:01.699Z | STATE_CHANGE/context_rescope_required | incident=`7d770639-0874-465b-8984-23299586f41b` | lesson_key=`context-pack-rescope` | event_sha256=`4fc52f35480033bc5ad75d9ce3971335f1b72c299f7c03ce71eff706fbc02022`
- #6: `43393e06-832b-4d5a-b358-7046a84d9425` | 2026-08-20T04:56:01.703Z | STATE_CHANGE/context_rescoped | incident=`feac52b9-a6a4-4550-9ba7-2dc717c9d27d` | lesson_key=`context-pack-rescope` | event_sha256=`0ece5d9e968762fb19d20d1446b16b5cb828f8e8c6fe1a8879aca71d4d0ba549`
- #7: `4a0aa9fb-9e7e-4d16-9df5-44af95e8ea71` | 2026-08-20T04:56:04.883Z | FAILURE/orchestrator_report_admission_red | incident=`5a0e367c-a06f-4cdb-9cc2-8e5e5a235f0d` | lesson_key=`orchestrator-report-admission` | event_sha256=`7f0cec67dfb7a87d2b00291f58551e3d24c9d646a77e3a2c3617efaeb710c567`
- #8: `d2c43c23-8e5b-4437-82de-6c4a6bba6f2f` | 2026-08-20T04:56:08.039Z | FAILURE/arma_report_admission_red | incident=`8b1cc67a-10cf-4f14-9b5c-674ccd64c7c6` | lesson_key=`arma-report-admission` | event_sha256=`4db3cc948a3eacf98f1090294dc979107e148fb289f9e9204ca11f928b7e55c6`
- #9: `6f7f2304-61c7-4b1e-a1df-04a6fc554dbd` | 2026-08-20T04:56:59.822Z | REVIEW/remediation_seven_focused_green | incident=`bcdb7c62-2f36-4d80-a5f5-61781fdccf96` | lesson_key=`orchestrator-report-owner-injection` | event_sha256=`0e92e26db652610d4afcf92119a3cbf82949af60249daee5aa50b7fea434f283`
- #10: `a6d01231-c7df-4e6b-9e0d-2a1a46a9a8e0` | 2026-08-20T04:57:13.165Z | REVIEW/arma_admission_order_green | incident=`2be9b8b1-7766-4f6e-ae1a-bc0ea85685db` | lesson_key=`arma-report-admission-before-raw-read` | event_sha256=`0fcc591197841dcb4b6a1a528bb0c3a307f4b328e1f79f9f18ac10f64f280fc4`
- #11: `8a6e3f1b-3f88-4cf7-a8c3-7ab8be99eec8` | 2026-08-20T04:58:15.258Z | REVIEW/orchestrator_report_admission_green | incident=`bcdb7c62-2f36-4d80-a5f5-61781fdccf96` | lesson_key=`orchestrator-report-owner-injection` | event_sha256=`1f53b0a4cf1607f4a886bd03550730eb577fbc516d0f5b4c511e5f1184421c04`
- #12: `4de2eb15-5f4e-4b85-a868-ef5a7cfb7c80` | 2026-08-20T04:58:15.375Z | REVIEW/arma_report_admission_green | incident=`2be9b8b1-7766-4f6e-ae1a-bc0ea85685db` | lesson_key=`arma-report-admission-before-raw-read` | event_sha256=`75aea00b62585ef5a8a8af714a8535d60ea0625972f8170e59ca74d4650a1318`
- #13: `9e1e0b41-8f49-42ea-b1ac-fc9f1c2e0d2e` | 2026-08-20T04:58:15.492Z | REVIEW/orchestrator_report_admission_green_dup | incident=`5a0e367c-a06f-4cdb-9cc2-8e5e5a235f0d` | lesson_key=`orchestrator-report-admission` | event_sha256=`9f722964aa3a2804ca00b0d7f703a39ba3706cb60b76c2473ce1411315395d33`
- #14: `5a9bc92c-8a7a-4e08-bf86-14cfa963c6f4` | 2026-08-20T04:58:15.612Z | REVIEW/arma_report_admission_green_dup | incident=`8b1cc67a-10cf-4f14-9b5c-674ccd64c7c6` | lesson_key=`arma-report-admission` | event_sha256=`1a1073268b9e7cec417aae1d737313a7c1e99a1138f0c81f6c50642466be60b6`
- #15: `7c21ddc3-d87e-46cb-a54c-0b1260d57e31` | 2026-08-20T04:58:45.064Z | GATE/impacted_legacy_contract_boundary | incident=`8b2d7441-ecfd-4143-83f0-59ab1a7ee84a` | lesson_key=`legacy-report-contract-not-reopened` | event_sha256=`df286b5185e625fcb9247106ee8300b7bc55efd285141704cdc5f6bb1f160b91`
- #16: `c2df9303-4a5a-4470-98e2-c3143d05bdf3` | 2026-08-20T05:02:24.924Z | GATE/remediation_seven_verification_gate | incident=`f225c7b5-3f4a-4f4f-86c2-4d70b9d8c67e` | lesson_key=`evidence-report-remediation-gate` | event_sha256=`47b298c87ebe5346a67cf254503c03760ca1f923b5edd67fde38cfcae23b4df5`
- #17: `1c4be18c-2bd0-42f9-9b59-cbbd08cb7f53` | 2026-08-20T05:03:13.580Z | GAP/legacy_arma_raw_renderer_boundary | incident=`2bd3a8a0-91b3-48b8-a3f8-6eb33ff1ad2e` | lesson_key=`legacy-arma-raw-renderer-boundary` | event_sha256=`cd4d6f5c70b324528a198093ccc722d68bc91d361c0442cee82294f2e5eda380`
- #18: `9b805927-5746-4605-aad7-40ca96e1b6fe` | 2026-08-20T05:03:30.357Z | GAP/ownerless_normal_report_e2e_boundary_one | incident=`cfc93c85-bb0d-43b6-9d3a-a9f2c9d9c3a4` | lesson_key=`ownerless-normal-report-e2e-boundary` | event_sha256=`1c9df82f162e2a4c01fd98c017e1c4e47fb911a50e23c9e4e81a97ca7f7a40e0`
- #19: `a7d046c3-8d67-4215-a96a-0e5a1e6b90fb` | 2026-08-20T05:03:43.402Z | GAP/ownerless_normal_report_e2e_boundary_two | incident=`b9bd2b4b-9ed8-4f8f-bc95-2d65ddc8bd63` | lesson_key=`ownerless-normal-report-e2e-boundary` | event_sha256=`88b5734ba13df997ca9eac9211ab9805443b47e35d1bfd6403ca62282dc3777b`
- #20: `56e97c6a-6a1d-4b20-a277-cae3bfd7d26f` | 2026-08-20T05:04:25.538Z | GATE/remediation_seven_final_closeout_gate | incident=`c9289c58-6bd1-4f96-bd0a-6afc332d58c6` | lesson_key=`evidence-report-remediation-final-gate` | event_sha256=`076c99b959ac2511789aadf512fa97c27c20c5edbd221b61e6a2caad84153acb`
- #21: `d9f67f5b-bdf0-45ed-859e-ae89d28dd76a` | 2026-08-20T05:04:45.430Z | STATE_CHANGE/line_completed | incident=`7eec75cf-f176-4967-9a1b-71cec10e01a2` | lesson_key=`evidence-report-remediation-line-complete` | event_sha256=`daed54d762f653417e7a4cf0d5033c89afafcbb2e90c99a195de2badd82c4816`
