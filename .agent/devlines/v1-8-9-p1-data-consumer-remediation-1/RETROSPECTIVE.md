# Retrospective — v1-8-9-p1-data-consumer-remediation-1

## Goal

# Objective: Workbench v1.8.9 P1 Data Consumer Remediation 1  ## Exact baseline  This fresh implementation line starts from the target worktree product tip \`4fe3a827db586733f87a161029bd3cae0c1c8fc2\`. Prior formal lines, their Context Packs, events, retrospectives, handoffs, and commits are historical evidence only and must not be edited.  ## Required remediation  Close the independently reviewed P1-A through P1-C and P2-D through P2-F data-consumer defects within the package-local consumer boundary:  - Separate dependency installation presence from verified import/operation   admission. A real import or minimal verified adapter failure for pyarrow or   pyreadstat must produce typed \`optional_dependency\`/\`unavailable\` results;   capability discovery, writer, read, read-back, and manifest/admission paths   must fail closed without fallback or a bare \`ModuleNotFoundError\`. - Route bounded Parquet reads in \`data_operations.py\` through the same verified   Parquet engine admission as interchange, passing the admitted engine where   the pandas contract permits it. - Before any raw snapshot copy/write, verify run-root containment, reject   symlink/non-regular/identity hazards, and preserve typed fail-closed errors   with zero out-of-root side effects. - Make \`MetadataRegistryV1\` server-owned metadata deeply immutable or deeply   copied while retaining compatible serialization. - Reject malformed non-Mapping column metadata with a typed invalid/unavailable   or metadata-loss result; never silently drop it or report verified loss-free   interchange. - Require value, schema, and dtype agreement for \`verified\` round-trips;   mismatches must be represented as schema mismatch or metadata loss rather   than being hidden behind \`value_equal\`.  ## TDD evidence required  Add and retain minimal RED/GREEN regression tests for broken imports, unavailable Parquet bypass, symlink pre-write zero side effect, nested metadata mutation, malformed column metadata, and dtype/schema mismatch. Preserve the normal CSV/XLSX/Parquet round-trip contracts and typed fastparquet/neither and pyreadstat-unavailable outcomes.  ## Scope and boundaries  Only package-local Data Consumer implementation, its focused tests, objective and final handoff, and formal development-line files are in scope. Do not modify central Agent/Notebook/Report/cutover code, providers, frontend product code, dependencies, other worktrees, or prior formal lines. Do not install dependencies, sign/broadcast anything, or claim browser/provider/central/ host/full-gate/release acceptance.  ## Verification and known gates  Run exact backend interchange, ingestion, data-operation, editor, route, and manifest tests; direct adversarial probes; frontend focused tests and typecheck; backend compileall; and \`git diff --check\`. Run formal verify and CLI-generated retrospective before closeout. Browser acceptance, provider integration, central Agent/Notebook/Report integration, host gate, full gate, merge, tag, and release remain \`NOT VERIFIED\` unless separately evidenced.

## Final status

COMPLETED

## Metrics

- Failure frequency: 10/30 (33.3%; 33.3 per 100 events)
- Repeat rate: 0/10 (0.0%)
- Recurrence rate: 0/10 (0.0%)
- MTTR: median=1740000 ms (sample=10; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/16 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #4 2026-08-20T03:56:00.000Z `p1a_broken_optional_import_red`; cause_status: `known`; cause: The RED probes simulated installed-but-unimportable pyarrow and pyreadstat; the baseline admitted both from find_spec and the live manifest also advertised native interchange.; resolution: `open`; lesson: Optional dependency presence is not executable admission; import and operation probes must guard every consumer surface.
- #5 2026-08-20T04:02:00.000Z `p1b_parquet_bypass_red`; cause_status: `known`; cause: The RED probe disabled the shared Parquet engine admission and observed data_operations._read_frame call pandas.read_parquet directly.; resolution: `open`; lesson: Every bounded Parquet consumer must admit and pass the same verified engine before pandas reads the artifact.
- #6 2026-08-20T04:05:00.000Z `p1c_raw_snapshot_symlink_red`; cause_status: `known`; cause: The RED probe replaced run_root/raw_snapshot with a symlink to an external directory; ingest_files copied source bytes there before register_artifact rejected the escaped path.; resolution: `open`; lesson: Containment, symlink, regular-file, and identity checks must complete before the first raw snapshot write.
- #7 2026-08-20T04:09:00.000Z `p2d_nested_metadata_mutation_red`; cause_status: `known`; cause: The RED probe mutated nested caller metadata after MetadataRegistryV1 construction and observed the server-owned registry change with the baseline shallow dict copy.; resolution: `open`; lesson: Frozen dataclass fields do not freeze nested metadata; server-owned projections need recursive ownership and immutability.
- #8 2026-08-20T04:15:00.000Z `p2e_malformed_metadata_red`; cause_status: `known`; cause: The RED probe expected malformed column metadata to fail typed with reason_code metadata_loss, but the baseline silently discarded the non-Mapping value and returned a round-trip result.; resolution: `open`; lesson: Validate every declared column metadata entry before constructing the loss manifest.
- #9 2026-08-20T04:20:00.000Z `p2f_roundtrip_status_red`; cause_status: `known`; cause: The RED probes showed that round_trip_frame returned verified when values matched but dtype/schema differed, and when the explicit metadata loss manifest contained dropped metadata.; resolution: `open`; lesson: Derive round-trip status from value, schema/dtype, and metadata-loss evidence rather than value equality alone.
- #10 2026-08-20T04:25:00.000Z `p1a_ingestion_import_hook_regression`; cause_status: `known`; cause: The focused ingestion suite simulated a broken pyarrow import through builtins.__import__, but the verified adapter reused an already-loaded module through importlib without exercising that import boundary.; resolution: `open`; lesson: Verified optional adapters must exercise the same import boundary used by callers, including already-loaded module paths.
- #11 2026-08-20T04:31:00.000Z `p2d_metadata_serialization_compatibility_red`; cause_status: `known`; cause: Deep-freezing MetadataRegistryV1 with nested MappingProxyType values preserved authority, but downstream data-operation sidecar construction still shallow-copied registry metadata and json serialization rejected mappingproxy values.; resolution: `open`; lesson: Every serialization boundary consuming server-owned metadata must use a recursive thawed compatibility projection.
- #12 2026-08-20T04:31:00.000Z `p1a_manifest_fixture_compatibility_red`; cause_status: `known`; cause: The manifest now used the verified interchange capability message for native optional formats; this changed the live provider contract digests and made the protected built-in provider fixture disagree with the live payload.; resolution: `open`; lesson: Environment-sensitive capability admission must not silently rewrite the protected provider contract fixture; preserve a stable manifest contract while exposing live unavailable status.
- #24 2026-08-20T04:30:07.000Z `p1c_raw_snapshot_atomicity_boundary_red`; cause_status: `known`; cause: The initial pre-write containment fix did not yet remove a target created by a partial copy or a raised register_artifact call, and it did not compare the source fingerprint after copy.; resolution: `open`; lesson: A pre-write containment check is not sufficient: a snapshot writer must clean up only its own target on copy/register failure and verify the source fingerprint after copy.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `bounded-reader-engine-parity`: occurrences=1; cause_status: `known`; root cause: The RED probe disabled the shared Parquet engine admission and observed data_operations._read_frame call pandas.read_parquet directly.; solution: `open`
- `deep-metadata-authority`: occurrences=1; cause_status: `known`; root cause: The RED probe mutated nested caller metadata after MetadataRegistryV1 construction and observed the server-owned registry change with the baseline shallow dict copy.; solution: `open`
- `deep-metadata-serialization`: occurrences=1; cause_status: `known`; root cause: Deep-freezing MetadataRegistryV1 with nested MappingProxyType values preserved authority, but downstream data-operation sidecar construction still shallow-copied registry metadata and json serialization rejected mappingproxy values.; solution: `open`
- `fail-closed-admission`: occurrences=1; cause_status: `known`; root cause: The RED probes simulated installed-but-unimportable pyarrow and pyreadstat; the baseline admitted both from find_spec and the live manifest also advertised native interchange.; solution: `open`
- `metadata-loss-truth`: occurrences=1; cause_status: `known`; root cause: The RED probe expected malformed column metadata to fail typed with reason_code metadata_loss, but the baseline silently discarded the non-Mapping value and returned a round-trip result.; solution: `open`
- `pre-write-containment`: occurrences=1; cause_status: `known`; root cause: The RED probe replaced run_root/raw_snapshot with a symlink to an external directory; ingest_files copied source bytes there before register_artifact rejected the escaped path.; solution: `open`
- `raw-snapshot-copy-register-atomicity`: occurrences=1; cause_status: `known`; root cause: The initial pre-write containment fix did not yet remove a target created by a partial copy or a raised register_artifact call, and it did not compare the source fingerprint after copy.; solution: `open`
- `roundtrip-verification-status`: occurrences=1; cause_status: `known`; root cause: The RED probes showed that round_trip_frame returned verified when values matched but dtype/schema differed, and when the explicit metadata loss manifest contained dropped metadata.; solution: `open`
- `stable-manifest-compatibility`: occurrences=1; cause_status: `known`; root cause: The manifest now used the verified interchange capability message for native optional formats; this changed the live provider contract digests and made the protected built-in provider fixture disagree with the live payload.; solution: `open`
- `verified-import-boundary`: occurrences=1; cause_status: `known`; root cause: The focused ingestion suite simulated a broken pyarrow import through builtins.__import__, but the verified adapter reused an already-loaded module through importlib without exercising that import boundary.; solution: `open`

## Added tests

- `tests/test_data_operation_routes.py::test_transform_child_reloads_all_confirmed_metadata_and_provenance_sidecar; tests/test_data_operation_routes.py::test_split_group_children_bind_metadata_sidecars_and_reload_profile; tests/test_data_operation_routes.py::test_rename_child_reloads_expressible_metadata_and_provenance`
- `tests/test_data_operations.py`
- `tests/test_ingestion_metadata.py`
- `tests/test_ingestion_metadata.py::test_parquet_bounded_ingestion_reports_typed_optional_dependency`
- `tests/test_v189_data_interchange.py`
- `tests/test_v189_data_interchange.py::test_malformed_column_metadata_is_typed_and_not_reported_verified`
- `tests/test_v189_data_interchange.py::test_round_trip_status_is_schema_mismatch_when_dtype_differs; tests/test_v189_data_interchange.py::test_round_trip_status_exposes_declared_metadata_loss`
- `tests/test_v189_data_operation_manifest.py::test_builtin_provider_payload_is_c0_shaped_and_matches_repository_fixture`

## New rules

- `bounded-reader-engine-parity`: line experience occurrence(s)=1
- `deep-metadata-authority`: line experience occurrence(s)=1
- `deep-metadata-serialization`: line experience occurrence(s)=1
- `fail-closed-admission`: line experience occurrence(s)=1
- `metadata-loss-truth`: line experience occurrence(s)=1
- `pre-write-containment`: line experience occurrence(s)=1
- `raw-snapshot-copy-register-atomicity`: line experience occurrence(s)=1
- `roundtrip-verification-status`: line experience occurrence(s)=1
- `stable-manifest-compatibility`: line experience occurrence(s)=1
- `verified-import-boundary`: line experience occurrence(s)=1

## Future guidance

- A pre-write containment check is not sufficient: a snapshot writer must clean up only its own target on copy/register failure and verify the source fingerprint after copy.
- Containment, symlink, regular-file, and identity checks must complete before the first raw snapshot write.
- Derive round-trip status from value, schema/dtype, and metadata-loss evidence rather than value equality alone.
- Environment-sensitive capability admission must not silently rewrite the protected provider contract fixture; preserve a stable manifest contract while exposing live unavailable status.
- Every bounded Parquet consumer must admit and pass the same verified engine before pandas reads the artifact.
- Every serialization boundary consuming server-owned metadata must use a recursive thawed compatibility projection.
- Frozen dataclass fields do not freeze nested metadata; server-owned projections need recursive ownership and immutability.
- Optional dependency presence is not executable admission; import and operation probes must guard every consumer surface.
- Validate every declared column metadata entry before constructing the loss manifest.
- Verified optional adapters must exercise the same import boundary used by callers, including already-loaded module paths.

## Event index

- #1: `c6d86503-1450-436e-8984-5340aaf87242` | 2026-08-20T03:48:59.222Z | STATE_CHANGE/line_started | incident=`303c26cd-61cb-41a4-bf6a-0fb6e7fd16ef` | lesson_key=`frozen-context-before-start` | event_sha256=`e9a881e5cca952562090021651f70f9cdf129d23296250f22c611fc857e7e8a7`
- #2: `160ac6df-c07f-4b0d-99d6-d201200401a6` | 2026-08-20T03:53:10.498Z | STATE_CHANGE/context_rescope_required | incident=`dc078c1e-aa78-4485-a091-7eb895120d05` | lesson_key=`context-pack-rescope` | event_sha256=`d387a185a620940a5cc0d0273f5184160f290d9823a338060f9e78e36b0abcc0`
- #3: `e30d014e-4fa9-42e0-bf4a-b54c3708970b` | 2026-08-20T03:53:10.501Z | STATE_CHANGE/context_rescoped | incident=`5ead3622-5d1b-42fc-9e05-f6a02bc805eb` | lesson_key=`context-pack-rescope` | event_sha256=`a4d4252c5772d95fb34c7473d47335856191b169858ea49057b1115518166687`
- #4: `49f7c0a1-1c39-4cfb-bc9f-7d7a4f2b9e31` | 2026-08-20T03:56:00.000Z | FAILURE/p1a_broken_optional_import_red | incident=`0e1c2a3b-4d5e-467f-8a9b-0c1d2e3f4a5b` | lesson_key=`fail-closed-admission` | event_sha256=`734c5abfdfb82e3b27b6cfe7e6aba2829ef41abc30f30c242d0ae325d1f513ab`
- #5: `5a0c4e89-7f1b-4d2e-9c6a-8b3e0f2d1a74` | 2026-08-20T04:02:00.000Z | FAILURE/p1b_parquet_bypass_red | incident=`6b2d4f8a-1c3e-4597-9d0f-7a5c2e1b8f64` | lesson_key=`bounded-reader-engine-parity` | event_sha256=`579559978b2354fd6240b15595ff6d81f7ec733563d9db4d54c9dd5ab85cd1b2`
- #6: `7c1e5a9d-3f62-4b80-8d14-6e9a2c5f7b31` | 2026-08-20T04:05:00.000Z | FAILURE/p1c_raw_snapshot_symlink_red | incident=`8d2f6a1c-4e90-5b73-9a16-c7e2f4b8d0a5` | lesson_key=`pre-write-containment` | event_sha256=`12d3bf147c6e13e7e05a3bb8617f2d73e290a01280119f04b0945977f15587bb`
- #7: `9e4a2c7f-1b6d-4f80-9a53-2c7d8e1f0b4a` | 2026-08-20T04:09:00.000Z | FAILURE/p2d_nested_metadata_mutation_red | incident=`a5c3e7f1-2b4d-4e80-9a63-2c7d8e1f0b5b` | lesson_key=`deep-metadata-authority` | event_sha256=`f320b4dafd5e6eb5da35f84ce51b42a2101067663636a1607554eea47bb9c7bf`
- #8: `c7e1a2f4-9b6d-4e80-8a53-2c7d1f0b4a5e` | 2026-08-20T04:15:00.000Z | FAILURE/p2e_malformed_metadata_red | incident=`4b42d420-5da5-4d69-8d6b-0ce3ea9f9e16` | lesson_key=`metadata-loss-truth` | event_sha256=`aa4ca41ed3ed1f73010315d7b913a16183f5ca91266435dda499831408921e3b`
- #9: `d8f2b4a6-1c7e-4f90-8b53-2a6d9e0c1f4b` | 2026-08-20T04:20:00.000Z | FAILURE/p2f_roundtrip_status_red | incident=`5c8e1a3f-7b4d-4e90-9f26-1d5a7c2b8e04` | lesson_key=`roundtrip-verification-status` | event_sha256=`f55881b5dda5b43e38f0633c99a5eac547059fa6c9329f936ab59617df06baaa`
- #10: `e9a3c5f7-2b6d-4f80-9a14-7c3e1d5b8f02` | 2026-08-20T04:25:00.000Z | FAILURE/p1a_ingestion_import_hook_regression | incident=`6d2f8a1c-4e90-5b73-9c16-7a3e1f5b8d02` | lesson_key=`verified-import-boundary` | event_sha256=`a60215a5403d6a015ced53960509e69698222be00031dd0a03f2680716ae3eaf`
- #11: `f1a3c5e7-9b2d-4e80-8a16-7c3f1d5b9e02` | 2026-08-20T04:31:00.000Z | FAILURE/p2d_metadata_serialization_compatibility_red | incident=`7c2e4a1f-9b5d-4e80-8a36-1f7c3d5b9e02` | lesson_key=`deep-metadata-serialization` | event_sha256=`5286c8706c1f53088a953b4a4e5517eb7851f475621468c17e1a06d2125d2855`
- #12: `a4c6e8f0-2b7d-4f91-8a35-1c7e9d0b5f24` | 2026-08-20T04:31:00.000Z | FAILURE/p1a_manifest_fixture_compatibility_red | incident=`8d3f5b2a-1c7e-4f90-9a36-2b5d8e0c1f47` | lesson_key=`stable-manifest-compatibility` | event_sha256=`a2c1e11e1531738486a58f6ea43016a080bef066a488b0279c387f5b65a6069f`
- #13: `b5d7f9a1-3c8e-4f20-9a46-1d7b5e0c2f83` | 2026-08-20T04:35:00.000Z | GATE/data_consumer_backend_focused_gate | incident=`9e1c5a7f-3b4d-4f80-8a26-1d7e0c5b9f42` | lesson_key=`data-consumer-focused-gate-boundary` | event_sha256=`cc6ec5480cf5a3fc082af269909dae1043df15beadd940dea130e8462d16fa7d`
- #14: `c6e8a1f3-5b7d-4f90-8a24-1d6e0c5b9f42` | 2026-08-20T04:36:00.000Z | GATE/data_consumer_frontend_focused_gate | incident=`7f2a4c1e-9b5d-4e80-8a36-1c7e0d5b9f42` | lesson_key=`frontend-focused-gate-boundary` | event_sha256=`c29f7d4e78307da54c9b855dfefeb5544bf2e831f424fdfd893a4117e36ffd1f`
- #15: `d7f9b1c3-5e8a-4f20-9a46-1c7e0d5b2f83` | 2026-08-20T04:37:00.000Z | GATE/data_consumer_boundary_and_ownership_gate | incident=`8e2c4a1f-7b5d-4f90-9a36-1c7e0d5b2f84` | lesson_key=`ownership-before-closeout` | event_sha256=`78ef4e208c35a41b58099cdd74947122b84210b85ac2fcad4eb519d135045663`
- #16: `e8a2c4f6-1b7d-4f90-9a36-2c5e0d8b1f47` | 2026-08-20T04:40:00.000Z | STATE_CHANGE/line_completed | incident=`9f3b5d7a-1c6e-4f80-8a24-2d7b0e5c1f46` | lesson_key=`close-at-owned-evidence-boundary` | event_sha256=`569fdf937395a31020d63afb7a24957e1beb32cdac1208adb7d514ca8d1b2c9d`
- #17: `f1a3c5e7-9b2d-4e80-8a16-7c3f0d5b9e24` | 2026-08-20T04:41:00.000Z | GATE/remediation_verified_fail_closed_admission | incident=`0e1c2a3b-4d5e-467f-8a9b-0c1d2e3f4a5b` | lesson_key=`fail-closed-admission` | event_sha256=`81d7286b455770e9198b8ad4ed3e085139ef5053cf904e17055dc57fedb6332a`
- #18: `a2c4e6f8-1b7d-4f90-8a35-2c7e0d5b9f16` | 2026-08-20T04:41:00.000Z | GATE/remediation_verified_bounded_reader_engine_parity | incident=`6b2d4f8a-1c3e-4597-9d0f-7a5c2e1b8f64` | lesson_key=`bounded-reader-engine-parity` | event_sha256=`d5ff4d9b3af8ee670934274f6940935969535fc1b47c08117029eac192eb2729`
- #19: `b3d5f7a9-2c8e-4f10-9a46-1d7b0e5c2f83` | 2026-08-20T04:41:00.000Z | GATE/remediation_verified_pre_write_containment | incident=`8d2f6a1c-4e90-5b73-9a16-c7e2f4b8d0a5` | lesson_key=`pre-write-containment` | event_sha256=`09420218290639ee534c9ac775f6f65e631696347e8a840e78bd9975d01d9476`
- #20: `c4e6f8a0-3b9d-4f21-8a57-1c7e0d5b2f94` | 2026-08-20T04:41:00.000Z | GATE/remediation_verified_deep_metadata_authority | incident=`a5c3e7f1-2b4d-4e80-9a63-2c7d8e1f0b5b` | lesson_key=`deep-metadata-authority` | event_sha256=`a5a4fbe349f461fbb64ff0183e102a68f74379702de5e836746d4c058aaaa4e2`
- #21: `d5f7a9b1-4c0e-4f32-8a68-1d7e0c5b2f95` | 2026-08-20T04:41:00.000Z | GATE/remediation_verified_metadata_loss_truth | incident=`4b42d420-5da5-4d69-8d6b-0ce3ea9f9e16` | lesson_key=`metadata-loss-truth` | event_sha256=`00b14fe34a96cb70b801f7bba80d7a0910192f3a25e11da32a40b19d36858277`
- #22: `e6a8b0c2-5d1f-4f43-8a79-1c7e0d5b2f96` | 2026-08-20T04:41:00.000Z | GATE/remediation_verified_roundtrip_status | incident=`5c8e1a3f-7b4d-4e90-9f26-1d5a7c2b8e04` | lesson_key=`roundtrip-verification-status` | event_sha256=`93476eedd5c21a4d3cfbccb753615d30a705c5e87fe795a945a2ec8ba1f3b214`
- #23: `f7b9c1d3-6e2a-4f54-8a80-1d7e0c5b2f97` | 2026-08-20T04:41:00.000Z | GATE/remediation_verified_import_boundary | incident=`6d2f8a1c-4e90-5b73-9c16-7a3e1f5b8d02` | lesson_key=`verified-import-boundary` | event_sha256=`279bb3151ddff72576659816b8926509437e1772dafc4add34f756401c5e9ac9`
- #24: `a8c2e4f6-1b7d-4f90-9a36-2c5e0d8b1f48` | 2026-08-20T04:30:07.000Z | FAILURE/p1c_raw_snapshot_atomicity_boundary_red | incident=`9e4a2c7f-1b6d-4f80-8a53-2c7d1f0b4a6f` | lesson_key=`raw-snapshot-copy-register-atomicity` | event_sha256=`57537449cdde94679d454ae7a168f1d8c25b18c15c69465fd58e1d544eb0caf9`
- #25: `08c2e4f6-1b7d-4f90-9a36-2c5e0d8b1f49` | 2026-08-20T04:30:07.000Z | GATE/remediation_verified_deep_metadata_serialization | incident=`7c2e4a1f-9b5d-4e80-8a36-1f7c3d5b9e02` | lesson_key=`deep-metadata-serialization` | event_sha256=`9d15f0cd3f6387468bb3defd6884395c2a2157577f5994ceb0e9a9ed1c1c41c1`
- #26: `18d3f5b7-2c8e-4f90-9a46-1d7b0e5c2f84` | 2026-08-20T04:30:07.000Z | GATE/remediation_verified_stable_manifest_compatibility | incident=`8d3f5b2a-1c7e-4f90-9a36-2b5d8e0c1f47` | lesson_key=`stable-manifest-compatibility` | event_sha256=`586be6778075d6ea0fcc904b151580635a7e8d11a3956ce04341075cc8ec075c`
- #27: `29e4f6a8-3b9d-4f21-8a57-1c7e0d5b2f95` | 2026-08-20T04:30:07.000Z | GATE/remediation_verified_raw_snapshot_failure_cleanup | incident=`9e4a2c7f-1b6d-4f80-8a53-2c7d1f0b4a6f` | lesson_key=`raw-snapshot-copy-register-atomicity` | event_sha256=`5244f838acc3b7dfe7ede83eb7772a91573dcfdb755b4361ce41dae192951138`
- #28: `3af7b9d1-4e80-4f26-8a53-2c7d1f0b4a60` | 2026-08-20T05:00:00.000Z | GATE/remediation_reaffirmed_deep_metadata_serialization | incident=`7c2e4a1f-9b5d-4e80-8a36-1f7c3d5b9e02` | lesson_key=`deep-metadata-serialization` | event_sha256=`cec5d004c1d824eebdb5f44de3aa9e90ac9fa97d39ddc78aceaf123f31f9cab5`
- #29: `4b8c2e6f-1d7a-4f90-9a36-2c5e0d8b1f50` | 2026-08-20T05:00:00.000Z | GATE/remediation_reaffirmed_stable_manifest_compatibility | incident=`8d3f5b2a-1c7e-4f90-9a36-2b5d8e0c1f47` | lesson_key=`stable-manifest-compatibility` | event_sha256=`855aca413e0483124a07312d71a21a4f009aa309967cdf59583840fde62591e0`
- #30: `5c9e3a7f-1b6d-4f80-9a36-2c5e0d8b1f51` | 2026-08-20T05:05:00.000Z | GATE/data_consumer_final_owned_evidence_gate | incident=`6f2a4c8e-1b7d-4f90-9a36-2c5e0d8b1f52` | lesson_key=`final-owned-evidence-boundary` | event_sha256=`355b2b22014103f78a1b29390ded7cb4303cd3f8fc2d122abf336dc6f7853aa6`
