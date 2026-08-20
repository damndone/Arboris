# Retrospective — v1-8-9-p0-evidence-report-remediation-8

## Goal

# v1.8.9 P0 Evidence/Report Hardening — remediation-8 objective  ## Objective  At exact clean baseline \`cf41b0ab0a89e85a1e05d337b0ef6b065080a1e0\`, close the remaining P0 ARMA-GARCH report-path defect.  The legal owner-admitted \`_run_workflow\` path must execute the real ARMA-GARCH deliverable build and then construct an owner-issued \`ReportDocumentWriterV1\` before the real Jinja template and durable writer run.  A missing or invalid admission must return typed unavailable/blocked state before any raw ARMA builder/read and must prove zero builder calls.  ## Required outcomes  1. Preserve the existing fail-closed admission gate.  Missing, forged, stale,    or wrong-root owner/projection input produces typed unavailable/blocked    state before \`build_arma_garch_deliverables\` or any ARMA artifact read; the    builder call count remains zero. 2. Repair the legal ARMA path so \`_run_workflow\` reaches the real    \`build_arma_garch_deliverables\` implementation, converts its result through    the server-owned projection/document boundary, and invokes the real    \`ReportDocumentWriterV1\` plus real template rendering and durable artifact    registration.  No renderer mock may stand in for this proof. 3. Preserve exact owner, request identity, receipt, canonical project/run    root, artifact identity, content hash, and rendered file hash bindings.    Do not reintroduce \`ReportStage\` raw-dict fallback, ownerless legacy    rendering, or a second report engine. 4. Add a real renderer probe using only a temporary canonical run root and    safe fixture data.  Keep the existing missing-admission probe and extend    the valid probe so it asserts the real writer/template path and the    resulting indexed artifact/hash bindings. 5. Audit ARMA deliverable callers.  Keep typed contract or explicit typed    unavailable behavior for all callers; record exactly these three known    legacy ownerless/raw caller GAPs without weakening the contract:    \`legacy_arma_raw_renderer_boundary\`,    \`ownerless_normal_report_e2e_boundary_one\`, and    \`ownerless_normal_report_e2e_boundary_two\`. 6. Run evidence/report focused and impacted suites, compileall, diff-check,    formal verification, final GATE, retrospective generation, and handoff.    Commit only scoped changes in this worktree.  Do not push, merge, tag,    deploy, or modify another worktree/root checkout.  ## Scope  - \`backend/workbench/engine/packs/arma_garch/deliverables.py\` - \`backend/workbench/engine/stages/report.py\` - \`backend/workbench/orchestrator/__init__.py\` (only if the real workflow   wiring requires it) - \`tests/test_v189_evidence_report_boundary.py\` - \`tests/models/arma_garch/test_deliverables.py\` (only for typed contract   caller alignment if required) - this objective, its implementation plan, and the remediation-8 handoff  ## Protected boundaries  Do not modify Agent, Notebook, provider, estimator, frontend, dependency, deployment, live-host, release, or unrelated report/export surfaces.  Do not hand-edit \`.agent/devlines\` files.  Do not reset, checkout, delete, overwrite, push, merge, or tag.

## Final status

COMPLETED

## Metrics

- Failure frequency: 8/13 (61.5%; 61.5 per 100 events)
- Repeat rate: 2/8 (25.0%)
- Recurrence rate: 2/6 (33.3%)
- MTTR: median=0 ms (sample=4; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #3 2026-08-20T00:00:00.000Z `arma_real_renderer_owner_payload_red`; cause_status: `known`; cause: The real legal ARMA-GARCH workflow still passed the family builder's raw report mapping into the owner-issued document seam, so ReportDocumentWriterV1 rejected the payload before template and file IO.; resolution: `open`; lesson: Build the ARMA report through one owner-issued document payload before invoking the real template writer.

## All errors

- #2 2026-08-20T00:00:00.000Z `socket_capability_boundary`; cause_status: `external`; cause: The restricted runner rejected the Unix socket required by the server-owned authority fixture before the real-renderer RED assertions could execute.; resolution: `resolved`; lesson: Record restricted-host socket failures separately and rerun authority probes on a supported host.
- #8 2026-08-20T00:00:00.000Z `arma_pack_bootstrap_import_order`; cause_status: `known`; cause: The isolated ARMA pack declaration test hits the pre-existing loader-to-orchestrator statistical_tests circular import before the declaration assertion; the remediation-8 diff does not touch that import chain.; resolution: `accepted`; lesson: Keep unrelated import-order failures separate from evidence/report remediation and do not widen scope to repair them.
- #10 2026-08-20T00:00:00.000Z `formal_event_evidence_digest_correction`; cause_status: `known`; cause: A prior overlap review event used the digest of the orchestrator E2E file while its evidence ref named the ARMA pack runtime file; the append-only event was not edited and this correction records the exact runtime-file digest.; resolution: `resolved`; lesson: Compute evidence digests from the exact referenced file before appending a formal event.
- #11 2026-08-20T00:00:00.000Z `formal_event_evidence_digest_correction_pack_bootstrap`; cause_status: `known`; cause: The pre-existing pack bootstrap error event named the ARMA pack runtime file but initially carried the orchestrator E2E digest; the append-only history is preserved and this event supplies the exact runtime-file digest.; resolution: `resolved`; lesson: Bind every formal evidence digest to the exact path named by its evidence reference.

## All gaps

- #5 2026-08-20T00:00:00.000Z `legacy_arma_raw_renderer_boundary`; cause_status: `known`; cause: The standalone ARMA deliverables test intentionally passes the raw family mapping to the post-remediation typed render_html_report contract.; resolution: `accepted`; lesson: Keep standalone raw deliverable callers documented as legacy gaps rather than weakening the typed renderer boundary.
- #6 2026-08-20T00:00:00.000Z `ownerless_normal_report_e2e_boundary_one`; cause_status: `known`; cause: The normal-run traceable-output E2E invokes the orchestrator without a server-owned Report capability and still asserts an ownerless report.html file.; resolution: `accepted`; lesson: Keep ownerless normal-run HTML assertions documented until their fixture injects server-owned Report admission.
- #7 2026-08-20T00:00:00.000Z `ownerless_normal_report_e2e_boundary_two`; cause_status: `known`; cause: The advanced-statistics normal-run E2E invokes the orchestrator without a server-owned Report capability and still reads an ownerless report.html file.; resolution: `accepted`; lesson: Keep ownerless normal-run HTML assertions documented until their fixture injects server-owned Report admission.

## All waste

- None recorded.

## Root causes and solutions

- `arma-real-renderer-owner-payload`: occurrences=1; cause_status: `known`; root cause: The real legal ARMA-GARCH workflow still passed the family builder's raw report mapping into the owner-issued document seam, so ReportDocumentWriterV1 rejected the payload before template and file IO.; solution: `open`
- `formal-event-evidence-digest`: occurrences=2; cause_status: `known`; root cause: A prior overlap review event used the digest of the orchestrator E2E file while its evidence ref named the ARMA pack runtime file; the append-only event was not edited and this correction records the exact runtime-file digest.; solution: `resolved`
- `legacy-arma-raw-renderer-boundary`: occurrences=1; cause_status: `known`; root cause: The standalone ARMA deliverables test intentionally passes the raw family mapping to the post-remediation typed render_html_report contract.; solution: `accepted`
- `ownerless-normal-report-e2e-boundary`: occurrences=2; cause_status: `known`; root cause: The normal-run traceable-output E2E invokes the orchestrator without a server-owned Report capability and still asserts an ownerless report.html file.; solution: `accepted`
- `preexisting-pack-bootstrap-import-order`: occurrences=1; cause_status: `known`; root cause: The isolated ARMA pack declaration test hits the pre-existing loader-to-orchestrator statistical_tests circular import before the declaration assertion; the remediation-8 diff does not touch that import chain.; solution: `accepted`
- `socket-capable-host-evidence`: occurrences=1; cause_status: `external`; root cause: The restricted runner rejected the Unix socket required by the server-owned authority fixture before the real-renderer RED assertions could execute.; solution: `resolved`

## Added tests

- `tests/models/arma_garch/test_deliverables.py::test_arma_garch_report_and_exports_render_the_native_evidence`
- `tests/models/arma_garch/test_pack_runtime.py::test_pack_declaration_exposes_one_generic_time_series_handler`
- `tests/models/arma_garch/test_pack_runtime.py::test_public_workflow_completes_with_pack_graph_and_raw_lineage`
- `tests/test_orchestrator_e2e.py::test_normal_run_persists_typed_advanced_statistics_evidence`
- `tests/test_orchestrator_e2e.py::test_run_workflow_creates_traceable_outputs`
- `tests/test_v189_evidence_report_boundary.py`
- `tests/test_v189_evidence_report_boundary.py -k arma_garch_report_admission or arma_garch_real_renderer`
- `tests/test_v189_evidence_report_boundary.py::test_arma_garch_report_admission_valid_real_workflow_renders_owner_document`

## New rules

- `arma-real-renderer-owner-payload`: line experience occurrence(s)=1
- `formal-event-evidence-digest`: line experience occurrence(s)=2
- `legacy-arma-raw-renderer-boundary`: line experience occurrence(s)=1
- `ownerless-normal-report-e2e-boundary`: line experience occurrence(s)=2
- `preexisting-pack-bootstrap-import-order`: line experience occurrence(s)=1
- `socket-capable-host-evidence`: line experience occurrence(s)=1

## Future guidance

- Bind every formal evidence digest to the exact path named by its evidence reference.
- Build the ARMA report through one owner-issued document payload before invoking the real template writer.
- Compute evidence digests from the exact referenced file before appending a formal event.
- Group equivalent ownerless normal-run assertions under the existing documented GAP identity.
- Keep ownerless normal-run HTML assertions documented until their fixture injects server-owned Report admission.
- Keep standalone raw deliverable callers documented as legacy gaps rather than weakening the typed renderer boundary.
- Keep the family builder behind one owner-issued document adapter and test the real template/writer boundary.
- Keep unrelated import-order failures separate from evidence/report remediation and do not widen scope to repair them.
- Record restricted-host socket failures separately and rerun authority probes on a supported host.

## Event index

- #1: `f3ae17e4-79bb-4b72-b41d-a6bb38f8d15e` | 2026-08-20T05:17:04.248Z | STATE_CHANGE/line_started | incident=`19713522-4198-4faa-bc92-af812c9b3181` | lesson_key=`frozen-context-before-start` | event_sha256=`b07b8b52bf046602cf5d69d97dd0c10ffab88063a0aed88376231ef413b0021c`
- #2: `a3d0c3e8-2b6e-4d2a-8a31-75e9969d9c21` | 2026-08-20T00:00:00.000Z | ERROR/socket_capability_boundary | incident=`49f7e7e4-26e0-4c5b-b5d2-621692b6047e` | lesson_key=`socket-capable-host-evidence` | event_sha256=`a9fe52390c9ad8e6f504dce59872366dc603f2902657a633134d50fa6b27dcc7`
- #3: `b9c1d6f2-4e76-4dd3-a7d3-51a7fd4f1e89` | 2026-08-20T00:00:00.000Z | FAILURE/arma_real_renderer_owner_payload_red | incident=`b6e50af0-9cc2-4e95-9f1c-14a9b6366e27` | lesson_key=`arma-real-renderer-owner-payload` | event_sha256=`6ef2fc4c14abb0d7af3898b386c10d127cf3a762312225df56b70ca534a926ed`
- #4: `c1c01c63-f542-4fba-8f54-4d4cd1f51269` | 2026-08-20T00:00:00.000Z | REVIEW/arma_real_renderer_owner_payload_green | incident=`b6e50af0-9cc2-4e95-9f1c-14a9b6366e27` | lesson_key=`arma-real-renderer-owner-payload` | event_sha256=`b810c8ce77c39f801a2f56777e4021c6ddfbc6a62a8a82c8cf450470074fbbfa`
- #5: `0e7e65b9-5ff9-4c0e-bd7e-6b92f8cc7c17` | 2026-08-20T00:00:00.000Z | GAP/legacy_arma_raw_renderer_boundary | incident=`e8a1ad6b-5c3f-469a-9f1e-34d0a0f3b4b4` | lesson_key=`legacy-arma-raw-renderer-boundary` | event_sha256=`ecfdd2851797a22290a10f32cb52e2fb57466ca3cea490c1c706087bd475db2d`
- #6: `1f6a7d11-c7e5-4c17-9cbb-4c6d1b4b4b49` | 2026-08-20T00:00:00.000Z | GAP/ownerless_normal_report_e2e_boundary_one | incident=`c1f8dc15-e175-47d5-b4f2-17d85c19f9e7` | lesson_key=`ownerless-normal-report-e2e-boundary` | event_sha256=`47b44fb399295e19ad1697cc8941d6ca7cb8c8d6b40453685c6a018abb4f5f76`
- #7: `2c0d7d9e-0a62-43c7-a70a-f1a1ce4d51f9` | 2026-08-20T00:00:00.000Z | GAP/ownerless_normal_report_e2e_boundary_two | incident=`c1f8dc15-e175-47d5-b4f2-17d85c19f9e7` | lesson_key=`ownerless-normal-report-e2e-boundary` | event_sha256=`af2237e009242a15fcea05ea0036f0bbc7222f7e08ddbcf36a88644ede85502a`
- #8: `3aa9b6cf-2ee5-49f7-b0fa-1e72bdf9e0d3` | 2026-08-20T00:00:00.000Z | ERROR/arma_pack_bootstrap_import_order | incident=`99dd9db7-1f41-4ab7-8371-4c9c33d58977` | lesson_key=`preexisting-pack-bootstrap-import-order` | event_sha256=`40251944758509cbca1443c0514ebe40196572f2a07e0e03ad56f73895e15d25`
- #9: `4bb2a7d3-1ce0-4cbb-9d7b-1d7c948cc3b8` | 2026-08-20T00:00:00.000Z | REVIEW/arma_pack_runtime_ownerless_overlap | incident=`7f7b8a4c-dabf-4d6e-9ad8-9a97a2dc08af` | lesson_key=`ownerless-normal-report-e2e-boundary` | event_sha256=`84076b9d0c4c21ced53b2e3c8ca77ebec92aff4ae95d247a35991a5559709d84`
- #10: `5cc1f0ee-dc04-4e3f-9e2f-7ed6a0fc2c76` | 2026-08-20T00:00:00.000Z | ERROR/formal_event_evidence_digest_correction | incident=`1c3cb81d-4ccd-49e1-86be-d093baec0f5f` | lesson_key=`formal-event-evidence-digest` | event_sha256=`0ec3f3b19e44ab64e7aa1075b84f573b9fb4d979b866c7eefc9cc9d57bde32e6`
- #11: `6dd19e1b-cf59-4bb8-9563-8fce1e9f4e14` | 2026-08-20T00:00:00.000Z | ERROR/formal_event_evidence_digest_correction_pack_bootstrap | incident=`99dd9db7-1f41-4ab7-8371-4c9c33d58977` | lesson_key=`formal-event-evidence-digest` | event_sha256=`1f0204c5f0d7e73eaead759a027c5b15114527c8da8532824e376715339d0300`
- #12: `7e3aa0b0-4a84-43e2-8c8f-bc7c8b1a0a3f` | 2026-08-20T00:00:00.000Z | GATE/remediation_eight_final_closeout_gate | incident=`d0a4f8bc-9ecb-46a5-ae68-5a7daed6e0e8` | lesson_key=`evidence-report-remediation-final-gate` | event_sha256=`f14fccee1e9e2866b08ebe7ee5875e36cc3fd3c01f4db2d8483546011e68ab0f`
- #13: `8f53d2c0-9fd4-4ef5-b1e8-7c4b3c9b4f62` | 2026-08-20T00:00:00.000Z | STATE_CHANGE/line_completed | incident=`f2e2dbe2-6d03-4a67-92b9-6d6d11d8f7f5` | lesson_key=`evidence-report-remediation-line-complete` | event_sha256=`b0fb95983d407f31af54006ed38b8114e1937f86c733b9108cb843ae608dbdcf`
