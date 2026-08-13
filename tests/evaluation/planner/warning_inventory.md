# Warning inventory

Captured on 2026-08-13 from the focused suites and the host full gate. This
file distinguishes warnings that Workbench can repair from warnings that are
part of a deliberate degenerate-data boundary or belong to a dependency.

## Removed in this line

- `frontend/src/report/ReportView.test.tsx`: React `act(...)` warnings were
  caused by assertions racing the report provider's asynchronous state update.
  The tests now await the visible transition and retain the original UI
  assertions.
- `frontend/src/workbench/WorkbenchRouteContainer.test.tsx`: React `act(...)`
  warnings were caused by asynchronous analysis-loop loads and React Router
  future-flag warnings. The tests now await the error/load boundary and opt
  into the declared Router v7 behavior.
- `backend/workbench/app.py`: the Workbench-owned `@app.on_event("startup")`
  warning was removed by moving the same validation/bootstrap call into the
  FastAPI lifespan context. No startup behavior was intentionally changed.
- `frontend/src/workbench/agent/AgentPanel.test.tsx`: decline/revision tests
  now await the async action boundary before asserting the calls.
- `frontend/src/launcher/LauncherRoute.tsx`: a conditional `useState` after
  an early `<Navigate>` return was moved above the branch. The old test passed
  while logging React's "Rendered fewer hooks than expected" error when the
  recent-project state changed.
- `frontend/src/main.tsx`, `frontend/vitest.setup.ts`, and the affected router
  tests: the two React Router v7 future flags are explicit in both browser and
  test routers.
- `backend/workbench/data_operations.py`: pandas' deprecated `rename(copy=)`
  call is now an explicit `.copy()`, and date parsing uses the explicit
  `format="mixed"` mode rather than the implicit parser fallback.
- `backend/workbench/statistical_tests.py`: constant-input correlation is
  returned as typed null evidence with `CORRELATION_CONSTANT_INPUT`; Cohen's
  d uses the standard-library sample variance so a typed constant-group
  rejection does not first emit SciPy precision warnings.
- The same statistical boundary now computes Welch and paired t statistics
  locally when a group/difference has zero variance, and records
  `T_TEST_ZERO_VARIANCE`, `PAIRED_T_ZERO_VARIANCE`, or
  `ZERO_VARIANCE_GROUP` in the evidence instead of leaking SciPy divide-by-zero
  warnings.

## Remaining and intentionally not suppressed

- `fastapi/testclient.py`: Starlette warns that the installed `httpx` version
  should move to `httpx2` for `TestClient`. This is third-party dependency
  ownership; removal requires a dependency/lockfile decision and a separate
  compatibility gate.
- statsmodels emits a NumPy array-shape deprecation from its ARMA/GARCH state
  space implementation, and a BIC formula `FutureWarning` from its GLM
  implementation. Both are upstream semantic/dependency decisions; no global
  filter was added because changing the BIC convention or hiding numerical
  library output without a version decision could change evidence meaning.
- SciPy/statsmodels still emit numerical warnings for deliberate degenerate
  fixtures outside the repaired statistical-test boundary: perfect
  separation, infinite VIF, high-scale White tests, nearly identical model
  samples, and singular mixed-effect covariance. These cases remain visible in
  the host gate. Workbench result contracts sanitize non-finite values or
  reject the unsafe fit; a future numerical-diagnostics slice should translate
  every remaining library warning into a structured status before claiming
  warning-free numerical execution.
- Python's multiprocessing fork warning is emitted by the runtime when one
  append-only-store test forks a multi-threaded process. It is not an
  analytical result and is retained until the test can move to a spawn-safe
  fixture.
- A fresh benchmark preview may emit a Matplotlib cache-directory warning if
  `MPLCONFIGDIR` is not writable. The runner does not hide it; local gates set
  a writable cache directory explicitly. It does not affect planner scoring or
  provider calls.

No global warning filter, console mock, or pytest ignore was added.
