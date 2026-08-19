# Retrospective — v1-8-9-p0-evidence-core-remediation

## Goal

# v1.8.9 P0 Evidence Core Remediation Objective  Remediate independently verified Evidence Core authority and persistence-integrity failures before integration admission. Registry admission must issue the only persistence authority; direct caller-created ArtifactAdmission records must not commit. Persisted packet/index metadata must be content-bound and tamper-detected, raw path-like provenance must be rejected before write, packet versions must be validated, invalid refs must produce stable failure outcomes, and projections must be deeply immutable. Preserve the locked C0 envelope and package-local boundary.  Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749 Remediation line: v1-8-9-p0-evidence-core-remediation Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-evidence-core  Required outcomes: adversarial authority/tamper/path/version/deep-mutation probes fail closed; focused tests and formal handoff reflect actual evidence. Do not touch runtime, consumers, central catalog or protected paths.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/8 (25.0%; 25.0 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: N/A (sample=0; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-16T10:16:54.000Z `tdd_red_evidence_core_remediation_bypasses`; cause_status: `known`; cause: The existing Evidence Core implementation admits persistence from a public ArtifactAdmission type without a registry receipt, hashes only the envelope, permits path-like provenance and forged packet versions, constructs invalid-id failure receipts from unvalidated input, and shallow-freezes projection mappings.; resolution: `open`; lesson: Keep registry authority separate from public record construction and bind every persisted metadata field before claiming a focused green result.
- #3 2026-08-16T10:23:37.000Z `test_expectation_stale_after_complete_hash_binding`; cause_status: `known`; cause: The focused suite exposed a stale replay-conflict assertion: after binding the complete artifact metadata, a different artifact_id correctly produces a different content hash and is not a replay conflict.; resolution: `open`; lesson: When a security-bound identity hash changes, update replay tests to exercise an actual immutable destination conflict.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `evidence-core-remediation-red-bypass-tests`: occurrences=1; cause_status: `known`; root cause: The existing Evidence Core implementation admits persistence from a public ArtifactAdmission type without a registry receipt, hashes only the envelope, permits path-like provenance and forged packet versions, constructs invalid-id failure receipts from unvalidated input, and shallow-freezes projection mappings.; solution: `open`
- `replay-test-must-follow-complete-artifact-hash`: occurrences=1; cause_status: `known`; root cause: The focused suite exposed a stale replay-conflict assertion: after binding the complete artifact metadata, a different artifact_id correctly produces a different content hash and is not a replay conflict.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `evidence-core-remediation-red-bypass-tests`: line experience occurrence(s)=1
- `replay-test-must-follow-complete-artifact-hash`: line experience occurrence(s)=1

## Future guidance

- Keep registry authority separate from public record construction and bind every persisted metadata field before claiming a focused green result.
- When a security-bound identity hash changes, update replay tests to exercise an actual immutable destination conflict.

## Event index

- #1: `89e59647-e346-4d27-b63e-6ffd8d4f6421` | 2026-08-16T10:09:26.483Z | STATE_CHANGE/line_started | incident=`74c97dbb-00df-4620-b09a-db277e1012b3` | lesson_key=`frozen-context-before-start` | event_sha256=`dc49a5e0a1e8380a061e7c55efe947bcd61dacd2cbe93c562da10b43a710eb22`
- #2: `eb290ef7-88b9-480d-a63b-0a3d6bdf5361` | 2026-08-16T10:16:54.000Z | FAILURE/tdd_red_evidence_core_remediation_bypasses | incident=`30757643-15e5-41cc-99fd-7e9d6c565827` | lesson_key=`evidence-core-remediation-red-bypass-tests` | event_sha256=`edff192ad78ac65a006e81e30e222f66378baed4bc8f6ea921becf7ff0c4196b`
- #3: `50598b58-c715-4c28-ad96-6c972ad29c95` | 2026-08-16T10:23:37.000Z | FAILURE/test_expectation_stale_after_complete_hash_binding | incident=`dc74057a-ccf9-4411-8f29-df61bb2cf2d6` | lesson_key=`replay-test-must-follow-complete-artifact-hash` | event_sha256=`2fe0741c180b68712895e30606aa08c76b41f2afa325c2cabc857243c9dbfe00`
- #4: `2c31b1a0-5ab8-4cbf-8bd0-71bb12a2e8fa` | 2026-08-16T10:27:17.000Z | GATE/evidence_core_remediation_targeted_gate | incident=`4a7fa8a6-e928-4c9f-a7c2-9b9a0d0e5b4f` | lesson_key=`evidence-core-focused-gate-is-not-integration-gate` | event_sha256=`f750bd3235a18fd9dce1e5d309ea7c4a91add9199e77fc16465e17d451b396ba`
- #5: `f1d1c6b0-2c34-4bf6-bcb0-4a8ad1f36e0c` | 2026-08-16T10:27:17.000Z | STATE_CHANGE/remediation_line_completed_with_concerns | incident=`d3f24e67-0a62-4ef2-a5b8-8a8d1df55944` | lesson_key=`close-line-with-explicit-unverified-boundaries` | event_sha256=`6be7c378995a4f6e0ff35659186e68b6c0f7eb327db9a13ffccc494b509f73be`
- #6: `d4f5e36d-0cb6-4acf-9bf3-66d0d8612a0b` | 2026-08-16T10:29:41.000Z | STATE_CHANGE/structured_provenance_review_reopened_line | incident=`f77a2c49-5cb0-4b36-9f18-40ae1bd7c91c` | lesson_key=`structured-provenance-path-review` | event_sha256=`3a7c8d9ed9ab8a17086beb98df46ce9d0762a3d922a7f10a52b9f162e1010f17`
- #7: `7a8f0f88-5c2a-4c0e-8b71-3dbb12b24b31` | 2026-08-16T10:30:06.000Z | GATE/evidence_core_remediation_final_targeted_gate | incident=`c2872cf4-a50a-46a3-a734-99f0a4dc0f8d` | lesson_key=`rerun-focused-gate-after-structured-provenance-review` | event_sha256=`7ea50616858eef11d18a2cb07be8f5aa0de1f0f2c6836f10c4d958142e74eae9`
- #8: `3e3b8f0f-1d39-4cae-9cdb-8d34e3a443bc` | 2026-08-16T10:30:06.000Z | STATE_CHANGE/remediation_line_finally_completed_with_concerns | incident=`cbf78d6b-5ee1-4a49-9f45-d85fba29f07c` | lesson_key=`completion-binds-final-hardening-evidence` | event_sha256=`ea318a164dde23bd920996c41e70818acc8c6e63b3799c8af712f68a1149f84f`
