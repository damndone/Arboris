# Retrospective — v1-8-3-integration-acceptance

## Goal

# v1.8.3 capability runtime integration objective  Implement the remaining local, design-scoped v1.8.3 product integration:  1. connect the server-owned capability authority to the production application    bootstrap and execution gateway without introducing test keys, unsigned    fallbacks, or a weaker containment fallback; 2. expose the admitted \`model.custom\` path through the existing Notebook,    proposal/risk authorization, Draft, Run, Graph, and artifact contracts; 3. run a controlled local fixture through adapter generation and independent    validation evidence, including the experimental -> verified -> approved    promotion rules, while keeping author-supplied self-tests non-authoritative; 4. connect dependency bundle assembly and its server-owned build/scan receipt    to the actual execution gateway handoff, with offline analysis execution.  The implementation must preserve fail-closed behavior when the host cannot prove native containment. It may make the explicitly authorized local profile observable as experimental, but it must not claim production admission without real authority and containment evidence. No host Workbench environment may be modified by dynamic package installation.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/43 (7.0%; 7.0 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/20 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- #7 2026-07-28T00:57:54.000Z `invalid_status_probe`; cause_status: `known`; cause: A read-only development-line status probe used a command that is not defined by the formal CLI.; resolution: `resolved`; lesson: Use only the formal CLI subcommands documented by the development-line control script.

## All gaps

- #3 2026-07-28T00:18:30.000Z `darwin_containment_host_gap`; cause_status: `external`; cause: The current macOS host rejects the sandbox primitive with sandbox_apply Operation not permitted during code execution and native containment canaries.; resolution: `open`; lesson: Treat host containment rejection as an external gate gap and preserve fail-closed execution until a supported host is available.
- #24 2026-07-28T08:58:45.000Z `formal_scope_narrowing_constraint`; cause_status: `known`; cause: The formal rescope CLI rejects legacy broad allowlist entries and also rejects the exact backend app module when replacing an allowlist, so the B0 package could not be added without modifying protected control code.; resolution: `mitigated`; lesson: When a formal allowlist replacement rejects legacy broad paths, preserve the frozen scope and compose through existing allowed interfaces rather than editing control machinery.

## All waste

- None recorded.

## Root causes and solutions

- `formal-cli-command-surface`: occurrences=1; cause_status: `known`; root cause: A read-only development-line status probe used a command that is not defined by the formal CLI.; solution: `resolved`
- `formal-scope-narrowing`: occurrences=1; cause_status: `known`; root cause: The formal rescope CLI rejects legacy broad allowlist entries and also rejects the exact backend app module when replacing an allowlist, so the B0 package could not be added without modifying protected control code.; solution: `mitigated`
- `supported-host-containment-required`: occurrences=1; cause_status: `external`; root cause: The current macOS host rejects the sandbox primitive with sandbox_apply Operation not permitted during code execution and native containment canaries.; solution: `open`

## Added tests

- `npx vitest run; npx tsc --noEmit; src/workbench/WorkbenchRouteContainer.test.tsx`
- `tests/test_agent_tools.py::test_tool_registry_surfaces_analysis_loop_source_errors_to_agent`
- `tests/test_api.py`
- `tests/test_capability_custom_dispatcher.py::test_preflight_accepts_notebook_content_addressed_binding_reference`
- `tests/test_capability_dependency_service.py`
- `tests/test_capability_factory_runtime.py`
- `tests/test_capability_factory_runtime.py plus local Notebook browser flow`
- `tests/test_capability_factory_runtime.py::test_deployment_runtime_binds_external_authority_scanner_and_signed_report_source`
- `tests/test_capability_notebook_materialization.py::test_authorized_notebook_gateway_runs_real_local_darwin_adapter`
- `tests/test_capability_notebook_materialization.py::test_authorized_notebook_gateway_runs_real_local_darwin_adapter and tests/test_notebook_routes.py::test_model_custom_route_runs_generated_adapter_through_local_experimental_gateway on host execution`
- `tests/test_capability_validation_service.py::test_validation_harness_promotes_real_local_adapter_through_independent_oracle`
- `tests/test_capability_workflow_contract.py`
- `tests/test_local_supply_chain_scanner.py plus capability runtime, dependency, and Notebook route tests`
- `tests/test_notebook_routes.py::test_model_custom_route_runs_generated_adapter_through_local_experimental_gateway`
- `tests/test_sandbox.py`

## New rules

- `formal-cli-command-surface`: line experience occurrence(s)=1
- `formal-scope-narrowing`: line experience occurrence(s)=1
- `supported-host-containment-required`: line experience occurrence(s)=1

## Future guidance

- Do not retain a compatibility setter that can bypass a newly required server-owned execution gate.
- Keep an admission scope category distinct from a project scope reference when wiring dependency execution tests.
- Keep the full Notebook binding digest and the legacy resolver reference as two explicit server-owned ABI forms at the CF4 join.
- Rehydrate durable transition prefixes through the same controller rules before appending a new trusted state.
- Surface bounded, server-owned refusal reasons to the Agent when they are actionable; keep internal faults opaque.
- Treat host containment rejection as an external gate gap and preserve fail-closed execution until a supported host is available.
- Use one contract table for composable workflow fields, vocabulary, validation metadata, and registry projection; keep deliberate direct-operation identity collisions explicit.
- Use only the formal CLI subcommands documented by the development-line control script.
- When a formal allowlist replacement rejects legacy broad paths, preserve the frozen scope and compose through existing allowed interfaces rather than editing control machinery.

## Event index

- #1: `af0bcc15-e27e-4227-8a73-790cc3e06baf` | 2026-07-27T23:39:10.649Z | STATE_CHANGE/line_started | incident=`3140fe92-780f-4d90-86e3-185dbc5216ba` | lesson_key=`frozen-context-before-start` | event_sha256=`f03e72da03c796e5af0d533f53889989e8ca63f1d205391a8a0f56cdf43d20eb`
- #2: `c0a80118-6f3e-4d21-9dc7-3ca8b9d4f101` | 2026-07-28T00:18:10.000Z | GATE/capability_factory_focused_gate | incident=`c0a80118-6f3e-4d21-9dc7-3ca8b9d4f102` | lesson_key=`separate-capability-control-plane-gate` | event_sha256=`37085f069e0e189701356eec462cea18f98ebaa7f0c33dcfc9ebff7f248d9eea`
- #3: `c0a80118-6f3e-4d21-9dc7-3ca8b9d4f103` | 2026-07-28T00:18:30.000Z | GAP/darwin_containment_host_gap | incident=`c0a80118-6f3e-4d21-9dc7-3ca8b9d4f104` | lesson_key=`supported-host-containment-required` | event_sha256=`14cae892c8daf88bb21e4725b36ba9dd692badf19a57c6ed96d7f15f4d420ec8`
- #4: `c0a80118-6f3e-4d21-9dc7-3ca8b9d4f105` | 2026-07-28T00:22:10.000Z | REVIEW/persistent_admission_rehydration | incident=`c0a80118-6f3e-4d21-9dc7-3ca8b9d4f106` | lesson_key=`rehydrate-admission-transitions` | event_sha256=`aef52ed4d17d1b00d5628c2eae0907ef8e216cff648104b2388a78f468ae5405`
- #5: `c0a80118-6f3e-4d21-9dc7-3ca8b9d4f107` | 2026-07-28T00:24:10.000Z | REVIEW/legacy_gateway_bypass_closed | incident=`c0a80118-6f3e-4d21-9dc7-3ca8b9d4f108` | lesson_key=`close-legacy-execution-bypass` | event_sha256=`f2f62450762f8f36c71eb0c53d7eb4d689a0724c11d2f087216890ac6c6c8656`
- #6: `c0a80118-6f3e-4d21-9dc7-3ca8b9d4f109` | 2026-07-28T00:34:10.000Z | GATE/full_pytest_host_boundary | incident=`c0a80118-6f3e-4d21-9dc7-3ca8b9d4f110` | lesson_key=`full-gate-host-limited` | event_sha256=`2b3ec922d05a61700a329dcf8dd745bb427c8e47b813b298d78ce3e392fa711f`
- #7: `7f0a0c1e-9cb3-42e6-8c50-ff5e61a01e11` | 2026-07-28T00:57:54.000Z | ERROR/invalid_status_probe | incident=`7f0a0c1e-9cb3-42e6-8c50-ff5e61a01e12` | lesson_key=`formal-cli-command-surface` | event_sha256=`c87a46173c1270ed7a3fb68c632a9b6f05c027ec1156a44dc823b7bd844a3c2c`
- #8: `a6b0dd62-5c1a-49b0-a0a0-e94d2a4428a7` | 2026-07-28T01:11:06.892Z | STATE_CHANGE/context_rescope_required | incident=`136bce13-65bd-4afd-b346-84027dfc95f4` | lesson_key=`context-pack-rescope` | event_sha256=`a52e62635ed924592c3fdf14d9879e0372674b3a4151a7df23916470a25c7e43`
- #9: `8691ea85-b92e-4520-9082-cd20ec87a298` | 2026-07-28T01:11:06.896Z | STATE_CHANGE/context_rescoped | incident=`fbb84f92-e41c-4a7c-b208-650247322757` | lesson_key=`context-pack-rescope` | event_sha256=`2ba13367254bbdb29a1d90a028598c43cfcff6bbb5d475d50ff8ba92c602f4c2`
- #10: `2e6cc6f1-8e99-4b35-bbf9-1ad86a75b201` | 2026-07-28T00:58:30.000Z | GATE/integration_gate_host_limited | incident=`2e6cc6f1-8e99-4b35-bbf9-1ad86a75b202` | lesson_key=`integration-gate-host-boundary` | event_sha256=`eabba4575d65433a316594e7c6b7d509424b17a80f43be352c35ac8b4e162a5e`
- #11: `dd0b9df6-310a-4109-8728-750721fda327` | 2026-07-28T03:04:32.392Z | STATE_CHANGE/context_rescope_required | incident=`71b314a3-84ce-4386-b70c-8f329969f86e` | lesson_key=`context-pack-rescope` | event_sha256=`9cbb75c72069d1db85727cdcdc752357496c38efd07d1d976b8c80d2d4f93711`
- #12: `56648cc3-3533-4d67-b906-0ea156bea43b` | 2026-07-28T03:04:32.397Z | STATE_CHANGE/context_rescoped | incident=`fc1420c3-8f8f-4a6b-9d11-be8a17a5d785` | lesson_key=`context-pack-rescope` | event_sha256=`6330c20f26f2a696a2bcd9d4a6d67dec0bd56a65caf39b7b365e14686e5045d2`
- #13: `3f6bbf6f-eefa-4f22-ae6d-a52d5d163b13` | 2026-07-28T03:06:38.000Z | REVIEW/agent_actionable_source_refusal_feedback | incident=`3f6bbf6f-eefa-4f22-ae6d-a52d5d163b14` | lesson_key=`agent-actionable-source-refusal` | event_sha256=`ce841c6936fbdef533c7b6947bafca2e41f8aa438c9e03af29900e14f0d4f568`
- #14: `c5f74060-d391-4363-9c2c-54c8d285def4` | 2026-07-28T03:21:44.955Z | STATE_CHANGE/context_rescope_required | incident=`760b0bed-367a-48c4-bc88-8e1078c299dd` | lesson_key=`context-pack-rescope` | event_sha256=`76adbf5f92dea89a0d6fcbe6d0eaed7d780710d2b4b013b2b89257d167798abe`
- #15: `d07fc914-8733-46f4-834e-105cdb55ca32` | 2026-07-28T03:21:44.962Z | STATE_CHANGE/context_rescoped | incident=`67034e1b-2ada-4b9f-9673-641ac5526004` | lesson_key=`context-pack-rescope` | event_sha256=`efea11f24b181f823fa15d77008d690ecaf64c27b6d1c649bf23dec7e189f016`
- #16: `d3d0f40b-b2ca-4e90-9b53-1cb01d3207df` | 2026-07-28T03:22:23.000Z | REVIEW/workflow_contract_projection | incident=`0c0dba1a-8ac2-46f6-a27f-7b4c52ad47b8` | lesson_key=`workflow-contract-single-source` | event_sha256=`8a2588d44cd385295c62bca11559c58fb6f139ef022f94e5e6f617cb0f21022c`
- #17: `93a46c91-d0f1-41bb-8fa6-84906dd4df2f` | 2026-07-28T03:30:00.000Z | GATE/darwin_custom_e2e | incident=`f9c1dff0-4a7f-4b7f-9458-f0eb3b7b23bb` | lesson_key=`darwin-custom-e2e` | event_sha256=`469f05f55abc72b07334584bfcdeeda3e480da54bb32967eafedff7dca85ee97`
- #18: `0c7ac1c5-fd08-4de7-8b36-0d40f1d6402b` | 2026-07-28T03:44:27.000Z | GATE/full_release_gate | incident=`ec27f70d-8304-4c7c-91a0-93bb07f501c7` | lesson_key=`full-gate-host-boundary` | event_sha256=`16d11e2e2ef0a98319d48159ef52fdd83ed3676d180360de94bfc067dea3078c`
- #19: `b31aa2f7-bc09-4d68-86fc-7a2bfffc3f09` | 2026-07-28T03:47:47.000Z | GATE/cf3_real_fixture_e2 | incident=`aaf79ec5-518f-48b0-a843-8b0e31cb756e` | lesson_key=`cf3-real-fixture-e2` | event_sha256=`f20bd476dc18c499f492f79a000745f8160b8fbb108420171eb6cac2b56d0ef1`
- #20: `8e3f2a79-bf2c-44b7-9f1f-2f32efc8c2a1` | 2026-07-28T12:10:00.000Z | REVIEW/notebook_binding_abi_reconciled | incident=`b5ad3e44-17f7-43c1-b4ee-93562b6c4b1d` | lesson_key=`notebook-binding-abi-compatibility` | event_sha256=`a97d7278752fa15a142eb2a43edab6ecab661b2eb32e9a3a3bd4b2c961317d11`
- #21: `4d6aa5ef-9b67-4d1f-b5cd-bb0a5cbd1e7a` | 2026-07-28T12:12:00.000Z | GATE/notebook_custom_local_e2e | incident=`f8e51672-dc6c-48c9-8fd0-6d60555a9a24` | lesson_key=`notebook-custom-local-e2e` | event_sha256=`a5491d58798b19a123f1127f121e1717ff9d05e1207a3bd23b14219030070522`
- #22: `d1f5c4ba-1dc1-48c3-a369-cb9dc22b6e6d` | 2026-07-28T06:21:48.000Z | GATE/full_release_gate_host_limited | incident=`d1f5c4ba-1dc1-48c3-a369-cb9dc22b6e6e` | lesson_key=`full-gate-host-limited` | event_sha256=`c678ca0e5b4e5b5e6c72ba770190c5c7cbc4c19eb62ca9498f0267e86b886d1e`
- #23: `010890f5-b97d-478a-8402-cabbb8449ecd` | 2026-07-28T08:49:05.000Z | REVIEW/dependency_scope_type_corrected | incident=`2d51d2a6-e542-4dad-88a8-504ebbcbc21c` | lesson_key=`dependency-scope-category` | event_sha256=`3fc06ad655d728a35d8c018db6fc559d340ac7e7b65916bb33d1bdb22630f28b`
- #24: `853c6453-299b-4316-bc2f-66c854e2bd92` | 2026-07-28T08:58:45.000Z | GAP/formal_scope_narrowing_constraint | incident=`813078a8-7e7e-45d9-a6e8-941aa1dc6345` | lesson_key=`formal-scope-narrowing` | event_sha256=`648e5221875f54699ee11a3ce9ef82061975614f54ebd3bb55e620858fb19f62`
- #25: `378cf400-7c41-47f6-8711-c42c0f797d6a` | 2026-07-28T08:58:45.000Z | GATE/real_dependency_readonly_e2e | incident=`443792ce-4649-43fc-b6db-4d9d9b03ccbb` | lesson_key=`real-dependency-gateway-e2e` | event_sha256=`c83b36e303d8e783ba0076264e15100b21428ffa08802b442c12c943d9e2d21f`
- #26: `67bdc061-c880-407f-baee-9afaa4277e00` | 2026-07-28T08:58:45.000Z | GATE/deployment_authority_bootstrap | incident=`f3b8225d-95bc-49cb-adc0-350f5fbbfd9b` | lesson_key=`deployment-authority-bootstrap` | event_sha256=`ff5273bc0337c668cea2ad9ab72b95247e97d18504f9dc7e7d05b8633a5de311`
- #27: `a6e573b3-3609-434a-a693-0e7f9c0dffc7` | 2026-07-28T09:02:33.000Z | GATE/browser_acceptance_tool_limited | incident=`72eb8f36-be9d-4255-adfd-ddda6c092dcf` | lesson_key=`browser-tool-not-product-evidence` | event_sha256=`f8c8a8fa009c9f59ef7aeace3dffdbc02eee9906a559a0bd3b067ca5b46bfd48`
- #28: `05f98891-9509-4076-b28e-b98116850806` | 2026-07-28T09:15:24.000Z | GATE/full_release_gate_host_limited_reconfirmed | incident=`9b8cd4f1-22ae-4aa4-8733-a1178994239c` | lesson_key=`full-gate-host-limited-reconfirmed` | event_sha256=`9ceab69719fa55d84939ab4ca86abf0474f306b37f53dffb2f423e3426c559b9`
- #29: `e34d268f-29c3-4951-9250-ccca460340f6` | 2026-07-28T09:28:55.000Z | GATE/full_release_gate_host_passed | incident=`59a93289-a949-43d0-b0b9-da3300466acf` | lesson_key=`host-full-gate-evidence` | event_sha256=`6df70c106d19483e6aa8736b425ba731dd24d3a0b80d1d6080008b23cf11df02`
- #30: `89d1d8cf-d589-43bf-91ca-b520b5494afc` | 2026-07-28T09:58:45.000Z | GATE/local_scanner_and_browser_flow | incident=`02eb34d8-cc7f-4ce5-b18b-a7e4cd58236a` | lesson_key=`local-experimental-scanner-and-browser-evidence` | event_sha256=`07431cd10d26f5d681d977393f69a83de326d202c3e2424f81b421246cedb620`
- #31: `bd63e94b-9604-4c30-b8ed-f68846b35889` | 2026-07-28T10:04:31.000Z | GATE/pinned_local_scanner_worker | incident=`ce0c8a87-7a57-4b33-ae4a-956d4f5ec145` | lesson_key=`pinned-local-scanner-worker-bridge` | event_sha256=`6af44dc04f9e3d03f929234dc959b47acec8070b813fe7cee2cacde6aabb0a1d`
- #32: `a732dbcf-0f24-43de-b5c0-c60f2e207d87` | 2026-07-28T11:17:25.000Z | GATE/frontend_mount_race_resolved | incident=`16623e2e-82d5-42f1-b75b-0cd65101572f` | lesson_key=`route-settings-initial-effect-race` | event_sha256=`57210903d0fcbd2bc9d9c5dabc605c41e6dacae231b79cc4c2b6265e13f57233`
- #33: `df7b5814-536f-4aaa-8f72-66bcc787399f` | 2026-07-28T11:17:45.052Z | STATE_CHANGE/context_rescope_required | incident=`43582188-b337-4466-b588-00048d8f47d0` | lesson_key=`context-pack-rescope` | event_sha256=`a8882895963c0e9ff3e3b47258e8d6fac42cbff5ac34fded21112c491a22e38d`
- #34: `dd60e242-e2c0-4152-a822-0ae20f7ca130` | 2026-07-28T11:17:45.067Z | STATE_CHANGE/context_rescoped | incident=`1b270a3e-a07f-4b82-ab1e-757cce039a90` | lesson_key=`context-pack-rescope` | event_sha256=`c9a4308bdf5c37a4ff6b96d43f4e057df9ba16d530814ee9d8bb52cc9def9de9`
- #35: `9073eb9f-4de7-4c4b-ad29-8923c74cdea2` | 2026-07-28T11:19:31.614Z | STATE_CHANGE/context_rescope_required | incident=`971583b1-d243-4da2-90ef-23709201a30e` | lesson_key=`context-pack-rescope` | event_sha256=`f626d57bea4caf3f614315a30e4d2edb1566677e04a13c6b7294b437604b2f23`
- #36: `490ec3fe-9109-4639-998c-e12124df0365` | 2026-07-28T11:19:31.630Z | STATE_CHANGE/context_rescoped | incident=`812edeff-8437-45d3-bb16-7b1b2b3635a4` | lesson_key=`context-pack-rescope` | event_sha256=`338514eaa70c8e49d765f7690c636b96e9dbbaaba34cd8e5a5896e367a6c5041`
- #37: `7bad13ee-29b4-4d6f-93f9-50bb57172914` | 2026-07-28T11:20:57.000Z | GATE/local_osv_scanner_live_response | incident=`b7bcce0e-30c4-429f-a90e-b5e7b536be09` | lesson_key=`metadata-only-live-osv-probe` | event_sha256=`8811144c01e2a2b904bd245f4c7a6d6a669bac69d5c5e3493336a6a18f7711fe`
- #38: `c4d3bf7e-9e2d-4d68-9674-1e2cdcf4b00f` | 2026-07-28T11:33:03.000Z | GATE/host_full_gate_passed_after_local_scanner | incident=`dc2e7775-72df-4b58-a1df-22d452e71d77` | lesson_key=`post-scanner-host-full-gate-evidence` | event_sha256=`2f5bd0d12bbcc5f6cdcf8aac969811b4f1ba03624221203db2ba7aa5a107b4c8`
- #39: `7ec1f7ea-a94c-44d7-884a-01a06bdebf34` | 2026-07-28T11:57:00.799Z | STATE_CHANGE/context_rescope_required | incident=`221ef6f2-4644-4027-8896-7cf708e8ed7d` | lesson_key=`context-pack-rescope` | event_sha256=`446c09ef0756060e867994bc4141b08c4561d1ce5c354d0da010b193031be9f3`
- #40: `4eb3bf87-fb8b-4880-9371-0fadb56514cc` | 2026-07-28T11:57:00.817Z | STATE_CHANGE/context_rescoped | incident=`571afb31-f83d-4c33-abde-34003b34b2f2` | lesson_key=`context-pack-rescope` | event_sha256=`069565eb01769115c76ff2a3ce716c42ec633376af069f42b638b7bed34d516c`
- #41: `d3fb93b5-5bc4-4d7e-b768-5c2992be27dd` | 2026-07-28T11:58:36.000Z | GATE/darwin_model_custom_release_e2e | incident=`5b1a586d-46b9-43ca-a111-2f8eb0a9e507` | lesson_key=`real-host-darwin-release-e2e` | event_sha256=`c4165b1ebaa2cf30696380c78dd85a517e6ca615e8fef8d540064048ecba8ddc`
- #42: `8d048aea-2d92-4a98-b1ca-7830d1c13acd` | 2026-07-28T12:09:54.000Z | GATE/v183_release_candidate_full_gate_passed | incident=`cbb7a83c-e5e3-4250-8a21-df59e3b76372` | lesson_key=`final-staged-candidate-full-gate` | event_sha256=`248c988f9e14fa3f6b1519fbd9211d7c4aefb1d8357d59ebe00ea2e36839fb7b`
- #43: `caf5a6d4-7045-46b2-9034-753d8a2f3d9b` | 2026-07-28T12:11:00.000Z | STATE_CHANGE/v183_local_design_scope_completed | incident=`dfd73b19-4510-49a8-868b-c581bcd7c8ca` | lesson_key=`local-scope-completion-with-deployment-boundaries` | event_sha256=`f0c8a2d9f0d1d427821fda3483592f383dfc549f3b58056fc4601d854da05134`
