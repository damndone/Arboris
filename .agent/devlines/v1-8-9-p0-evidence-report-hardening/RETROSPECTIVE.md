# Retrospective — v1-8-9-p0-evidence-report-hardening

## Goal

# Workbench v1.8.9 P0 Evidence and Report Hardening Objective  Close the real consumer-boundary gaps between persisted workflow artifacts, EvidenceEnvelope/EvidenceCommitBinding, and the Report UI.  Required outcomes:  - an indexed post-estimation artifact without a committed canonical evidence   binding cannot create citable Report facts; it must render as   \`UNAVAILABLE\`/\`BLOCKED\` with a typed reason; - the actual ReportView path must receive and render the typed evidence   projection, including status, envelope digest, provenance and bounded facts; - no raw JSON fallback or recursive scalar extraction may bypass evidence   status, digest, or admission checks; - Agent, Notebook, and Report must preserve the same fact identity/value for a   committed envelope; - tests must prove both the accepted committed path and the rejected   uncommitted/tampered path.  This line owns the run/report evidence loading and Report consumer paths plus their tests. It does not modify Agent/Notebook routing, provider execution, model estimators, or release sidecars. Browser/provider/full-host-gate acceptance remains separate.

## Final status

COMPLETED

## Metrics

- Failure frequency: 8/30 (26.7%; 26.7 per 100 events)
- Repeat rate: 0/8 (0.0%)
- Recurrence rate: 0/8 (0.0%)
- MTTR: median=0 ms (sample=4; unresolved=4)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/14 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- #3 2026-08-19T17:01:00.000Z `preexisting_host_authority`; cause_status: `external`; cause: The existing post-estimation compatibility run failed before the Report route assertion because the protected Agent workflow host-authority resolver is not configured.; resolution: `accepted`; lesson: Keep Agent host-authority failures separate from the Report consumer gate and use an isolated route probe for this line.
- #4 2026-08-19T17:02:00.000Z `formal_event_validation_retry`; cause_status: `known`; cause: The first TDD red gate event draft used an unsupported preventability value and was rejected by the formal CLI before being corrected and appended.; resolution: `resolved`; lesson: Validate formal event enum values before invoking the append control.
- #5 2026-08-19T17:04:00.000Z `preexisting_api_admission`; cause_status: `external`; cause: The broader API compatibility suite could not materialize its completed-run report artifacts because the host-owned workflow admission receipt is unavailable.; resolution: `accepted`; lesson: Use focused route probes when the broader API fixture depends on an unavailable host admission receipt.
- #12 2026-08-19T17:36:00.000Z `formal_verify_stale_retrospective`; cause_status: `known`; cause: Formal verify observed that the completed retrospective had not yet been regenerated after the new TDD red event was appended.; resolution: `mitigated`; lesson: Regenerate the formal retrospective immediately after appending post-closeout evidence before running final verification.
- #16 2026-08-19T18:00:00.000Z `owner_capability_fixture_mismatch`; cause_status: `known`; cause: After removing the report-local fake persistence ports, the existing canonical indexed tests still supplied a C1 fixture without a C0 owner capability and failed closed at the required content-hash gate.; resolution: `not_applicable`; lesson: Canonical Report probes must exercise the same C0 owner capability as production rather than pass a detached consumer fixture.
- #17 2026-08-19T17:59:30.000Z `content_hash_alias_probe_failure`; cause_status: `known`; cause: The first real C0 owner probe reached production persistence but exposed an inconsistent pair of content-hash aliases: evidence_content_hash remained canonical while content_hash was tampered.; resolution: `resolved`; lesson: All index aliases for an authoritative identity must agree before a persistence capability is called.
- #18 2026-08-19T18:02:00.000Z `route_owner_setup_failure`; cause_status: `known`; cause: The first route-level owner injection probe passed a non-existent persistence root to EvidencePacketStoreV1.admit, which correctly rejected the root before the route could run.; resolution: `resolved`; lesson: Owner-side persistence probes must materialize the admitted root before constructing the immutable store capability.
- #27 2026-08-19T18:55:40.000Z `route_identity_seam_regression`; cause_status: `known`; cause: The first final backend gate started while the route still used the pre-hardening run-only current_report_evidence_persistence call, so the HTTP typed-failure probe raised TypeError before reaching the fail-closed projection.; resolution: `resolved`; lesson: After tightening an owner-capability selector, rerun the real HTTP route probe immediately rather than relying on an earlier in-flight test process.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `fail-closed-content-hash-aliases`: occurrences=1; cause_status: `known`; root cause: The first real C0 owner probe reached production persistence but exposed an inconsistent pair of content-hash aliases: evidence_content_hash remained canonical while content_hash was tampered.; solution: `resolved`
- `formal-retrospective-after-append`: occurrences=1; cause_status: `known`; root cause: Formal verify observed that the completed retrospective had not yet been regenerated after the new TDD red event was appended.; solution: `mitigated`
- `owner-store-root-precondition`: occurrences=1; cause_status: `known`; root cause: The first route-level owner injection probe passed a non-existent persistence root to EvidencePacketStoreV1.admit, which correctly rejected the root before the route could run.; solution: `resolved`
- `report-tests-use-c0-owner-capability`: occurrences=1; cause_status: `known`; root cause: After removing the report-local fake persistence ports, the existing canonical indexed tests still supplied a C1 fixture without a C0 owner capability and failed closed at the required content-hash gate.; solution: `not_applicable`
- `route-identity-seam-regression`: occurrences=1; cause_status: `known`; root cause: The first final backend gate started while the route still used the pre-hardening run-only current_report_evidence_persistence call, so the HTTP typed-failure probe raised TypeError before reaching the fail-closed projection.; solution: `resolved`
- `separate-agent-host-authority-failure`: occurrences=1; cause_status: `external`; root cause: The existing post-estimation compatibility run failed before the Report route assertion because the protected Agent workflow host-authority resolver is not configured.; solution: `accepted`
- `separate-api-admission-failure`: occurrences=1; cause_status: `external`; root cause: The broader API compatibility suite could not materialize its completed-run report artifacts because the host-owned workflow admission receipt is unavailable.; solution: `accepted`
- `validate-formal-event-enums`: occurrences=1; cause_status: `known`; root cause: The first TDD red gate event draft used an unsupported preventability value and was rejected by the formal CLI before being corrected and appended.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `fail-closed-content-hash-aliases`: line experience occurrence(s)=1
- `formal-retrospective-after-append`: line experience occurrence(s)=1
- `owner-store-root-precondition`: line experience occurrence(s)=1
- `report-tests-use-c0-owner-capability`: line experience occurrence(s)=1
- `route-identity-seam-regression`: line experience occurrence(s)=1
- `separate-agent-host-authority-failure`: line experience occurrence(s)=1
- `separate-api-admission-failure`: line experience occurrence(s)=1
- `validate-formal-event-enums`: line experience occurrence(s)=1

## Future guidance

- After tightening an owner-capability selector, rerun the real HTTP route probe immediately rather than relying on an earlier in-flight test process.
- All index aliases for an authoritative identity must agree before a persistence capability is called.
- Canonical Report probes must exercise the same C0 owner capability as production rather than pass a detached consumer fixture.
- Keep Agent host-authority failures separate from the Report consumer gate and use an isolated route probe for this line.
- Owner-side persistence probes must materialize the admitted root before constructing the immutable store capability.
- Regenerate the formal retrospective immediately after appending post-closeout evidence before running final verification.
- Use focused route probes when the broader API fixture depends on an unavailable host admission receipt.
- Validate formal event enum values before invoking the append control.

## Event index

- #1: `4d4470c0-5786-414e-bfa6-9ed9c056a9fe` | 2026-08-19T16:34:43.586Z | STATE_CHANGE/line_started | incident=`ad4126bd-d9c4-4939-9b43-f3c6c602b59b` | lesson_key=`frozen-context-before-start` | event_sha256=`54b27b5ba090210619b4dea7929898a22befe6d604842036a6fe60b10cd8dc0e`
- #2: `55d848f3-0ad1-4b28-8d3d-5e2be9e2915b` | 2026-08-19T16:52:00.000Z | GATE/tdd_red | incident=`9cd71950-19d3-4c36-93b3-0bde0c690d77` | lesson_key=`tdd-red-before-implementation` | event_sha256=`29dfa363d880bcbb42494351e2f7089f20aab358ec77f56c849874d1a069e83f`
- #3: `2f6e0f16-5eef-4e38-b5f4-2a3fcdad57bf` | 2026-08-19T17:01:00.000Z | ERROR/preexisting_host_authority | incident=`7ee2d830-5d8f-4ee4-87e1-4071e118c99f` | lesson_key=`separate-agent-host-authority-failure` | event_sha256=`ab706e1a59ec8ece6620bbfa617b0541fa867274aa228166e66e69f6b6f3f6e2`
- #4: `8e7c7d9e-8e20-4f74-b3a0-e1542e0e53a8` | 2026-08-19T17:02:00.000Z | ERROR/formal_event_validation_retry | incident=`c9458024-0c33-45ef-b6dc-0d27eefdd950` | lesson_key=`validate-formal-event-enums` | event_sha256=`c80e7538c063a898a129ba89420f4c7cf425267e6e8cfe132c710e397778f063`
- #5: `e4b00c49-19b3-4d24-aed7-5ce86ab7a613` | 2026-08-19T17:04:00.000Z | ERROR/preexisting_api_admission | incident=`6ecfce9d-0e70-4b95-90d9-9a2e65b82f20` | lesson_key=`separate-api-admission-failure` | event_sha256=`f42126c3dadf6ce8e6017a4a47b390990eb5a103799a262393a25ded51f819ff`
- #6: `c745b744-c195-45d7-bd43-6d66b20a8b19` | 2026-08-19T17:06:00.000Z | GATE/report_boundary_backend | incident=`e9c6cc2d-fc2f-4dba-9e23-d8f09d0e7bc3` | lesson_key=`backend-report-boundary-green` | event_sha256=`66d81f70ea968a3bbd2f8f6f18a7029857eeb81d64f531288fb0c0adc4b72d8c`
- #7: `6f3a4e68-660f-45da-b5ef-5aa9ec0e0f2a` | 2026-08-19T17:06:10.000Z | GATE/report_boundary_frontend | incident=`e0a994ef-6bb1-48d1-a61a-3f6fc25388df` | lesson_key=`frontend-report-boundary-green` | event_sha256=`3fc0e291acd313fe02100598ce45349a61ebef0916d2421764135adef46ef03f`
- #8: `f6d4cbd7-5ff4-4cc2-b7bf-9e1cf8de373a` | 2026-08-19T17:06:20.000Z | GATE/frontend_typecheck | incident=`4b5d45c6-480e-4c98-9825-3a7c22414a1c` | lesson_key=`frontend-typecheck-separate-browser` | event_sha256=`d61e6c5404936ebfbfeaba54860c271ab4f16fa545fbd2609b175b1792f3bece`
- #9: `d84e986a-2d3d-4011-a5e9-37dbd85ee968` | 2026-08-19T17:08:00.000Z | STATE_CHANGE/implementation_verified | incident=`d67651d8-b1e8-4135-ad5b-a43124b964c6` | lesson_key=`report-boundary-implementation-verified` | event_sha256=`87a348d11f05722166c7ff674115081126e88075e6fcfd9089df3d9c7307fdcf`
- #10: `9d8be3e7-82e6-44dc-8cf0-bbf1b6bc7b12` | 2026-08-19T17:12:00.000Z | STATE_CHANGE/line_completed | incident=`46d65aed-6cba-40d0-93da-4e753caef2b7` | lesson_key=`close-with-evidence-and-deferred-gates` | event_sha256=`b9fe97935143dd24c615fad0f946f9e608401b7a93993805d7a852caab424d80`
- #11: `c3c7b4ba-1a37-4ba6-a568-6c6d67b2e2c9` | 2026-08-19T17:30:08.000Z | GATE/tdd_red | incident=`2dd1c02a-e83e-4dd3-835c-a9ec17c43f6a` | lesson_key=`tdd-red-foreign-artifact-bundle` | event_sha256=`a8e5eb84e81b7fdf47bcf27d901bcf5424ab4219765ed27a5c0f39117c638d9b`
- #12: `c7b69c57-a1e0-4ee0-a601-c4a3dfc4c5f4` | 2026-08-19T17:36:00.000Z | ERROR/formal_verify_stale_retrospective | incident=`0c97b43b-86e9-4a9a-82b2-68d3b11df4da` | lesson_key=`formal-retrospective-after-append` | event_sha256=`c09c56d62f65d64ed731449652eb4c457a15d39584255d984cf6f6a6a97cf009`
- #13: `8e7a3bd2-c8d4-4b7f-b0a3-56f322f7561e` | 2026-08-19T17:50:00.000Z | GATE/tdd_red_authoritative_registry | incident=`1f5bf047-75a4-42ce-ab8d-5f91ed03d7f2` | lesson_key=`authoritative-registry-before-report-facts` | event_sha256=`ea9fdb2a9334985a5e860ee66df7ac30ac5c0a506b10039eb68731e8b888c728`
- #14: `45230fe7-f434-478a-af6d-ed1d0cb9ad4c` | 2026-08-19T17:41:20.480Z | STATE_CHANGE/context_rescope_required | incident=`13f54121-3a6b-4039-bf3d-e8646ebe4c5d` | lesson_key=`context-pack-rescope` | event_sha256=`3e8242cc2b8f7d8e7aa596bfe345b64dbe9128ecd7f64c5a306db1ed1b8fd143`
- #15: `c73021b4-0a97-4476-b18e-299d6600f3df` | 2026-08-19T17:41:20.487Z | STATE_CHANGE/context_rescoped | incident=`14d066e1-f44e-4902-92fb-033094c8073c` | lesson_key=`context-pack-rescope` | event_sha256=`ed9ad34b3971ab2c41f29ec72c1f787c5f515840ce9476dd00f0670797f0c94f`
- #16: `b9d7ac7e-5d62-4e92-83d7-7fc42c4905ac` | 2026-08-19T18:00:00.000Z | ERROR/owner_capability_fixture_mismatch | incident=`0c3bfe33-a476-4c4f-a39e-1572cf7012ee` | lesson_key=`report-tests-use-c0-owner-capability` | event_sha256=`32eb2b612196caad21fbe69821cc4e902b058d77bb816974213f9bd35207acd3`
- #17: `5c82c04f-fdb3-4bce-94c5-6de59fcaa2d1` | 2026-08-19T17:59:30.000Z | ERROR/content_hash_alias_probe_failure | incident=`c587f731-51e3-4d6e-9c8a-bdbfcd2c037a` | lesson_key=`fail-closed-content-hash-aliases` | event_sha256=`c2a51190282a4f00f3255d88b9227d9226980a486006b8ee6ef5ac2ba2836d2f`
- #18: `0f710e97-640e-49d4-92d4-9aa86c4a7379` | 2026-08-19T18:02:00.000Z | ERROR/route_owner_setup_failure | incident=`0a2a54c3-1e2f-4cab-85ac-af2b6a10d7b2` | lesson_key=`owner-store-root-precondition` | event_sha256=`54beec6da81924e37fc022fec8d7043f485f0d2133400601be57f8f1d9b47cbf`
- #19: `2a8f947d-4db1-488d-8aca-6d5c045a3aa6` | 2026-08-19T18:03:45.000Z | GATE/report_authoritative_registry_green | incident=`a0b5db92-7d1a-4d46-a72d-4efac6f2905b` | lesson_key=`authoritative-report-persistence-green` | event_sha256=`3adf7c2e0e19db10754b8fd966369e407c67ef6c7f129b39e2df5a363be01653`
- #20: `f82d9d4b-4e7d-4c3c-bb0d-e82bc73fdc38` | 2026-08-19T18:03:50.000Z | GATE/report_boundary_frontend_final | incident=`2ea3fe37-ecc6-4013-b65e-e49db6c4ea4e` | lesson_key=`frontend-typed-evidence-green` | event_sha256=`487551aecfc8e615bd3eaa31fb0d5f009f8ea3853dc2115296af3599aff38488`
- #21: `5f1c9fe5-07a8-46f8-88e1-33b66e65782c` | 2026-08-19T18:03:55.000Z | GATE/report_static_gates_final | incident=`a60a2bee-d397-4a08-a6ab-7bcb62e83a63` | lesson_key=`report-static-gates-green` | event_sha256=`0615d4e8e1d166f8732d323e82fea552d382d9bbad26b1984c23d234a4047714`
- #22: `cb3e2f1c-5276-42a2-aa55-77f8f8c1fda1` | 2026-08-19T18:05:52.000Z | GATE/formal_verify_final | incident=`acb56290-b579-4f57-82af-2de8199473e8` | lesson_key=`formal-final-verify-green` | event_sha256=`e767e527562367ee3d726d2f3f13889363e68284e5240dd6c4bce8afcbbfb031`
- #23: `2152c23e-b109-4aac-8fc0-6b5119be2002` | 2026-08-19T18:38:54.000Z | GATE/tdd_red_second_round | incident=`e5325584-5d79-4070-adb6-efd6202c7c51` | lesson_key=`tdd-red-second-round-evidence-report` | event_sha256=`33c2273068a0f8c7de12693f54cbc4c99e62eecccac2ff3c3534e1432d6edd08`
- #24: `fc14466e-aae6-48fd-8e0e-32d52d590cfd` | 2026-08-19T18:43:48.650Z | STATE_CHANGE/context_rescope_required | incident=`d693e33a-d2a0-48e6-8b87-60bb80277d17` | lesson_key=`context-pack-rescope` | event_sha256=`a0299f84b6fb91ef57f58198046b86a7bbef32c892e8aa6dca13cef45cd6a83e`
- #25: `fd7ab24b-81b5-4909-9049-b85810aafa33` | 2026-08-19T18:43:48.661Z | STATE_CHANGE/context_rescoped | incident=`1ada45b0-c38f-4330-b339-136c123a4662` | lesson_key=`context-pack-rescope` | event_sha256=`cef394e5218abe047d76f412682a142db3244d6ee7cca89abb2dceef57cf1804`
- #26: `11bc3b06-7558-41ef-a43f-3702968353c8` | 2026-08-19T18:52:45.000Z | GATE/report_hardening_green | incident=`4d8437f9-3d44-4ca4-9a96-da959b82784b` | lesson_key=`report-hardening-green` | event_sha256=`5f9c60f8d72f84acb10335504108d5e9480f851483dff782e39f92dd329e5fda`
- #27: `6c2f3c56-6ca2-4e0b-bf93-1c4dcf7b7225` | 2026-08-19T18:55:40.000Z | ERROR/route_identity_seam_regression | incident=`0b43c5aa-c86a-4fd5-b0cb-792c7c05e9b1` | lesson_key=`route-identity-seam-regression` | event_sha256=`10b1535f235681be1e473f3cb71ecb095d6dfef9c623fb4a58f1c0b72419808d`
- #28: `fae7c979-5a4c-46b6-9223-ff952220d685` | 2026-08-19T18:56:11.000Z | GATE/report_static_gates_green | incident=`86b93edd-2903-4fe5-8b9f-68b87b35e616` | lesson_key=`scoped-gates-separate` | event_sha256=`1ec34ac0854f74b5c01687f2c7abbe7508d443b234cac293ad77fe788da880d2`
- #29: `e3dfcb11-7722-45c0-8840-4bf70c54254f` | 2026-08-19T18:56:19.000Z | GATE/report_hardening_final_gate | incident=`ba6fd4c8-104c-4b5a-bd72-5f49010763b7` | lesson_key=`report-hardening-final-gate` | event_sha256=`852270c84cacfd9d8335a161da5157cc5773524714874c4c4bfbe4922afda4dc`
- #30: `824db8c5-dade-486b-9562-c893cab40c02` | 2026-08-19T18:56:40.000Z | STATE_CHANGE/report_hardening_completed | incident=`e91149e7-0f40-41f1-8660-d992dbc3bc55` | lesson_key=`report-hardening-complete` | event_sha256=`91bacf390c4ead5ff25fd459dc07a86e313cb60b4b238064d004de0d0bd1ecc2`
