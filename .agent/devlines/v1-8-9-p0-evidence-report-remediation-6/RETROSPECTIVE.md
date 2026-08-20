# Retrospective — v1-8-9-p0-evidence-report-remediation-6

## Goal

# v1.8.9 P0 Evidence/Report Hardening — remediation-6 objective  ## Objective  Close the independent remediation-5 Evidence/Report review findings at the exact clean baseline \`5daa3dfc5542fabdf5466261431da401547710d2\`.  Every legacy presentation, Report export, and document-writer path must fail closed before facts, templates, artifact hashes, or filesystem IO unless the exact server-issued C0 owner and projection admission are present.  ## Required outcomes  1. \`build_report_view_model\` must reject missing, caller-shaped, or forged    owner/projection inputs before \`_build_legacy_presentation\`, template reads,    staged fact reads, or filesystem IO.  The valid server-admitted owner path    must still return the admitted typed facts and preserve the legacy    presentation projection only after admission. 2. Report/evidence HTTP and export entrances must complete a real    server-owned owner/proof/receipt/canonical admission before reading an    artifact index, hashing an artifact, or reading artifact bytes.  Add direct    order probes for both the evidence and export paths. 3. \`EvidenceProjectionV1\`, \`ReportEvidenceWriterV1\`, and    \`ReportDocumentWriterV1\` must require an unforgeable-in-practice    server-issued exact-object identity/issuer registry in addition to copied    fields, markers, and digests.  \`object.__new__\` clones and copied/serialized    projections must fail before facts or writer/filesystem IO; the real owner    issued projection/writer remains usable. 4. The normal \`ReportStage\` must adapt a server-owned C0 report owner and    projection from its existing stage context/receipt admission into    \`render_legacy_html_report\`.  If no exact owner/projection is available it    must emit typed unavailable/blocked report state and never restore a raw    summary fallback.  Add a positive stage probe and a no-owner negative probe.  ## TDD and verification  For each outcome, add a real RED probe first and run it against this exact baseline before changing production code.  Run the focused Evidence/Report, HTTP, export, and ReportStage suites in a socket-capable host; run direct no-IO/order/object-clone/positive owner probes; run compileall, diff check, and formal retrospective/verify.  Record exact RED/GREEN commands and counts in the remediation-6 handoff.  Browser, provider, central Agent/Notebook, live production host, full repository gate, and release acceptance remain \`NOT VERIFIED\`.  ## Boundaries  Only this target worktree may change.  In scope are the Evidence/Report backend seams, the minimal normal ReportStage/HTTP adapter needed to preserve the valid owner path, focused tests, and remediation-6 objective/plan/handoff and formal records.  Do not modify central Agent/Notebook semantic engines, providers, estimators, live-host code, frontend, dependencies, deployment wiring, the root worktree, or another worktree unless a focused fixture makes it unavoidable.  Push, merge, tag, and release remain out of scope.

## Final status

COMPLETED

## Metrics

- Failure frequency: 5/12 (41.7%; 41.7 per 100 events)
- Repeat rate: 0/5 (0.0%)
- Recurrence rate: 0/5 (0.0%)
- MTTR: median=11412 ms (sample=5; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T04:25:42.094Z `legacy_presentation_owner_red`; cause_status: `known`; cause: The baseline RED probe reached legacy presentation construction without a C0 owner or projection admission.; resolution: `open`; lesson: Gate every legacy presentation read before summary, template, or filesystem access.
- #4 2026-08-20T04:26:09.338Z `http_admission_order_red`; cause_status: `known`; cause: The baseline HTTP evidence and export probes observed artifact index or hash work before server owner admission.; resolution: `open`; lesson: Admit the real server owner before opening an artifact index or hashing any export input.
- #6 2026-08-20T04:26:33.810Z `exact_identity_clone_red`; cause_status: `known`; cause: The baseline clone probe copied valid projection and writer fields, then reached canonical report IO because field markers were the only admission proof.; resolution: `open`; lesson: Require an exact server-issued identity registry in every projection and writer consumer.
- #8 2026-08-20T04:26:58.944Z `report_stage_owner_red`; cause_status: `known`; cause: The baseline ReportStage probe found no owner/projection adapter and the normal stage had no typed admission path for legacy rendering.; resolution: `open`; lesson: Adapt the exact stage-owned report admission and fail typed unavailable when it is absent.

## All errors

- #10 2026-08-20T04:27:25.174Z `socket_capability_boundary`; cause_status: `known`; cause: The default restricted runner could not bind the Unix socket used by the real owner fixture; the same probes were rerun on a socket-capable host.; resolution: `resolved`; lesson: Record restricted-host socket failures separately and rerun authority probes on the supported host.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `exact-report-identity-registry`: occurrences=1; cause_status: `known`; root cause: The baseline clone probe copied valid projection and writer fields, then reached canonical report IO because field markers were the only admission proof.; solution: `open`
- `http-owner-before-artifact-io`: occurrences=1; cause_status: `known`; root cause: The baseline HTTP evidence and export probes observed artifact index or hash work before server owner admission.; solution: `open`
- `legacy-presentation-owner-gate`: occurrences=1; cause_status: `known`; root cause: The baseline RED probe reached legacy presentation construction without a C0 owner or projection admission.; solution: `open`
- `report-stage-owner-adapter`: occurrences=1; cause_status: `known`; root cause: The baseline ReportStage probe found no owner/projection adapter and the normal stage had no typed admission path for legacy rendering.; solution: `open`
- `socket-capable-host-evidence`: occurrences=1; cause_status: `known`; root cause: The default restricted runner could not bind the Unix socket used by the real owner fixture; the same probes were rerun on a socket-capable host.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `exact-report-identity-registry`: line experience occurrence(s)=1
- `http-owner-before-artifact-io`: line experience occurrence(s)=1
- `legacy-presentation-owner-gate`: line experience occurrence(s)=1
- `report-stage-owner-adapter`: line experience occurrence(s)=1
- `socket-capable-host-evidence`: line experience occurrence(s)=1

## Future guidance

- Adapt the exact stage-owned report admission and fail typed unavailable when it is absent.
- Admit the real server owner before opening an artifact index or hashing any export input.
- Gate every legacy presentation read before summary, template, or filesystem access.
- Record restricted-host socket failures separately and rerun authority probes on the supported host.
- Require an exact server-issued identity registry in every projection and writer consumer.

## Event index

- #1: `fb6dd5e1-a3f0-4b61-80bf-dc8859ad213c` | 2026-08-20T04:04:25.308Z | STATE_CHANGE/line_started | incident=`0b0947b6-8875-4d1f-9bc1-2189fc467d0f` | lesson_key=`frozen-context-before-start` | event_sha256=`f184484cba186c248296536ea0f7b1ce5276febe09166162019cec09cea40edb`
- #2: `7335945b-fc7c-4575-baf9-ce1f4b45f7cd` | 2026-08-20T04:25:42.094Z | FAILURE/legacy_presentation_owner_red | incident=`f19ccf40-add5-47a7-a131-66dd53bfd7d7` | lesson_key=`legacy-presentation-owner-gate` | event_sha256=`35eb2fb0c9140d2a5b7c938dc76032d9d0f899a55e6b6d4d90b398b575763619`
- #3: `67d2f037-062c-493c-bb7e-2e67d90fb8c2` | 2026-08-20T04:25:54.786Z | REVIEW/legacy_presentation_owner_green | incident=`f19ccf40-add5-47a7-a131-66dd53bfd7d7` | lesson_key=`legacy-presentation-owner-gate` | event_sha256=`30c2ed781ad60b3ed2957d60321c8d859ea4ed0e94fad9cc370260c6dc0c25a3`
- #4: `f2ec6d46-5a81-465e-9c85-b9fa52e701cc` | 2026-08-20T04:26:09.338Z | FAILURE/http_admission_order_red | incident=`e14317b5-657e-42a8-845b-69530a23679f` | lesson_key=`http-owner-before-artifact-io` | event_sha256=`4447cb81cb94962c3c0b80be0db0565d97d66ee7a80d5c3f59b35df3685d0534`
- #5: `841547aa-fde9-4045-825a-f820125be848` | 2026-08-20T04:26:20.484Z | REVIEW/http_admission_order_green | incident=`e14317b5-657e-42a8-845b-69530a23679f` | lesson_key=`http-owner-before-artifact-io` | event_sha256=`f5a9907f9fbe8f37bc7f33ac691c18fc07b2683af651e7721f75a988a7c83d64`
- #6: `c8e02db9-5e3e-4c8b-bf58-0eaa74f461d6` | 2026-08-20T04:26:33.810Z | FAILURE/exact_identity_clone_red | incident=`cb497232-6b7e-409d-aec2-3a8ee42d0047` | lesson_key=`exact-report-identity-registry` | event_sha256=`25a2bff371e1d4e73627ff7123243ffd0962dc87dceea6d05dd842a3c83a4761`
- #7: `d846fb4e-0b68-463b-8fa6-01d021eb3d19` | 2026-08-20T04:26:45.244Z | REVIEW/exact_identity_clone_green | incident=`cb497232-6b7e-409d-aec2-3a8ee42d0047` | lesson_key=`exact-report-identity-registry` | event_sha256=`55c566c47460be2a9e53f685ad3c03cbc5448255db9de4781491bce3ba591f69`
- #8: `cc0dd114-b14f-4f9e-809f-a2928f92d432` | 2026-08-20T04:26:58.944Z | FAILURE/report_stage_owner_red | incident=`ff224562-bd0b-47ae-b1b4-e7b6dc3fbf08` | lesson_key=`report-stage-owner-adapter` | event_sha256=`c495d67074fa9da5f0d31b565fc168dba3b1125111f66a98b192f51b7b887be8`
- #9: `7ec73003-dd36-4ff2-8784-d27e17abb9c1` | 2026-08-20T04:27:10.356Z | REVIEW/report_stage_owner_green | incident=`ff224562-bd0b-47ae-b1b4-e7b6dc3fbf08` | lesson_key=`report-stage-owner-adapter` | event_sha256=`24502e0ea018a1053a1b04e4f1c4c1ea41327d5ea038245fea1b03439ad38ff3`
- #10: `0d0bf2e8-f7aa-42e8-a057-287f450f4535` | 2026-08-20T04:27:25.174Z | ERROR/socket_capability_boundary | incident=`f3afef8a-080e-4476-a41b-cf92e9ba72a6` | lesson_key=`socket-capable-host-evidence` | event_sha256=`b6f79a109ae4c70538833892aeb715e977f20987344a226207c39b932a81085f`
- #11: `175c756d-3b1c-48c0-a01c-fe9b9bbd6810` | 2026-08-20T04:31:46.512Z | GATE/remediation_six_verification_gate | incident=`48462fa0-7fbd-4c6e-b084-0f6a43c35f28` | lesson_key=`evidence-report-remediation-gate` | event_sha256=`adf38d71064a26cef36e9ab05b2556f1e62fa6952d541354f32a76d3a5418dde`
- #12: `8fa98f12-4793-41a2-9854-04e97d54d70c` | 2026-08-20T04:32:35.793Z | STATE_CHANGE/line_completed | incident=`97c39eb1-419f-4b39-98e0-fb4ead39ad47` | lesson_key=`evidence-report-remediation-line-complete` | event_sha256=`fd5d16ce5da03528eee10b362aa66fb4bc7e80c969199597f11bacc7eaea8f98`
