# Retrospective — v1-8-9-p0-agent-context-consumer-cutover

## Goal

# Workbench v1.8.9 P0 Agent context consumer cutover objective  ## Objective  Bring the legacy Agent read-only context consumer suite onto the v1.8.9 server-owned result-artifact contract. Tests that intend to expose verified model facts must create a real artifact index entry, digest, input identity, and self-digesting \`result_binding\` before calling the Agent context tools. Tests that intentionally exercise malformed, running, missing, or otherwise unavailable state must assert the typed unavailable/lifecycle projection instead of expecting a raw \`model_results\` fallback.  The cutover must preserve the production fail-closed boundary: no caller-owned JSON, path, project identity, or inferred model result may become citable evidence. It must not weaken \`_verified_model_results\`, C0 evidence admission, or Report/Notebook projections. The goal is to make the existing consumer suite truthful under the v1.8.9 contract, not to delete coverage or blanket skip failures.  ## Required outcomes  - The previously failing \`tests/test_agent_context_tools.py\` cases either use   a server-shaped persisted artifact fixture or explicitly assert the typed   unavailable/lifecycle state they are designed to cover. - Verified-result tests prove the indexed path, digest, model identity,   source-artifact identity, and payload digest are all present; changing any   one invalidates the projection. - Existing raw-row redaction and malformed/tampered fail-closed assertions   remain active. - No production authority or raw-result fallback is added.  ## Scope  Allowed paths:  - \`tests/test_agent_context_tools.py\` - \`docs/superpowers/objectives/2026-08-20-v1.8.9-p0-agent-context-consumer-cutover-objective.md\` - \`docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-agent-context-consumer-cutover.md\` - \`docs/superpowers/handoff/2026-08-20-v1.8.9-p0-agent-context-consumer-cutover-handoff.md\`  Protected paths include all production backend/frontend code, existing formal devline records, root checkout, other worktrees, and unrelated tests. If a production defect is demonstrated rather than a stale fixture, stop and request an explicit rescope through \`devline_control.py\` before editing it.  ## Baseline and verification  - Exact baseline: \`91ee6a05eab2a1892844c8a3057e1e607359a29e\`. - Focused gate:   \`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -p no:cacheprovider tests/test_agent_context_tools.py -q --disable-warnings\`. - Adjacent typed boundary gate:   \`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -p no:cacheprovider tests/test_v189_central_evidence_consumer_mount.py tests/test_v189_evidence_report_boundary.py -q --disable-warnings\`. - Also run selected-file compile checks and \`git diff --check\`. - Browser, external provider, host-authority/full gate, cross-process,   merge, tag, release, and deployment remain separate \`NOT VERIFIED\` gates.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/6 (16.7%; 16.7 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: N/A (sample=0; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- None recorded.

## All gaps

- #2 2026-08-21T00:42:26.874Z `authority_socket_environment`; cause_status: `external`; cause: The adjacent central evidence suites require a Unix-domain authority socket under the host temporary directory; the current agent sandbox rejects that bind before product code is reached.; resolution: `accepted`; lesson: Run authority-socket and containment-sensitive evidence in the supported host environment; do not weaken product boundaries or treat sandbox failure as a product regression.

## All waste

- None recorded.

## Root causes and solutions

- `authority-socket-environment`: occurrences=1; cause_status: `external`; root cause: The adjacent central evidence suites require a Unix-domain authority socket under the host temporary directory; the current agent sandbox rejects that bind before product code is reached.; solution: `accepted`

## Added tests

- `tests/test_agent_context_tools.py`
- `tests/test_v189_central_evidence_consumer_mount.py tests/test_v189_evidence_report_boundary.py`

## New rules

- `authority-socket-environment`: line experience occurrence(s)=1

## Future guidance

- Run authority-socket and containment-sensitive evidence in the supported host environment; do not weaken product boundaries or treat sandbox failure as a product regression.

## Event index

- #1: `39c8c18e-9458-4641-b0ff-5f71ad21862b` | 2026-08-21T00:22:01.719Z | STATE_CHANGE/line_started | incident=`008d262c-a70b-4070-84c2-bd65acdebf15` | lesson_key=`frozen-context-before-start` | event_sha256=`51416befe1b1f753512c2fde18971e65bd3757020848049c4958d93146087abd`
- #2: `a5555555-5555-4555-8555-555555555555` | 2026-08-21T00:42:26.874Z | GAP/authority_socket_environment | incident=`a6666666-6666-4666-8666-666666666666` | lesson_key=`authority-socket-environment` | event_sha256=`bf50c2d1860ddbab41f674045fea201d1b964a8600e5be7f7b3027d35055d330`
- #3: `c162101d-7f56-408d-8b65-ac3fe4f0cbe3` | 2026-08-21T00:50:43.445Z | STATE_CHANGE/context_rescope_required | incident=`928e3563-39a7-4d63-8ed5-33067fc85d82` | lesson_key=`context-pack-rescope` | event_sha256=`8fbbc1ec3824b38a9265642840268aa39e0e604708af9ee4d3f5f5e99af96ad2`
- #4: `1ef32365-7e0b-4b68-b160-4ed387f15f81` | 2026-08-21T00:50:43.448Z | STATE_CHANGE/context_rescoped | incident=`ecc37feb-0881-4946-b037-46d4c19e92d7` | lesson_key=`context-pack-rescope` | event_sha256=`29c29cb1969705603cdd3a189028edeb4c21c4497ffdea3ed8d9fc281ff461a0`
- #5: `a9999999-9999-4999-8999-999999999999` | 2026-08-21T00:51:23.493Z | GATE/agent_context_fixture_green | incident=`b0000000-0000-4000-8000-000000000000` | lesson_key=`agent-context-fixture-green` | event_sha256=`5abb8a3de68b8680c89f2c690d4e3393ecf3bb08068edea53049fd4c13e1a005`
- #6: `b3333333-3333-4333-8333-333333333333` | 2026-08-21T00:51:58.423Z | STATE_CHANGE/line_completed | incident=`b4444444-4444-4444-8444-444444444444` | lesson_key=`agent-context-cutover-package-complete` | event_sha256=`00cc21862ce02e8d0cadd159709032e7b7872ba7ee457cfeaff666834e4f3b72`
