# remediation-4 findings

## Initial read-only findings

- Exact target tip before remediation-4: `7329ccda9dd17f083a56066c77993ff1d1f25808`.
- Predecessor remediation-3 is complete as a separate formal line; its handoff
  records package-local evidence only and leaves browser/provider/central/host/
  full-gate/release boundaries `NOT VERIFIED`.
- `build_persisted_evidence_report_view` currently accepts a caller-created
  `ReportEvidenceRequestIdentityV1` plus a typed artifact admission and emits
  facts/digest without receiving the exact owner capability.
- `_evidence_wire_fields` and related index readers use truthy fallback across
  outer and nested records; an invalid present outer value can be hidden by a
  valid nested value.
- `frontend/src/report/factTable.ts` currently validates a candidate by
  recomputing `reportProjectionDigest(candidate)`, which permits a forged pair
  when the candidate carries complete self-consistent provenance.

## Hypotheses to test

1. The first backend RED probe will demonstrate that a valid projection and
   caller-created identity can reach the report view without owner admission.
2. The wire RED probe will demonstrate that present-but-empty outer fields are
   silently replaced by nested fields.
3. The frontend RED probe will demonstrate that a forged facts/digest pair is
   accepted when the parser has no independent server-bound expected evidence.

## Confirmed RED evidence

- Default sandbox: `5 failed` at the real Unix authority socket bind with
  `PermissionError: [Errno 1] Operation not permitted`; no probe assertion ran.
- Controlled host rerun: `5 failed, 51 deselected, 1 warning`.
  - owner/request probes failed at the current function signature with
    `TypeError: unexpected keyword argument 'owner'`;
  - all three outer-invalid/nested-valid probes returned `status=available`,
    proving the current truthy fallback bypass.
- The identical controlled harness therefore provides implementation RED
  evidence; the default-sandbox result is recorded separately as an external
  environment gate.

## Confirmed GREEN and controlled-host acceptance

- Owner/request and `object.__new__` probes: `2 passed`; strict invalid outer
  binding/envelope/envelope-ref probes: `3 passed` in the socket-capable
  controlled host harness.
- Frontend forged facts plus caller-recomputed digest: `1 failed` RED before
  the receipt gate, then `11 passed` in the boundary suite and `6 passed` in
  the workspace receipt suite after the server-bound receipt check.
- Real controlled HTTP host receipt probes: `2 passed`; the response receipt
  kind, projection digest, and provenance match the typed Report projection.
- Complete controlled backend evidence/report/export/event focused suite:
  `119 passed, 1 warning`. The strict event pair remains `17 passed`.
- Frontend focused boundary/workspace/ReportView/FamilyEvidence/TableView
  suite: `74 passed, 9 skipped`; `npm run typecheck` passed; targeted
  `compileall` and `git diff --check` passed.
- The default sandbox's Unix authority socket `PermissionError` is an
  environment boundary only. The identical host-dependent probes and final
  suite passed in the controlled socket-capable environment.
- Root remains untouched by this line: its pre-existing dirty
  `FamilyEvidence.test.tsx`, `TableView.test.tsx`, and `.formal/` were only
  inspected; all remediation-4 changes are in this worktree.
