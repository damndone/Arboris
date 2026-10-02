# LMM Public Result Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` or `executing-plans` to execute each checkbox in order.

**Goal:** Expose one validated terminal LMM result packet through the generic result reader and a
read-only WO-C presentation contract, without enabling any LMM runtime feature.

**Architecture:** WO-B writes exactly one terminal complete-or-failed envelope at the controlled
run-relative result path and registers it as `model_result_packet`; diagnostics and recovery remain
separate artifacts. A dedicated adapter validates one immutable packet-byte snapshot and makes a
deterministic public projection. The legacy OLS loop remains unchanged; declared invalid LMM packets
fail the whole read atomically.

**Tech Stack:** Python 3.14, pytest, PacketEnvelope, canonical SHA-256. No model fitting, dependency change, registration, route, Agent/UI/Compare integration, candidate merge, or release.

---

The controlling contract is `docs/superpowers/specs/2026-07-19-lmm-public-result-adapter-design.md`; time-series documents are out of scope.

### Task 0: RED WO-B producer contract

**Files:** Modify `backend/workbench/engine/packs/linear_mixed_effects/runner.py`, `result.py`, and
`figures.py`; modify `tests/models/linear_mixed_effects/test_runner.py`.

- [ ] First write RED tests for exactly one `model_result_packet` at `artifacts/model_results/linear_mixed_effects_1.result.json` for a terminal complete fit, returned terminal failure, and unexpected `_fit_prepared` exception. Assert the exception becomes sanitized `LMM_UNEXPECTED_FIT_EXCEPTION` terminal failure, while input-blocked preflight/validation/preparation produces only a blocking diagnostic artifact and no result packet.
- [ ] Add RED result tests: no top-level `result_id`, `estimate`, or `inference_method`; only `coefficients.group_time_interaction` exposes them.
- [ ] Add RED figure tests: canonical `{chart_type,time,groups}` only when all displayed groups have identical sorted observed-time support; otherwise null figure, exactly one `LMM_FIGURE_CONTEXT_UNAVAILABLE_UNBALANCED_TIME` warning diagnostic and matching warning entry, exact bounded evidence, and no truncate/impute/interpolate behavior. Independently recompute `sha256_canonical(sorted observed-time number array)` and the least numeric symmetric-difference member; reject wrong group order, digest, or first difference.
- [ ] Only after those tests are RED, implement the narrowly owned runner, result, and figures changes and run `PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests/models/linear_mixed_effects/test_runner.py -q`.

### Task 1: Strict packet reader

**Files:** Create `backend/workbench/services/lmm_result_adapter.py`; create `tests/test_lmm_result_adapter.py`.

- [ ] Write failing tests that construct exactly one terminal complete or failed LMM envelope at `artifacts/model_results/linear_mixed_effects_1.result.json` plus its real `ArtifactRecord(...).to_dict()` `model_result_packet` entry (including required `config_hash`). Assert diagnostics/recovery artifacts are not projected. Cover bare payload, unknown contract/version, path escape/symlink, oversized or non-normalized path with no raw-path error echo, a second or wrong-path terminal packet, specifically reject `model/lmm_result.json` and every other path for declared new LMM terminal packets, file digest mismatch, duplicate identity, covariance alias mismatch, old `series` FigureContext, invalid canonical vectors, unknown terminal diagnostic code, allowlisted code with wrong severity/status/action-candidate state, and every complete/null-figure case except the exact bounded unbalanced-time warning case.
- [ ] Run `PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests/test_lmm_result_adapter.py -q`; it must fail because the module is missing.
- [ ] Implement only `VersionedResultReadError`, `parse_lmm_result_payload_v1`, and `read_lmm_public_results`. Read the index through pinned descriptors; an unversioned V1 index with no exact `artifact_type="model_result_packet"` stays on the legacy path, while every declared LMM terminal packet requires the exact `ArtifactRecord.to_dict()` index shape including `config_hash` and exact path `artifacts/model_results/linear_mixed_effects_1.result.json`. Enforce the bounded normalized path before emitting it in an error, use one byte snapshot for hash and parse, validate the C1 envelope and WO-B-aligned payload, and create a read-time view. For the unbalanced-time exception validate only the representable closed evidence invariants; do not claim to recompute hidden support arrays. For complete fits require a canonical figure except the exact `LMM_FIGURE_CONTEXT_UNAVAILABLE_UNBALANCED_TIME` warning case; do not translate, truncate, impute, or interpolate. Do not import a fitting library or write artifacts.
- [ ] Repeat the focused pytest command; it must pass.

### Task 2: Legacy reader dispatch

**Files:** Modify `backend/workbench/services/results_service.py`; modify `tests/test_lmm_result_adapter.py`; test `tests/test_ols_result_contract.py`.

- [ ] Write a failing mixed-reader test: a legacy OLS dictionary remains first and byte-for-byte unchanged, a valid indexed LMM view is second, a declared invalid LMM raises `VersionedResultReadError` instead of returning partial OLS results, and unrelated unindexed JSON stays ignored.
- [ ] Run the focused adapter test; it must fail because `read_model_results` only scans top-level legacy coefficients.
- [ ] Preserve the existing legacy loop verbatim, then append `read_lmm_public_results(run_root)`. Do not catch versioned errors and do not alter OLS validation or the OLS-specific analysis-loop resolver.
- [ ] Run `PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests/test_lmm_result_adapter.py tests/test_ols_result_contract.py -q`; it must pass.

### Task 3: WO-B/WO-C assembly boundary

**Files:** Create `frontend/src/workbench/repeatedMeasures/repeatedMeasuresViewModel.ts`,
`PacketPanel.tsx`, `Trajectory.tsx`, their three named tests, and
`__fixtures__/publicModelResults.ts`; modify `tests/test_lmm_extension_seams.py` and
`docs/superpowers/release-trains/v1.7.3/README.md`; create
`docs/superpowers/release-trains/v1.7.3/integration-foundation/lmm-public-result-adapter.md`.

- [ ] Add the read-only, non-registered WO-C presentation adapter only in `frontend/src/workbench/repeatedMeasures/repeatedMeasuresViewModel.ts`, `PacketPanel.tsx`, and `Trajectory.tsx`, with `repeatedMeasuresViewModel.test.ts`, `PacketPanel.test.tsx`, `Trajectory.test.tsx`, and `__fixtures__/publicModelResults.ts`. Tests cover the three presentation states, including failed `LMM_UNEXPECTED_FIT_EXCEPTION`, structural trusted outer metadata, nested coefficient only, the shared closed terminal diagnostic-code allowlist, raw-envelope rejection, and absence of conclusions/recovery/Agent execution. The proposed `frontend/src/features/repeated-measures/...` path is superseded; add a no-parallel-consumer regression assertion.
- [ ] Add tests proving this reader registers no LMM model, Pack, capability, Agent recipe/proposal/execution, route, UI feature, or Compare dispatch; the OLS-specific resolver remains non-LMM.
- [ ] Run `PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests/test_lmm_extension_seams.py -q`; new assertions must pass without a production registry change.
- [ ] Record that WO-B must persist exactly one complete-or-failed terminal envelope at `artifacts/model_results/linear_mixed_effects_1.result.json`, register it as the sole `model_result_packet`, keep diagnostics/recovery distinct, emit canonical `{chart_type,time,groups}` when scientifically representable, and otherwise emit only the stable unbalanced-time warning with `figure_context:null` before its candidate can integrate.
- [ ] Run the focused adapter, seam, OLS-contract, C1-LMM-contract, and canonical-packet suites; run `git diff --check`; verify the two protected Honest-DiD tests have no diff. All must pass before the next foundation task.

No step stages, commits, merges a WO, invokes evaluation, or makes a release claim. Every completed implementation task receives spec-compliance review followed by code-quality review.
