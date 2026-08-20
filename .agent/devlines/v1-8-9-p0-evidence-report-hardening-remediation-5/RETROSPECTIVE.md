# Retrospective — v1-8-9-p0-evidence-report-hardening-remediation-5

## Goal

# v1.8.9 P0 Evidence/Report Hardening — remediation-5 objective  ## Objective  Close the independent remediation-4 Evidence/Report review finding that the legacy Report view and legacy render/persistence surfaces can still accept a caller-shaped \`Mapping\` rather than the exact C0 server-owned Report owner. The legacy compatibility path must become fail-closed before any writer, artifact registration, or filesystem IO while preserving the valid server-admitted Report path.  ## Required outcomes  1. \`build_report_view_model(evidence_projection=...)\` must require the exact    C0 server-owned Report owner, host proof/receipt, and canonical evidence    admission. Caller mappings, object.__new__ objects, caller identities, and    forged provenance without that owner return typed blocked/unavailable with    zero citable facts before any writer or persistence IO. 2. \`render_legacy_html_report\` and every legacy HTML/PDF/XLSX/bytes    writer/register/artifact-persistence entrance must use the same owner gate.    A forged mapping probe must prove \`write_bytes_durable\` and    \`register_artifact\` are not called; the valid server-admitted path must    remain writable. 3. Reconcile the exact \`git rev-parse HEAD\`, handoff parent/tip/formal    manifest/event digests, and remediation-5 formal events. Preserve the    previous remediation-4 bounds and the strict 17-pass event result; close    with \`unresolved=0\`. 4. Preserve frontend typed Report paths, raw classification \`NON-CITABLE\`,    strict provenance and outer/nested tamper handling, and controlled-host    HTTP behavior. Browser, provider, central, production live-host,    full-gate, and release remain \`NOT VERIFIED\`.  ## TDD and verification  Write real forged legacy view/render probes first and run them RED against the exact baseline. Add a real valid owner probe and run it GREEN after the minimal owner-gated implementation. Run the legacy/report focused backend suite, the existing frontend/evidence suites, the strict event pair, frontend typecheck, targeted compileall, \`git diff --check\`, and formal \`retrospective\`/\`verify\`.  ## Boundaries  Only this target worktree may change. Do not modify root, any other worktree, central Agent/Notebook/provider/estimator/live-host source, dependencies, or deployment wiring. Browser/provider/central/live-host/full-gate/release acceptance remain \`NOT VERIFIED\`.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/7 (28.6%; 28.6 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=340920 ms (sample=2; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T03:09:56.442Z `legacy_report_owner_red`; cause_status: `known`; cause: The exact-baseline forged legacy view/render probes showed that a caller-shaped Mapping was accepted as available and reached the legacy writer seam; the valid owner probe also exposed the missing owner-gated API before implementation.; resolution: `open`; lesson: Require the exact C0 server-owned Report owner and canonical typed projection before legacy presentation or any writer/register/filesystem boundary.

## All errors

- #3 2026-08-20T03:16:27.672Z `legacy_report_host_socket_environment`; cause_status: `external`; cause: The default sandbox rejected the real Unix authority socket while the valid owner probe was being repeated; the same probe passed in the controlled socket-capable host.; resolution: `resolved`; lesson: Keep authority-socket permission failures separate from implementation RED/GREEN evidence and rerun identical host-dependent probes in the controlled environment.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `legacy-report-host-socket-boundary`: occurrences=1; cause_status: `external`; root cause: The default sandbox rejected the real Unix authority socket while the valid owner probe was being repeated; the same probe passed in the controlled socket-capable host.; solution: `resolved`
- `legacy-report-owner-gate`: occurrences=1; cause_status: `known`; root cause: The exact-baseline forged legacy view/render probes showed that a caller-shaped Mapping was accepted as available and reached the legacy writer seam; the valid owner probe also exposed the missing owner-gated API before implementation.; solution: `open`

## Added tests

- `controlled backend Evidence/Report focused suite: 114 passed, 1 warning`
- `controlled backend Evidence/Report remediation-5 owner gate and no-IO probes`
- `controlled package-local Evidence/Report remediation-5 verification`
- `tests/test_v189_evidence_report_boundary.py -k remediation_five`
- `tests/test_v189_evidence_report_boundary.py -k remediation_five_server_admitted_owner (default sandbox)`

## New rules

- `legacy-report-host-socket-boundary`: line experience occurrence(s)=1
- `legacy-report-owner-gate`: line experience occurrence(s)=1

## Future guidance

- Close the legacy Report owner gate only after forged no-IO probes and the controlled positive owner path pass together.
- Keep authority-socket permission failures separate from implementation RED/GREEN evidence and rerun identical host-dependent probes in the controlled environment.
- Require the exact C0 server-owned Report owner and canonical typed projection before legacy presentation or any writer/register/filesystem boundary.
- Resolve RED incidents on their original identity only after the matching adversarial negative and controlled positive probes pass.

## Event index

- #1: `ccf8d73b-f650-4df0-95f8-17f7080cab24` | 2026-08-20T03:01:54.554Z | STATE_CHANGE/line_started | incident=`1aa64f41-65b8-4eee-990b-5f959d0bf05d` | lesson_key=`frozen-context-before-start` | event_sha256=`3f86af5220eef619ba2017be78718207ec4cc75d22da1ed05a6d95acf565490a`
- #2: `a1c7e4d2-5b89-4f03-9c16-7e2a8d5b0f41` | 2026-08-20T03:09:56.442Z | FAILURE/legacy_report_owner_red | incident=`b2d8f5a1-6c90-4e27-8b13-5f7a0d3c9e62` | lesson_key=`legacy-report-owner-gate` | event_sha256=`2eab5a332bdce668e516a36ebf9b4ec390faf1dfe43571fbec20f0599853160e`
- #3: `c3e9f6b2-7a14-4d80-9e25-6f1b8c3a5d72` | 2026-08-20T03:16:27.672Z | ERROR/legacy_report_host_socket_environment | incident=`d4f0a7c3-8b25-4e91-af36-7c2d9b5e1a83` | lesson_key=`legacy-report-host-socket-boundary` | event_sha256=`f71a8507522ab59d6874fae86bf18c93b93bec552359b9831e907a8d0d52ca05`
- #4: `e5a1c7d9-3f20-4b86-9e14-7c2d5a8f0b63` | 2026-08-20T03:17:23.129Z | REVIEW/legacy_report_owner_green | incident=`f6b2d8a4-7c91-4e35-af20-6d8b3c5a1e74` | lesson_key=`legacy-report-owner-gate` | event_sha256=`267eefa12df9d030c4f54c5551c89efd258da5ab368d4a3da8bea1376050146b`
- #5: `f7c3a9e1-5d20-4b86-8f14-6a2e7c9d0b53` | 2026-08-20T03:19:46.246Z | GATE/remediation_five_focused_gate | incident=`a1f7c3d9-5e20-4b86-9a14-7c2d6f8b0e53` | lesson_key=`report-remediation-focused-gate` | event_sha256=`a34260c92bbadf63577fb87f17c512e13f9608cf5bca3cb8e60396e8cdc6cc6e`
- #6: `b8d4f6a2-7c10-4e95-9f23-6a1c8d5b0e74` | 2026-08-20T03:20:28.479Z | STATE_CHANGE/line_completed | incident=`c9e5a7b3-8f21-4d96-a0c4-7b2e9d5f1a83` | lesson_key=`legacy-report-remediation-line-complete` | event_sha256=`5a978261051f9267c9fc08f6fa98be4424dbacaf4b855a1155ddf989c5cf1511`
- #7: `d9f5b7a3-1c84-4e20-9f62-7a3d5b8c0e14` | 2026-08-20T03:21:18.282Z | REVIEW/legacy_report_owner_red_resolved | incident=`b2d8f5a1-6c90-4e27-8b13-5f7a0d3c9e62` | lesson_key=`legacy-report-owner-gate` | event_sha256=`3303bba0bc55cfbbcfbc3df949b7e29015c8bb5409f210e27d9a0758cc804125`
