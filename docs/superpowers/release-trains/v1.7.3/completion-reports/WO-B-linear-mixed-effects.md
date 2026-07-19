# WO-B — Linear Mixed Effects Model Pack completion report

Status: `BLOCKED_PENDING_INTEGRATION_CONTRACT`. The package-local versioned
artifact remediation and strict negative-covariance closure are verified, but
this Lane is not approved, not mechanically integrable, and not released.

## Provenance and boundaries

- Release baseline: `4b2e6c1d9ddd289005b84c186255fec2e9cbd86a`
- Contract lock / branch start: `0251f0a30d984bdbb2cfab404e6c646deab60cae`
- Governance receipt (read-only): `f25ffd119df91479aabfcebcb549a47a1153e227`
- Work package receipt recorded by that governance commit: `2d356d3024570dbf55e7c3ecd2cff1ac5b4e85be`
- Lane / worktree: `feat/v173-model-linear-mixed-effects` / `.worktrees/v173-model-linear-mixed-effects`
- Initial implementation candidate: `211f3addf42034015b06d2e07bf89fad344f99e3`
- Envelope/fail-closed remediation code candidate:
  `e77bc3c0bee1b24af7a1c7f86990baa3102ca008`
- Strict negative-covariance closure code candidate:
  `3e5b9c9d66efc50df074b5548fdbc3940dbd3203`

The code candidates change only the owned pack directory and the three owned
model tests. This report is the Work Order's sole metadata exception. It
changes no public LMM contract, fixture, central registration, Agent/UI code,
gate script, or protected Honest-DiD test.

## Candidate contents

Initial candidate commit `211f3addf42034015b06d2e07bf89fad344f99e3` adds:

- `backend/workbench/engine/packs/linear_mixed_effects/__init__.py`
- `backend/workbench/engine/packs/linear_mixed_effects/declaration.py`
- `backend/workbench/engine/packs/linear_mixed_effects/input.py`
- `backend/workbench/engine/packs/linear_mixed_effects/runner.py`
- `backend/workbench/engine/packs/linear_mixed_effects/result.py`
- `backend/workbench/engine/packs/linear_mixed_effects/diagnostics.py`
- `backend/workbench/engine/packs/linear_mixed_effects/figures.py`
- `tests/models/linear_mixed_effects/test_input.py`
- `tests/models/linear_mixed_effects/test_runner.py`
- `tests/models/linear_mixed_effects/test_diagnostics.py`

Remediation commit `e77bc3c0bee1b24af7a1c7f86990baa3102ca008` adds the
pack-local `packets.py` boundary and changes only owned pack/test files. It
returns and persists C1 `PacketEnvelope` wire values rather than a bare result
dict:

- successful fits return and persist `linear_mixed_effects.result@1.0`, whose
  payload contains the canonical success facts (`status`, `result_id`,
  `estimate`, `fit_method`, `inference_method`) plus the locked data-only
  `figure_context` member;
- every normalized result also persists a
  `linear_mixed_effects.diagnostic@1.0` packet; a recovery packet is persisted
  only when the existing locked confirmation-required candidate exists;
- no standalone figure packet or new public contract was created: C1 defines
  `figure_context` only as a result-payload member;
- invalid covariance/residual facts are terminal
  `LMM_CONVERGENCE_FAILED` facts, never recovery candidates; and existing
  `LmmInputError` code/evidence is persisted as a terminal diagnostic before
  being re-raised to the lifecycle owner.

The declaration carries the locked `linear_mixed_effects@1.0` / contract `1.0`
owner facts, but it is intentionally not added to the central builtin loader.
Registration is **not** a mechanical Integration step: the required
cross-Lane packet adapter has not yet been specified or approved.

## RED → GREEN evidence

1. L1 began at the lock commit on the required branch with a clean worktree;
   `git diff --check` was silent. The owned model-pack directory and its three
   tests were absent. The immutable contract tests, fixtures, and feasibility
   guard were present.
2. Preimplementation command (required):

   ```bash
   PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest -q \
     tests/models/linear_mixed_effects/test_input.py
   ```

   Result: expected failure — `no tests ran` and `ERROR: file or directory not
   found: tests/models/linear_mixed_effects/test_input.py`.
3. Subsequent test-first RED evidence included the missing `input`,
   `diagnostics`, and `runner` modules, invalid nonnumeric time/outcome/control,
   invalid group/repeated-observation/random-slope designs, absent trajectory
   series time, and a fake non-converged fit with no `conf_int`. Each was made
   green with the smallest pack-local implementation change.
4. The envelope remediation was also test-first. RED evidence was: a real known-truth
   runner result rejected by `PacketEnvelope.from_dict()` as a bare dict;
   one-row, NaN, asymmetric, or non-finite-residual random-slope diagnostics
   failed to use the locked terminal path; and missing-subject/invalid-slope
   errors did not create a diagnostic artifact. Their corresponding pack-local
   assertions passed after the remediation.
5. The strict-negative-covariance closure was test-first. RED evidence was
   `[[1.0, 0.0], [0.0, -1e-9]]` being accepted under the former tolerance as a
   near-zero recovery candidate. GREEN requires every negative diagonal
   variance or negative covariance eigenvalue to fail before the near-zero
   threshold is considered. A direct diagnostics assertion and a runner probe
   that persists the result and diagnostic assert `failed/error`, no action
   candidate, empty coefficients, no figure context, and no recovery artifact.
   Existing zero and positive near-zero covariance recovery assertions remain
   green.
6. Final locked verification command:

   ```bash
   PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest -q \
     tests/models/linear_mixed_effects/test_feasibility.py \
     tests/models/linear_mixed_effects/test_input.py \
     tests/models/linear_mixed_effects/test_runner.py \
     tests/models/linear_mixed_effects/test_diagnostics.py \
     tests/contracts/test_lmm_contracts.py \
     tests/contracts/test_lmm_error_contract.py \
     tests/contracts/test_lmm_canonical_packets.py \
     tests/test_model_options_owner_binding.py \
     tests/test_lmm_extension_seams.py
   ```

   Result: `127 passed, 7 warnings in 12.60s`. The feasibility spike's direct
   statsmodels calls account for the LMM covariance/boundary warnings; the
   extension seam also emits existing FastAPI deprecation warnings. The pack
   suppresses estimator warnings from its caller, but does not parse warning
   text: its diagnostic facts are determined from explicit convergence and
   finite/symmetric/shape-checked covariance and residual facts.
7. `git diff --cached --check` was silent before the remediation code commit. A staged
   protected-file audit over all read-only and forbidden paths was also silent.

## Statistical and runtime observations

- Known-truth REML random-slope interaction: `0.940473570655`; locked truth is
  `0.9` with tolerance `0.35`.
- Deterministic result identity for that fixture:
  `2fa7a9f218ef35aa71d97e954699bdf1a7c216a656bde951ef24768d30cb373e`.
- Three direct known-truth fits took `0.166159s`, `0.163529s`, and `0.164774s`
  on this lane (`Python 3.14.6`, `statsmodels 0.14.6`, Darwin `24.1.0`). This
  is an observation, not a release performance claim.
- The known-truth covariance is classified as
  `LMM_RANDOM_EFFECTS_SINGULAR`, complete/warning, with the only locked,
  confirmation-required simplify-random-effects candidate. The associated
  result, diagnostic, and recovery artifacts are individually parsable C1
  envelopes.
- Non-convergence emits `LMM_CONVERGENCE_FAILED`, `failed/error`, no recovery
  candidate, no coefficient claim, and no trajectory context.
- The new persisted negative-variance probe uses
  `[[1.0, 0.0], [0.0, -1e-9]]` and emits that same terminal outcome before any
  coefficient, figure, or recovery construction. Exact zero and nonnegative
  near-zero matrices remain eligible for the existing singular/recovery path.

## Protected-file audit

The candidate has no diff in:

- all C1 common/model/agent contract files;
- `tests/contracts/test_lmm_contracts.py`,
  `tests/contracts/test_lmm_error_contract.py`,
  `tests/contracts/test_lmm_canonical_packets.py`, immutable fixtures, or
  `tests/models/linear_mixed_effects/test_feasibility.py`;
- all Work Order forbidden central, Agent, UI, graph, gate, and Honest-DiD
  paths.

No provider, API key, browser calculation, push, PR, merge, tag, or release
action was used.

## Integration contract blocker

The attempted P1-1 lifecycle probe established a cross-Lane public boundary:

- `EstimationStage` writes its returned primary value into `model_results`.
- `http/runs_routes.py` returns `model_results` over HTTP.
- `agent/context_tools.py` and `analysis_loop/resolver.py` consume
  `read_model_results`.

Therefore `model_results` is not a pack-private legacy sink. Returning a bare
`legacy_primary_payload` there would make an unversioned value available to
HTTP, Agent, and analysis-loop/Compare consumers; returning the C1 envelope
there is dropped by the legacy reader because it lacks top-level
`coefficients`. C1 defines versioned LMM packets but no versioned adapter for
this public transport. The tentative bare-payload workaround and its test were
discarded; no central, contract, or fixture change is present in this Lane.

Integration must make and implement a separately reviewed decision before this
pack can be enabled:

1. Define the public source of truth and an end-to-end versioned adapter for
   the EstimationStage → model-results → HTTP/Agent/analysis-loop path (or a
   distinct public versioned artifact/reader); it may not merely relabel
   `model_results` as internal.
2. Specify any legacy compatibility representation, ownership, and atomic
   correspondence to the packet, including how old readers avoid dropping
   coefficients without becoming public consumers of an unversioned payload.
3. Add central contract and integration acceptance tests for that chosen
   transport, then wire the builtin loader/capability registry only after the
   adapter is approved.

Until those decisions exist, the package's result, diagnostic, and recovery
files are versioned pack artifacts with local evidence only. They do not make
the Lane ready for Agent, UI, Compare, lifecycle, independent evaluation, or
release approval.

## Known package limits

- Scope is intentionally limited to a continuous outcome, numeric continuous
  time, exactly two retained groups, random intercept plus optional random time
  slope, selected numeric controls, ML/REML, and the locked interaction target.
- No GLMM, categorical time, more than two groups, nested/crossed effects,
  arbitrary selection, custom code, UI/Agent registration, or independent
  evaluation is included.
- `singular_random_slope.csv` is fail-closed as
  `LMM_INVALID_RANDOM_SLOPE_CONFIGURATION` because time is constant within
  each subject. Covariance singularity is separately classified by the
  deterministic diagnostics function.
- A standalone `linear_mixed_effects.figure` public contract is intentionally
  absent from C1. The data-only trajectory remains in the versioned result
  payload; Integration must not invent a second figure contract while defining
  the missing lifecycle adapter.
- The package has lane-local and immutable-contract evidence, but is blocked
  before WO-D evaluation until an Integration contract and exact integration
  SHA exist.

## Rollback

Before Integration, omit this declaration from the central builtin list and do
not introduce a Lane-local workaround for `model_results`. The standalone
negative-covariance closure can be rolled back independently by reverting
`3e5b9c9d66efc50df074b5548fdbc3940dbd3203`; removing the package candidates entirely then reverts
`e77bc3c0bee1b24af7a1c7f86990baa3102ca008` and
`211f3addf42034015b06d2e07bf89fad344f99e3` (plus their report receipts) in
reverse order. Any future Integration adapter must be a separate, reversible
commit and be rolled back before these package commits. No data migration or
external resource cleanup is required.
