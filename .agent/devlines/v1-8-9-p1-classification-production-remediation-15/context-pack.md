# Frozen Context Pack

Line: `v1-8-9-p1-classification-production-remediation-15`
Baseline SHA: `30f3adb9263cb009ec39174b0ff6597eeb00bf73`

## Objective
# Workbench v1.8.9 P1 Classification Production Remediation 15 Objective

Close the independent code-quality review blocker at exact tip
`30f3adb9263cb009ec39174b0ff6597eeb00bf73` without changing the repository
root or any other worktree. Keep remediation-14's descriptor-based integrity
seam and make the generic artifact download a bounded, compatible stream.

## Required behavior

- Keep `backend/workbench/repository/file_integrity.py` as the single
  server-owned path/open/fstat seam. Generic downloads must hash and stream
  from the same safely opened FD; they must not call `read_bytes_and_sha256`,
  allocate the whole artifact, or use `b''.join` for the response body.
- Use an explicit `64 KiB` maximum stream chunk and an explicit `512 MiB`
  maximum generic artifact stream size. Reject an indexed artifact larger than
  the policy before returning a response with a typed non-success boundary;
  do not silently truncate or spill unbounded memory.
- Make the stream generator close its FD in `finally` on success, normal
  client exhaustion, open/hash/read error, and iterator failure. Every emitted
  chunk must be bounded. During hashing and streaming, an inode, device, or
  size change must fail closed and must not yield further bytes.
- Restore the old generic download compatibility surface: MIME `Content-Type`,
  `Content-Disposition`, `Content-Length`, `Accept-Ranges: bytes`, and explicit
  byte-range semantics. Preserve single and multipart range behavior where
  the old `FileResponse` provided it; malformed or unsatisfiable ranges must
  have explicit 400/416 responses rather than silently returning a full file.
- Add direct unit/integration probes for intermediate-directory symlinks,
  open/read exceptions with FD cleanup, read-time inode/size replacement,
  valid large bounded streaming, response headers, and range behavior.
  Replacement callbacks must patch live symbols with `raising=True` and assert
  observed execution. Existing classification consumer, artifacts-index
  list, path/type/digest, duplicate, non-regular, symlink, and 500/503
  boundaries must remain unchanged.

## Formal and verification boundaries

Use the unique formal line
`v1-8-9-p1-classification-production-remediation-15`, created only through
`scripts/devline_control.py start`, with exact baseline
`30f3adb9263cb009ec39174b0ff6597eeb00bf73`.

Required evidence is TDD RED before production changes, then focused generic
stream/range/cleanup/TOCTOU tests, classification production and contract
suites, `compileall`, `git diff --check`, formal verify, retrospective, and an
exact handoff. Known inherited gates remain the API artifacts async fixture
failures, the v1.8.6 legacy consumer fixture failure, and the non-canonical
artifact-integrity fixture failures. Browser, external provider, central,
host, full-gate, merge, tag, and release acceptance remain `NOT VERIFIED`.

## Scope

- `backend/workbench/repository/file_integrity.py`
- `backend/workbench/http/runs_routes.py`
- `tests/test_v189_classification_production.py`
- `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-classification-production-remediation-15-objective.md`
- `docs/superpowers/plans/2026-08-20-v1.8.9-p1-classification-production-remediation-15.md`
- `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-production-remediation-15-handoff.md`
- the new remediation-15 formal records

Do not modify `backend/workbench/predictive_research/consumer_projection.py`,
`backend/workbench/repository/run_repository.py`,
`backend/workbench/prediction.py`, `backend/workbench/reporting.py`,
`backend/workbench/http/notebook_routes.py`,
`backend/workbench/predictive_research/persistence.py`, remediation-14 or
remediation-13 formal records, the repository root, or any other worktree.

## Boundary
- Affected paths: `backend/workbench/repository/file_integrity.py`, `backend/workbench/http/runs_routes.py`, `tests/test_v189_classification_production.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-classification-production-remediation-15-objective.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p1-classification-production-remediation-15.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-production-remediation-15-handoff.md`
- Allowed paths: none
- Protected paths: `backend/workbench/predictive_research/consumer_projection.py`, `backend/workbench/repository/run_repository.py`, `backend/workbench/prediction.py`, `backend/workbench/reporting.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/predictive_research/persistence.py`, `.agent/devlines/v1-8-9-p1-classification-production-remediation-14/context-pack.md`, `.agent/devlines/v1-8-9-p1-classification-production-remediation-14/events.jsonl`, `.agent/devlines/v1-8-9-p1-classification-production-remediation-14/RETROSPECTIVE.md`
- Dependencies: none
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_classification_production.py -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_classification_production.py -q -k "stream or range or cleanup or mutation or symlink"`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/predictive_research/test_classification_contracts_v189.py tests/predictive_research/test_classification_protocol_v189.py tests/predictive_research/test_classification_leakage_v189.py tests/predictive_research/test_classification_consumers_v189.py -q`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests`, `git diff --check`
- Known gates: `tests/test_api.py -q -k artifacts retains 2 async fixture failures`, `tests/predictive_research/test_consumer_projection_v186.py retains 1 legacy fixture failure`, `tests/test_v189_artifact_integrity.py retains 3 non-canonical fixture failures`, `browser/provider/central/host/full-gate/release are NOT VERIFIED`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-9-p0-agent-compiler-remediation-5 (2026-08-19T02:35:17.000Z)

Completed formal devline v1-8-9-p0-agent-compiler-remediation-5; final_state=COMPLETED; failure_lesson_keys=os-boundary-probes-need-controlled-sandbox-access

### v1-8-9-p0-workflow-truth-remediation-6 (2026-08-16T16:15:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-6; final_state=COMPLETED; failure_lesson_keys=formal-output-registration-transaction, register-child-run-model-artifacts, runtime-fixture-model-preconditions, use-declared-model-minimum

### v1-8-9-p0-legacy-compilation-authority-cutover (2026-08-16T14:30:00.000Z)

Completed formal devline v1-8-9-p0-legacy-compilation-authority-cutover; final_state=COMPLETED; failure_lesson_keys=legacy-authority-red-before-implementation, legacy-cutover-keeps-host-dependency-explicit

### v1-8-9-p0-workflow-truth-remediation-5 (2026-08-16T13:35:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-5; final_state=COMPLETED; failure_lesson_keys=production-host-integration-boundary, runtime-artifact-no-follow, workflow-remediation-5-red-before-fix

### v1-8-9-p0-evidence-core-remediation-7 (2026-08-16T12:56:51.000Z)

Completed formal devline v1-8-9-p0-evidence-core-remediation-7; final_state=COMPLETED; failure_lesson_keys=evidence-host-trust-root, typed-timeout-boundary

### v1-8-8-agent-chain-hardening (2026-08-10T01:59:47.000Z)

Completed formal devline v1-8-8-agent-chain-hardening; final_state=COMPLETED; failure_lesson_keys=host-gate-calendar-and-projection, host-gate-integration-before-claim, manual-browser-coverage-gap, qa-runner-is-not-cryptographic-witness, report-upstream-retry-visible, typed-failure-fail-closed

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required
