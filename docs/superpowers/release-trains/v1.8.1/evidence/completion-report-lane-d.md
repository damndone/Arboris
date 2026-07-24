# Completion Report — Lane D, Independent Evaluation Harness (v1.8.1)

ADR-PD-001 §10.2 — the seven required items.

- **Lane:** `evaluation` (Independent Evaluation Lane, ADR §7D)
- **Branch / worktree:** `test/v181-evaluation-harness` in `.worktrees/v181-evaluation-harness`
- **Branch tip at report:** `b3f6a263d339ad11e5fabb5c86de297394854b7e`
- **Contract lock (C1):** `481fc2e30730395093fc0f8699843e1002d64aa3`
- **Evidence manifest:** [`eval-v181-ets-001.yaml`](./eval-v181-ets-001.yaml)

---

## 1. What was implemented / what was not

**Implemented (this session, resuming a session-limit cutoff):**

- **Reconciled findings F-1 and F-2** with Integration's repairs. Each finding's
  test now *asserts the repaired behaviour* and is gated with the harness's own
  strict-`xfail` idiom keyed on a runtime probe of the current contract
  behaviour (`_ic_fixture_repaired()`, `_option_contract_rejects_unknown_fields()`).
  Where the repair has landed the test must pass on its merits; where it has not
  (this worktree), the finding is reported as `xfailed`, never a vacuous pass.
  The full finding narrative is preserved in each test's docstring and in the
  manifest.
- **Wrote the two missing producer-bound checks** (`test_producer_seams.py`),
  giving the two reserved capability probes a consumer: a real 3-option batch
  must stay all-fresh and self-consistent (spec §4.0 self-reference), and a real
  cross-family ETS↔ARMA-GARCH compare must refuse to rank by AIC (contract
  point 3). Both drive the *public* seam and report a signature mismatch as a
  contract gap (never patch); both are strict-`xfail` while the Agent lane /
  compare adapter are absent.
- **Produced the Evaluation Evidence Manifest** (§12.3 structure) with real
  command output, exit code, durations, and sha256s of the output artifact, the
  canonical + evaluation fixtures, and the four reproducible known-truth oracle
  series.
- **Wrote this completion report** (§10.2).

**Inherited from the prior (cut-off) agent, reviewed and kept as-is:**

- Contract-validation suite (`test_contract_validation.py`): round-trip,
  execution-pin matching, merged-hash rejection, fingerprint prefix/enum
  guards, artifact-contract DEC-ART-001 checks, ETS canonical-string identity,
  smuggled-volatility-parameter rejection.
- Known-truth harness (`ets_known_truth.py` + `test_ets_known_truth.py`): four
  reproducible ETS DGP oracles with an independent statsmodels secondary oracle.
- Fault injection (`fault_cases.py` + `test_ets_fault_injection.py`): interior
  gap, edge NaNs (legal, counted), too-short-for-trend/seasonal, degenerate
  constant / exact line, non-finite value, multiplicative-on-non-positive, and
  seven illegal specifications.
- Adversarial checkers (`checks.py`) + their meta-tests
  (`test_checkers_detect_their_own_bugs.py`): every checker proven against a
  counterexample.
- Numerically justified tolerances (`tolerances.py`) with a recorded Monte-Carlo
  calibration and discriminating-power argument.

**Not implemented (out of scope / blocked on absent lanes, honestly deferred):**

- Any *green* known-truth / fault / cross-family / self-reference result against
  a real producer: the ETS Model Pack, the Agent option-batch generator, and a
  cross-family compare adapter do not exist at this commit. Those checks run and
  are reported as `xfailed`, awaiting the named lane. They are **not** vacuous
  passes.
- Browser E2E: the UI lane is absent; there is no browser path to evaluate.
  Recorded as `not_applicable` in the manifest, not as `passed`.

## 2. Files changed and commits

Commit `b3f6a26` (this session):

- `tests/evaluation/v181/test_contract_validation.py` — F-1/F-2 reconciliation:
  added repair probes + strict-xfail markers, refreshed docstrings.
- `tests/evaluation/v181/test_producer_seams.py` — new; two producer-bound tests.

Documentation commit (this report + manifest):

- `docs/superpowers/release-trains/v1.8.1/evidence/eval-v181-ets-001.yaml`
- `docs/superpowers/release-trains/v1.8.1/evidence/artifacts/pytest-eval-v181-ets-001.txt`
- `docs/superpowers/release-trains/v1.8.1/evidence/completion-report-lane-d.md`

Prior WIP commit `3e346c4` carried the harness the cut-off agent had already
written (all files listed under §1 "Inherited").

## 3. Contracts touched / which lock

**None.** No contract was modified. The lane consumes the C1-locked contracts
read-only:
`backend/workbench/contracts/model/ets.py`,
`backend/workbench/contracts/agent/notebook_option.py`,
`backend/workbench/contracts/common/envelope.py`, and the canonical fixtures in
`tests/fixtures/contracts/v181/`. Lock in force: C1 =
`481fc2e30730395093fc0f8699843e1002d64aa3`.

## 4. Commands run and exact results

```
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/evaluation/v181 -q -rx
→ exit 0 · 73 passed, 41 xfailed, 0 failed · 2.14s
```

Per-suite (same run):

| suite | passed | xfailed | failed |
| --- | --- | --- | --- |
| test_contract_validation.py | 32 | 2 (F-1, F-2) | 0 |
| test_ets_known_truth.py | 8 | 21 | 0 |
| test_ets_fault_injection.py | 10 | 16 | 0 |
| test_checkers_detect_their_own_bugs.py | 23 | 0 | 0 |
| test_producer_seams.py | 0 | 2 | 0 |

Full captured output: `artifacts/pytest-eval-v181-ets-001.txt`
(sha256 `89278cd2…80f3`). Environment, fixture sha256s, and oracle digests are in
the manifest.

## 5. Known limitations, failure paths, performance observations

- **41 xfails are load-bearing, not noise.** Each names the lane it waits on
  (Model Pack `time_series.ets`, Agent option-batch generator, cross-family
  compare adapter) and each will convert to a hard failure the moment its lane
  lands but produces a wrong answer (strict xfail catches an accidental xpass).
- **F-1 and F-2 are reported as `xfailed` at this commit** because the repairs
  live on the integration tip, not on this branch. When the harness is re-run
  against a candidate integration tip that carries the repairs, both must flip to
  `passed`; a new `evaluation_id` must be minted for that run (§12.3).
- **Producer-seam signatures are pinned by best-guess contract-named spellings.**
  If a landed lane exposes a different public entry point, the test fails with an
  explicit "contract gap" message listing the spellings tried — by design (this
  is `driver.py`'s stated philosophy), so Integration gets a precise gap report
  rather than a silent skip.
- **Performance:** full suite 2.14s; the only non-trivial cost is the
  independent statsmodels reference fits in `test_ets_known_truth` (~1.8s for the
  8 oracle self-checks). No §12.4 performance SLO is asserted — no baseline exists
  yet (no runnable pack), and the ADR forbids inventing one.

## 6. Integration risks, suggested merge order, rollback

- **Merge order:** this evaluation harness is safe to merge onto the integration
  tip at any time; it adds only `tests/**` and `docs/**` and imports feature code
  lazily behind capability probes, so it cannot break a build that lacks the
  feature lanes. Recommended: land after the C1 contract lock and the F-1/F-2
  repairs so the two finding tests immediately go green; land the producer-bound
  tests before/with the Agent and Model Pack lanes so they gate those lanes.
- **Re-evaluation obligation:** once any feature lane or central adapter enters
  the candidate integration tip, prior evidence must not be reused — re-run the
  affected suites and generate a new `evaluation_id` pointing at the new
  `evaluated_commit` (§12.3, §9 Phase 2).
- **Rollback:** revert commit `b3f6a26` (and the docs commit) to remove the new
  tests and evidence; nothing under `backend/` or `frontend/` is touched, so
  there is no product rollback surface.

## 7. Forbidden / protected files touched?

**No.** No file under `backend/`, `frontend/`, `scripts/gate.sh`,
`tests/test_honest_did_adversarial.py`, or `tests/test_honest_did_sd_adversarial.py`
was modified. `scripts/gate.sh` was not run (targeted evaluation only, per the
work order). No dependency was installed or upgraded; no real LLM/API was called;
nothing was pushed, PR'd, merged, or tagged.
