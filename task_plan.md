# P7 Extensions: clustering, discriminant, and time-series kernels

## Goal

在现有 P7 多元统计 worktree 中增加可独立验证的聚类、判别分析和时间序列统计内核；保持与 Claude 当前 Agent/P0/P1/P2 文件完全隔离，给后续 CapabilityContract 与自然语言 Agent 接入留下稳定、显式、可组合的接口。

## Scope and boundaries

- 允许修改：`multivariate` pack、独立 `time_series` pack、对应 model contracts、专用 tests、design/plan docs。
- 禁止修改：`backend/workbench/agent/**`、`frontend/src/workbench/agent/**`、现有 workflow seam、OperationRegistry、orchestrator、context tools、现有 time-series diagnostics C1 contract。
- 不安装新依赖；使用仓库已有 NumPy/pandas/SciPy/statsmodels。
- 不做自动模型选择、隐式标准化、静默缺失值处理、原始行回传或 Agent 注册。

## Stages

- [complete] Stage 0 — same-worktree formal line scope, design, and implementation plan
- [complete] Stage 1 — deterministic clustering kernel: k-means and hierarchical clustering
- [complete] Stage 2 — safe LDA/QDA discriminant kernel with validation evidence
- [complete] Stage 3 — time-series input boundary, ACF/PACF and unit-root diagnostics
- [complete] Stage 4 — explicit ARIMA/SARIMA and VAR/Granger/IRF kernels
- [complete] Stage 5 — shared JSON surface, adjacent regression tests, protected-path and FMS verification
- [complete] Stage 6 — cointegration and VECM
- [complete] Stage 7 — VAR stability and IRF confidence bands
- [complete] Stage 8 — correspondence analysis and MCA
- [complete] Stage 9 — external numerical oracle and final verification
- [complete] Stage 10 — MANOVA, power analysis, and categorical-test packs

## Stage 10 scope

- MANOVA is a new multivariate kernel with explicit structured terms and all four classic multivariate test statistics.
- Power analysis is a separate contract/pack for independent t, one-way ANOVA, and two-proportion normal-approximation designs with an exactly-one-unknown solver boundary and bounded sensitivity grids.
- Cramér's V and McNemar are a separate categorical-count pack with explicit correction/exactness policies.
- External oracle tests use direct statsmodels and optional base R only inside tests.
- No Agent, P0/P1/P2/P3, data-management, persistence, frontend, or existing time-series C1 paths may change.

## Stage 10 verification

- [complete] MANOVA: structured terms, four multivariate statistics, bounded provenance, response/design fail-closed checks, statsmodels oracle.
- [complete] Power Analysis: independent t, one-way ANOVA, two-proportion z, exact-one-unknown solver, bounded Cartesian sensitivity grid, closed contract and evidence digest, statsmodels oracles.
- [complete] Cramér's V/McNemar: strict integer tables, explicit correction/exactness, operation-specific contract fields, precision guard, base-R oracle.
- [complete] Focused P7/new-module integration suite: 171 passed, 2 statsmodels ComplexWarnings.
- [complete] Adjacent Agent/workflow regression suite: 81 passed; warnings are existing numerical/third-party warnings.
- [complete] Protected-path comparison and diff checks.
- [ ] Agent reachability, frontend, browser, full gate, merge, push, and release acceptance remain deferred to the P1/P2 integration wave.

## Decision rules

1. Every new public behavior begins with a failing test.
2. Every estimator receives explicit options and returns its policy/provenance.
3. Numerical degeneracy becomes a stable pack error; no pseudoinverse or fallback is implicit.
4. Candidate comparison is evidence-producing only; the kernel never silently chooses a winner.
5. Commits remain self-contained and touch no Claude-owned paths.

## Errors encountered

- Intentional red-test checkpoints initially failed on missing time-series model exports; the implementation then added the independent model modules and all six model tests passed.
- A NumPy-array-to-contract boundary was identified in the first time-series diagnostics run and closed with a local JSON-native conversion helper before proceeding.
- VECM log likelihood can be a complex scalar with zero imaginary part; the time-series JSON boundary now normalizes only near-real complex values and rejects materially complex/non-finite results.
- Early repeated `rescope-context` calls replaced the frozen scope one path at a time; this was corrected by one audited full-scope rescope and subsequent FMS verification. No Context Pack was hand-edited.
- Review-driven fixes closed float64 count precision loss, MANOVA term collisions/statistic bounds/output bounds, power-contract nonfinite/semantic/grid/digest validation, and adjacent exact-surface assertions.

## Phase 2 decisions

- Cointegration rank is evidence-derived by Johansen trace testing; VECM never accepts a free-form rank that bypasses the test.
- VAR stability is reported from companion eigenvalues; unstable fits are rejected by default unless `report_only` is explicitly selected.
- IRF bands are asymptotic-normal in this slice and labelled as such; no bootstrap wording is permitted.
- CA and MCA share one SVD core; MCA is explicitly labelled `indicator_ca` and does not claim an inertia correction that is not implemented.
- R is used only as a fixed-input test oracle. Runtime code never invokes R or a shell.
