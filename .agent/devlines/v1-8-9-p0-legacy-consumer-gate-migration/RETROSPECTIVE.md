# Retrospective — v1-8-9-p0-legacy-consumer-gate-migration

## Goal

# Workbench v1.8.9 P0 legacy consumer gate migration  ## Objective  Migrate the legacy full-gate tests that still assume v1.8.8 raw-result, unbound-report, or untyped proposal-store behavior to the v1.8.9 typed server-owned contracts. The migration must make the tests exercise the current owner-bound evidence and proposal capability boundaries; it must not restore a raw model-result fallback, accept an unbound report mapping, or make an absent server authority look available.  ## Success criteria  1. The focused legacy consumer/report/lifecycle/golden command passes or    records only explicitly expected typed-unavailable outcomes with stable    evidence. 2. ARMA-GARCH report tests use the existing typed report-document adapter and    server-owned test fixture. 3. Consumer projection tests use the central typed reader rather than the    removed \`_model_results\` hook. 4. Analysis-loop lifecycle tests construct a server-issued proposal-store    capability through the supported test seam. 5. Golden snapshots record the current typed report/evidence contract without    hiding or deleting error states. 6. No production trust boundary is weakened and no arbitrary path, executor,    raw mapping, or caller-owned authority is admitted.  ## Non-goals  - No new statistical estimator or model family. - No report renderer fallback to raw mappings. - No production host/provider/browser/release acceptance claim.  ## Required verification  \`\`\`text PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/pytest -p no:cacheprovider tests/models/arma_garch/test_deliverables.py tests/predictive_research/test_consumer_projection_v186.py tests/test_agent_analysis_loop_lifecycle.py tests/test_engine_golden.py tests/test_statistical_exploration_golden.py -q --disable-warnings \`\`\`  Also run selected-file compileall, \`git diff --check\`, and the formal devline verification/retrospective. Full host gate, browser/provider acceptance, and release remain separate gates.

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
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T23:09:26.158Z `legacy_consumer_gate_failures`; cause_status: `known`; cause: The focused legacy consumer, report, lifecycle, and golden suites still assert pre-v1.8.9 raw-result, unbound-report, or untyped proposal-store behavior.; resolution: `open`; lesson: Migrate stale tests to the typed server-owned contract instead of restoring raw-result or unbound-authority fallbacks.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `typed-consumer-gate-migration`: occurrences=1; cause_status: `known`; root cause: The focused legacy consumer, report, lifecycle, and golden suites still assert pre-v1.8.9 raw-result, unbound-report, or untyped proposal-store behavior.; solution: `open`

## Added tests

- `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-consumer-gate-migration-handoff.md`
- `tests/models/arma_garch/test_deliverables.py`
- `tests/models/arma_garch/test_deliverables.py;tests/predictive_research/test_consumer_projection_v186.py;tests/test_agent_analysis_loop_lifecycle.py;tests/test_engine_golden.py;tests/test_statistical_exploration_golden.py`

## New rules

- `typed-consumer-gate-migration`: line experience occurrence(s)=1

## Future guidance

- Do not invent a typed export capability that production does not issue; keep positive coverage on the existing adapter and test unsupported raw inputs as fail-closed.
- Migrate stale tests to the typed server-owned contract instead of restoring raw-result or unbound-authority fallbacks.

## Event index

- #1: `d09976d9-57ab-414c-baad-7cc0982f4c80` | 2026-08-20T23:08:03.423Z | STATE_CHANGE/line_started | incident=`ca0ec07e-f7bc-46d8-bb1f-fef0533295a9` | lesson_key=`frozen-context-before-start` | event_sha256=`43cf8a0596fb30c959f8f31e65ecb212c1652bbeabded20d0071416694e11c7d`
- #2: `6b6d0dc9-945a-4a43-8a8a-d741f12c0b58` | 2026-08-20T23:09:26.158Z | FAILURE/legacy_consumer_gate_failures | incident=`5a99f77e-742a-4e7d-9f64-22a76aabdb3f` | lesson_key=`typed-consumer-gate-migration` | event_sha256=`b5f276197f6af9535c1a0e70574a0a3d3fde6b02375cca1a3ac9e9fc2f99d151`
- #3: `6cdd3a84-0b63-4e1f-9f4c-b6dc4f7ef4ae` | 2026-08-20T23:56:28.149Z | GATE/legacy_consumer_gate_migrated | incident=`9a08c607-44de-4b1d-a23d-8a3bf31b2857` | lesson_key=`typed-consumer-gate-migration` | event_sha256=`160206998801b23f2b407919752ea25acae6115d02d0aae2e57760921a447c1f`
- #4: `d5e0bbde-f20a-4b35-a2d1-3d0d8e7a90d1` | 2026-08-21T00:02:07.452Z | GATE/host_bound_writer_boundary_preserved | incident=`a7b3d3bf-c7c0-491f-87ad-80f7b2d42cb0` | lesson_key=`host-bound-acceptance-separate` | event_sha256=`309918ae95bc794a44ecf1186610bf3fac0ca561799340d656c737f6c421667e`
- #5: `6c65e00d-8ac8-45ef-900e-1f120852bf3a` | 2026-08-21T00:10:20.227Z | REVIEW/p0_legacy_consumer_re_review | incident=`d1dcdb32-cc2e-4c0b-bb6c-6b36dfc09377` | lesson_key=`scope-typed-export-adapter` | event_sha256=`ab2d03a18ee75b30f07277c698b97029f4449b6db56be4a9458e16a7a50edfce`
- #6: `5c75e8c5-9678-44cf-a54e-a08ed8e1df37` | 2026-08-21T00:10:41.690Z | STATE_CHANGE/line_completed | incident=`9d17fcbf-6f33-4d10-9be4-6a79c5975d66` | lesson_key=`close-scoped-line-with-explicit-gates` | event_sha256=`eb559eb6591acf2e701fbfe60878b76d1a0d38b56107d0ac50bed276cf363274`
