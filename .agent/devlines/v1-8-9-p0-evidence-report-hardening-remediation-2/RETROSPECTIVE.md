# Retrospective — v1-8-9-p0-evidence-report-hardening-remediation-2

## Goal

# Workbench v1.8.9 P0 Evidence/Report Remediation 2  Remediate the independent-spec review findings from the exact prior closeout baseline \`dc74ef64f9cba6d0983f81c85c7366b60712a655\` in the existing evidence report hardening worktree. This is a new formal remediation line; do not edit the predecessor formal line or its records.  Required TDD outcomes:  1. Replace the importable \`_REPORT_FACTORY_TOKEN\` trust seam with a real    server-owned/C0 owner capability check. Caller-created tokens, copied or    serialized owner-shaped objects, forged self-consistent projection wires,    and unowned writer/export calls must fail closed before any filesystem or    XLSX/PDF/HTML IO. Add real RED probes, then the smallest owner-bound GREEN    implementation. 2. Make frontend \`readReportEvidenceProjection\` validate the existing    canonical JSON projection digest semantics. Digest, identity, or provenance    tampering must return the typed unavailable path before facts are rendered. 3. Ensure prediction evidence and legacy state cannot become citable Report    facts through a bypass. They may remain historical compatibility inputs, but    raw \`model_results\`, \`post_estimation_results\`, and artifact JSON must either    enter the same server-owned typed evidence projection or render typed    unavailable/non-citable. Add a real Report rendering-path probe. 4. Fix event timestamp generation at the real append writer: while holding the    append lock, generate a server-side UTC timestamp strictly later than the    current tail, preserving append-only hash-chain and anchor integrity. Do not    relax strict verification and do not change tests to hide the collision.  Every required item must follow write RED probe -> run and observe the expected failure -> minimal implementation -> GREEN rerun. Preserve the existing C0 owner, historical report assertions, and protected central Agent/Notebook, provider, estimator, and live-host paths. Browser/provider/central integration, host/full-gate, and release acceptance remain NOT VERIFIED.

## Final status

COMPLETED

## Metrics

- Failure frequency: 8/15 (53.3%; 53.3 per 100 events)
- Repeat rate: 0/8 (0.0%)
- Recurrence rate: 0/8 (0.0%)
- MTTR: median=0 ms (sample=2; unresolved=6)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: N/A (sample=0)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T00:20:00.000Z `report_owner_c0_authority_probe_red`; cause_status: `known`; cause: The report projection seam accepted a caller-created owner and imported factory token.; resolution: `open`; lesson: Bind report evidence admission to a real server-owned capability before rendering.
- #3 2026-08-20T00:20:01.000Z `report_frontend_boundary_probe_red`; cause_status: `known`; cause: The frontend projection reader did not compare the supplied projection digest with canonical projection content.; resolution: `open`; lesson: Use the existing canonical JSON digest rule at the frontend projection boundary.
- #4 2026-08-20T00:20:02.000Z `devline_append_timestamp_probe_red`; cause_status: `known`; cause: The append writer validated caller timestamps without generating a strictly later timestamp under the append lock.; resolution: `open`; lesson: Generate the event timestamp inside the locked append writer and preserve strict verification.

## All errors

- #5 2026-08-20T00:20:03.000Z `frontend_probe_wrong_cwd`; cause_status: `known`; cause: The focused frontend command was first launched from the repository root instead of the frontend package directory.; resolution: `resolved`; lesson: Run package-local frontend probes from the package directory recorded by the Context Pack.
- #10 2026-08-20T00:27:00.000Z `formal_event_input_rejected`; cause_status: `known`; cause: The first rescope state event used a preventability value outside the event contract.; resolution: `resolved`; lesson: Validate formal event enum values before invoking the append control.
- #12 2026-08-20T00:30:00.000Z `focused_backend_socket_boundary`; cause_status: `external`; cause: The default sandbox denied the real UNIX socket bind used by the focused C0 evidence fixtures.; resolution: `open`; lesson: Separate host permission boundaries from implementation failures and rerun real probes in a controlled environment.
- #13 2026-08-20T00:30:01.000Z `frontend_projection_fixture_typecheck`; cause_status: `known`; cause: Making projectionDigest required in the frontend structural type exposed existing local test fixtures that intentionally omit server wire digests.; resolution: `open`; lesson: Keep runtime server-wire admission strict while allowing legacy local view fixtures to remain non-authoritative.
- #14 2026-08-20T00:31:00.000Z `projection_freeze_compare_failure`; cause_status: `known`; cause: The new owner recheck compared a recursively frozen projection wire with the mutable canonical wire by Python container identity semantics.; resolution: `open`; lesson: Compare canonical digest semantics after immutable freezing, not mutable container representation.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `devline-append-timestamp-red`: occurrences=1; cause_status: `known`; root cause: The append writer validated caller timestamps without generating a strictly later timestamp under the append lock.; solution: `open`
- `focused-backend-socket-boundary`: occurrences=1; cause_status: `external`; root cause: The default sandbox denied the real UNIX socket bind used by the focused C0 evidence fixtures.; solution: `open`
- `formal-event-enum-input`: occurrences=1; cause_status: `known`; root cause: The first rescope state event used a preventability value outside the event contract.; solution: `resolved`
- `frontend-probe-package-cwd`: occurrences=1; cause_status: `known`; root cause: The focused frontend command was first launched from the repository root instead of the frontend package directory.; solution: `resolved`
- `frontend-wire-type-compatibility`: occurrences=1; cause_status: `known`; root cause: Making projectionDigest required in the frontend structural type exposed existing local test fixtures that intentionally omit server wire digests.; solution: `open`
- `projection-freeze-canonical-compare`: occurrences=1; cause_status: `known`; root cause: The new owner recheck compared a recursively frozen projection wire with the mutable canonical wire by Python container identity semantics.; solution: `open`
- `report-frontend-digest-red`: occurrences=1; cause_status: `known`; root cause: The frontend projection reader did not compare the supplied projection digest with canonical projection content.; solution: `open`
- `report-owner-c0-authority-red`: occurrences=1; cause_status: `known`; root cause: The report projection seam accepted a caller-created owner and imported factory token.; solution: `open`

## Added tests

- `frontend/src/report/ReportEvidenceBoundary.v189.test.tsx::rejects_a_self_consistent_looking_projection_with_a_tampered_digest`
- `frontend/src/report/factTable.ts`
- `tests/test_devline_control_events.py::test_append_serializes_two_writers_without_interleaving`
- `tests/test_report_export.py::test_report_export_embeds_figures_in_html_and_print_html`
- `tests/test_v189_evidence_report_boundary.py`
- `tests/test_v189_evidence_report_boundary.py::test_round_five_imported_factory_token_and_forged_owner_fail_before_projection_io`

## New rules

- `devline-append-timestamp-red`: line experience occurrence(s)=1
- `focused-backend-socket-boundary`: line experience occurrence(s)=1
- `formal-event-enum-input`: line experience occurrence(s)=1
- `frontend-probe-package-cwd`: line experience occurrence(s)=1
- `frontend-wire-type-compatibility`: line experience occurrence(s)=1
- `projection-freeze-canonical-compare`: line experience occurrence(s)=1
- `report-frontend-digest-red`: line experience occurrence(s)=1
- `report-owner-c0-authority-red`: line experience occurrence(s)=1

## Future guidance

- Bind report evidence admission to a real server-owned capability before rendering.
- Compare canonical digest semantics after immutable freezing, not mutable container representation.
- Generate the event timestamp inside the locked append writer and preserve strict verification.
- Keep runtime server-wire admission strict while allowing legacy local view fixtures to remain non-authoritative.
- Run package-local frontend probes from the package directory recorded by the Context Pack.
- Separate host permission boundaries from implementation failures and rerun real probes in a controlled environment.
- Use the existing canonical JSON digest rule at the frontend projection boundary.
- Validate formal event enum values before invoking the append control.

## Event index

- #1: `3025a734-2157-43b6-a70c-ce94c4f10864` | 2026-08-20T00:10:13.168Z | STATE_CHANGE/line_started | incident=`727b3fa9-b80d-4482-81d7-562db3fc52b9` | lesson_key=`frozen-context-before-start` | event_sha256=`27ec3c8b1b4d3352c10176e894e38d3173b69558e45131582b665b03684ae40b`
- #2: `7e9ef53f-8790-4f36-9f5a-4c0d3cb7a101` | 2026-08-20T00:20:00.000Z | FAILURE/report_owner_c0_authority_probe_red | incident=`1f37ce2c-2e9f-4c9c-9db5-66e7d8d7a101` | lesson_key=`report-owner-c0-authority-red` | event_sha256=`06965776368dc8619d8dba28aea6bb5f28fd6a150de7cfb7404d6875f1c9ea72`
- #3: `7e9ef53f-8790-4f36-9f5a-4c0d3cb7a102` | 2026-08-20T00:20:01.000Z | FAILURE/report_frontend_boundary_probe_red | incident=`1f37ce2c-2e9f-4c9c-9db5-66e7d8d7a102` | lesson_key=`report-frontend-digest-red` | event_sha256=`55353566422b14942330357ccd560a5aaaa069119d43b4d27b192642569003e9`
- #4: `7e9ef53f-8790-4f36-9f5a-4c0d3cb7a103` | 2026-08-20T00:20:02.000Z | FAILURE/devline_append_timestamp_probe_red | incident=`1f37ce2c-2e9f-4c9c-9db5-66e7d8d7a103` | lesson_key=`devline-append-timestamp-red` | event_sha256=`948c6ff343884f967e6ce9f1e2b5679206167af63d1421978a9ee43d3c153d5b`
- #5: `7e9ef53f-8790-4f36-9f5a-4c0d3cb7a104` | 2026-08-20T00:20:03.000Z | ERROR/frontend_probe_wrong_cwd | incident=`1f37ce2c-2e9f-4c9c-9db5-66e7d8d7a104` | lesson_key=`frontend-probe-package-cwd` | event_sha256=`77a5683139f281a9652f641d6c744ceb1e0f7518a857ea7c509a253a3dc0c5bd`
- #6: `10c38ed4-e02d-428c-9a08-0bda98e808bf` | 2026-08-20T00:20:52.167Z | STATE_CHANGE/context_rescope_required | incident=`b8f9c262-9f74-4071-ad08-13dbb1efd889` | lesson_key=`context-pack-rescope` | event_sha256=`2f5ac5e2fde0aada1d10ddeb3ae2ef94b4d70cf21b86416dd5f6111e06318c76`
- #7: `ae756614-6e4f-484c-b439-305c8920981d` | 2026-08-20T00:20:52.171Z | STATE_CHANGE/context_rescoped | incident=`b5030cfb-a0e5-444e-b562-abe9fa4744e5` | lesson_key=`context-pack-rescope` | event_sha256=`3ee1e5a621eeb4ac7e86351296ea96375bbc28092c7b5b658ae3df10ac82bcb7`
- #8: `fe3fbdc6-a9d7-4b1d-920f-1444b84568cd` | 2026-08-20T00:21:15.956Z | STATE_CHANGE/context_rescope_required | incident=`8ec120f2-3c97-4a87-9eb6-728b75af3e50` | lesson_key=`context-pack-rescope` | event_sha256=`03463bc5b7890bcf91e06fd31cf2a993b69de09b337dd8116c3dac02a87e91f9`
- #9: `d4d2894f-b9b8-45ad-ad92-ecb577335b34` | 2026-08-20T00:21:15.962Z | STATE_CHANGE/context_rescoped | incident=`60947c9f-ddc8-4b3c-991a-cddfd4f3cd89` | lesson_key=`context-pack-rescope` | event_sha256=`72a5f049e3ea8b38f1509a1e3e6634047ecc119b3dc462104d631490b4ff9fa3`
- #10: `7e9ef53f-8790-4f36-9f5a-4c0d3cb7a106` | 2026-08-20T00:27:00.000Z | ERROR/formal_event_input_rejected | incident=`1f37ce2c-2e9f-4c9c-9db5-66e7d8d7a106` | lesson_key=`formal-event-enum-input` | event_sha256=`25b20e319fdde5983db93a3dc8aa490b091af1f08aab415f47e0cc7c3eb35f1f`
- #11: `7e9ef53f-8790-4f36-9f5a-4c0d3cb7a105` | 2026-08-20T00:27:01.000Z | STATE_CHANGE/formal_scope_rescoped | incident=`1f37ce2c-2e9f-4c9c-9db5-66e7d8d7a105` | lesson_key=`formal-reportview-rescope` | event_sha256=`2a893643d98f32ddbf786c1dea336346a62f88a6421cbcc0dae9f452e298997f`
- #12: `7e9ef53f-8790-4f36-9f5a-4c0d3cb7a107` | 2026-08-20T00:30:00.000Z | ERROR/focused_backend_socket_boundary | incident=`1f37ce2c-2e9f-4c9c-9db5-66e7d8d7a107` | lesson_key=`focused-backend-socket-boundary` | event_sha256=`db4aebfb2279b04dd2703157f1950bed55d458083adee60d60f5d6d5021681a9`
- #13: `7e9ef53f-8790-4f36-9f5a-4c0d3cb7a108` | 2026-08-20T00:30:01.000Z | ERROR/frontend_projection_fixture_typecheck | incident=`1f37ce2c-2e9f-4c9c-9db5-66e7d8d7a108` | lesson_key=`frontend-wire-type-compatibility` | event_sha256=`aa07db12e06af737e24705f8e06c3608f6dc168c600e83051a26baf6f418982e`
- #14: `7e9ef53f-8790-4f36-9f5a-4c0d3cb7a109` | 2026-08-20T00:31:00.000Z | ERROR/projection_freeze_compare_failure | incident=`1f37ce2c-2e9f-4c9c-9db5-66e7d8d7a109` | lesson_key=`projection-freeze-canonical-compare` | event_sha256=`f0747331c4760652691f3e1a697fc1ef5c8041a92d611cde915e215d4766358a`
- #15: `7e9ef53f-8790-4f36-9f5a-4c0d3cb7a110` | 2026-08-20T00:36:00.000Z | STATE_CHANGE/remediation_line_completed | incident=`1f37ce2c-2e9f-4c9c-9db5-66e7d8d7a110` | lesson_key=`close-remediation-at-measured-boundary` | event_sha256=`cce754006d8d4c4ad44056e61963801f563efed80abaa3e2745f781c27884ff8`
