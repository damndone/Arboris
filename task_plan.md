# P7 Extensions: standalone statistical kernels

## Goal

在现有 P7 多元统计 worktree 中继续增加可独立验证的统计内核；保持与 Claude 当前 Agent/P0/P1/P2 文件完全隔离，给后续 CapabilityContract 与自然语言 Agent 接入留下稳定、显式、可组合的接口。当前调整为：先做统一 replicate-and-combine 基础并修正 MICE/Rubin 池化，再做 Bootstrap/permutation；随后只做新的 GMM/弱工具变量诊断、Scheffé/Games--Howell，最后让新 pack 消费已有 v1.8.7 survey design。

## Scope and boundaries

- 允许修改：现有 P7 standalone packs、replicate-and-combine/missing-data contracts and packs、MICE/普通估计的必要消费边界、专用 tests、design/plan docs；后续可增加新 pack 对既有 survey design 的 typed adapter。
- 禁止修改：`backend/workbench/agent/**`、`frontend/src/workbench/agent/**`、Claude 正在对接的 P0/P1/P2 workflow seam、OperationRegistry、orchestrator Agent/context seam、现有 time-series diagnostics C1 contract、已有 survey design 数学内核。
- 不安装新依赖；使用仓库已有 NumPy/pandas/SciPy/statsmodels。
- 不做自动模型选择、隐式标准化、静默缺失值处理、原始行回传或 Agent 注册。
- 运行时不接受任意 Python callback、公式字符串、import path 或表达式；所有可执行统计量必须来自白名单注册表。
- 每个新 pack 先完成独立合同、红测、数值 Oracle 和保护路径检查，再进入下一阶段；现有 MICE 修正必须先有回归红测，不能把当前错误断言继续当作基线。

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
- [complete] Stage 11 — classic RM-ANOVA/mixed design, survival extensions, ROC diagnostics, and meta-analysis
- [complete] Stage 12 — replicate-and-combine foundation, missingness diagnostics, and Rubin MI correction
- [complete] Stage 13 — bootstrap and permutation inference consumer pack
- [complete] Stage 14 — GMM and weak-instrument diagnostics (reuse existing IV/2SLS)
- [complete] Stage 15 — Scheffé/Games--Howell and multiple-comparison contract
- [complete] Stage 16 — survey-aware adapters for new packs (reuse v1.8.7 survey design)
- [complete] Stage 17 — cross-pack regression, protected-path, and formal closeout verification
- [complete] Stage 18 — final P7 extension batch: nonparametric/robust, GLM extensions, diagnostics, spatial, matching, and synthetic control

## Stage 12 scope

- A shared `replicate-and-combine` contract/engine with bounded plans, deterministic provenance, failure summaries, and typed combiner strategies for MI, Bootstrap, Permutation, and future Survey replicates.
- Missingness diagnostics plus Rubin pooling of multiple model fits; first ordinary OLS consumer, unsupported model families fail closed rather than using the first imputation.
- Existing `run_mice_imputation` must persist exactly `m` declared datasets for `m > 1`, and the model result lineage must include all of them.
- Independent direct Rubin formula Oracle and optional R `mice::pool` Oracle; runtime code must never invoke R or a shell.
- No Agent registry, frontend, Claude P0/P1/P2 path, or existing v1.8.7 survey design mathematics changes.

## Stage 12 verification target

- [complete] MICE regression red-green suite proving `m=2` no longer becomes one dataset.
- [complete] Replicate-and-combine contract/runner suite with bounded provenance and no raw replicate output.
- [complete] Missingness and Rubin pooling suite, including between-imputation variance increasing total SE where estimates differ.
- [complete] OLS workflow pool and unsupported-model fail-closed integration tests.
- [complete] Direct Rubin/R `mice::pool` Oracle subset.
- [complete] Adjacent P7 regression suite, protected-path comparison, compile/safety scan, and formal FMS verification.
- [complete] Two-stage review after each implementation task and final slice review.

## Stage 12/13 completed verification

- [complete] MICE `m=2` persists two ordered datasets, restores global NumPy RNG state, and blocks partial/failed completion before estimation.
- [complete] Generic Rubin pooling is variance-first (within, between, total, t-based CI/p/FMI) and the first-imputation fit-statistic/residual/covariance fields cannot leak into pooled OLS output.
- [complete] OLS MI consumer records all imputed dataset IDs in model/pool artifact lineage; unsupported model families fail without first-fit or auto-fallback.
- [complete] Shared runner has a typed internal combiner boundary; public batch/result envelopes reject raw replicate values and bind `evidence_digest` to `{batch,result}`.
- [complete] Bootstrap supports mean/median with percentile, basic, and BCa intervals; permutation supports exact allocation enumeration and Monte Carlo plus-one p-values with explicit semantics.
- [complete] Stage 12/13 regression and Oracle slice: 211 passed, including 2 base-R numerical checks; compile, diff, and Claude protected-path checks passed.

## Stage 13 scope

- Closed statistic IDs only; no callback, formula, import path, shell, or raw replicate payload.
- Exact permutation state space is bounded; BCa degeneracy rejects rather than silently downgrading.
- The packs are standalone and not Agent/orchestrator/frontend reachable in this slice.

## Stage 14/15 scope and verification

- GMM is an explicit standalone extension of the existing IV/2SLS surface: one-step and two-step estimators, heteroskedastic sandwich covariance, Hansen J when overidentified, and descriptive weak-instrument evidence. No automatic Stock--Yogo threshold decision is emitted.
- Scheffé and Games--Howell are separate pairwise combiners with a digest-bound contract. Games--Howell uses Welch degrees of freedom and a studentized-range tail; Scheffé uses pooled ANOVA MSE. Constant-variance and non-finite inputs reject.
- GMM focused suite: 11 passed, including statsmodels IV2SLS/IVGMM Oracle checks; post-hoc focused suite: 10 passed, including 2 base-R checks. Commits: `858e287`, `26ebd11`.
- The standalone packs remain unreachable from Agent/orchestrator/frontend until the later P1/P2 integration wave; survey mathematics remains untouched.

## Stage 16 scope and verification

- Only `engine/replicate_combine/survey_adapter.py` bridges the existing survey design into the shared replicate boundary; `backend/workbench/survey/**` remains unchanged.
- The adapter accepts a typed `EstimatorSpec`, consumes the existing design's jackknife/BRR/provided/bootstrap weights, and publishes aggregate covariance/SE/design-df evidence with explicit failure summaries.
- Survey adapter + shared foundation: 137 passed; existing v1.8.7 survey engine/composition/wiring regression: 33 passed with 3 existing deprecation warnings; R-generated jackknife and fixed-Hadamard-BRR checks passed.

## Stage 17 verification

- [complete] Cross-pack regression: 607 passed with 5 existing warnings.
- [complete] Protected Claude Agent/P0/P1/P2 paths and `backend/workbench/survey/**` comparison are empty; the only scoped orchestrator change is the MI report-consumer boundary.
- [complete] Runtime safety scan, relevant-module compilation, `git diff --check`, and formal FMS verification passed.
- [ ] Agent/orchestrator/frontend reachability, native browser acceptance, full gate, merge, push, and release remain deferred to the P1/P2 integration wave.

## Stage 18 scope and freeze rule

- Add five final standalone extension areas: rank-based/nonparametric and robust inference; zero-inflated/hurdle/Beta GLM extensions; independent model diagnostics; global spatial autocorrelation with permutation inference; and explicit propensity matching plus synthetic control.
- Every new completed result carries bounded machine-readable scope, assumptions, limitations, `not_claimed`, and unsupported extensions. These metadata are part of the contract, not only prose documentation.
- Spatial scope is intentionally limited to Moran's I, Geary's C, Getis--Ord global evidence, explicit weights, and permutation policy. Spatial lag/error regression is deferred.
- Matching and Synthetic Control remain assumption-labelled causal evidence; no unconditional causal claims, automatic method choice, or mutation of existing DID/SC code.
- All new production paths remain under new `contracts/model`, new `engine/packs`, tests, Oracle fixtures, and freeze docs. Agent/P0/P1/P2/OperationRegistry/orchestrator/frontend/survey mathematics remain protected.
- After Stage 18, freeze P7 and move to P1/P2 capability adoption, Agent reachability, browser acceptance, and end-to-end validation. Any additional statistical family requires a separate extension line.

## Stage 18 Task 1 verification

- [complete] Added `P7ScopeMetadata` and `make_p7_scope` as the only shared foundation for the final five packs; the contract is closed-key, bounded, immutable, and JSON-safe.
- [complete] Added adversarial and positive prose tests for missing/extra fields, nested raw payloads, local/relative/Windows path shapes, code-shaped import/exec/eval/formula strings, and safe statistical notation.
- [complete] Focused verification: 33 passed; relevant modules compile; `git diff --check` passes; spec and quality reviews approved after the repeated-backslash fix.
- [complete] Commit: `02cded2` (`fix(p7): tighten extension scope text boundaries`).
- [complete] Scope policy margin: known filesystem/path shapes are rejected, while ambiguous statistical prose such as `A/B`, `group/time`, `/api/v1`, and conceptual `import` is allowed. This is a bounded heuristic, not a universal path classifier; future extensions must add explicit adversarial cases rather than broadening substring bans.

## Stage 18 Tasks 2–8 verification

- [complete] Task 2 — nonparametric/robust pack: Mann–Whitney, Wilcoxon signed-rank, Kruskal–Wallis, Friedman, Spearman, Kendall, and bounded robust summaries; explicit missing/tie/zero/exact/asymptotic/permutation policies; base-R formula Oracle and adversarial tests.
- [complete] Task 3 — GLM extension pack: ZIP, ZINB, hurdle Poisson, hurdle negative binomial, and Beta regression; separate zero/count/positive/mean/precision estimands; statsmodels Oracle and bounded convergence/linear-predictor policies.
- [complete] Task 4 — standalone model diagnostics: VIF, Breusch–Pagan, White, Breusch–Godfrey, RESET, and influence evidence; typed request boundary; statsmodels/R-compatible direct-formula Oracle; no aggregate model verdict.
- [complete] Task 5 — global spatial statistics: Moran's I, Geary's C, and global Getis–Ord G with explicit graph/weight policies and seeded permutation evidence; base-R direct-formula Oracle; `spdep` optional check skipped when unavailable.
- [complete] Task 6 — Matching: typed ATT/balance evidence with explicit propensity support policy, deterministic matching, balance diagnostics, and base-R logit Oracle; causal claims remain assumption-labelled.
- [complete] Task 7 — Synthetic Control: bounded simplex donor weights, pre-fit/post-gap/placebo evidence, and base-R `constrOptim` Oracle; predictor-matrix and inferential extensions are explicitly deferred.
- [complete] Task 8 — cross-pack review and freeze: focused suites, external Oracles, compile/safety scan, protected-path comparison, `git diff --check`, formal event append, and FMS verification.

### Stage 18 focused evidence

- [complete] Nonparametric + diagnostics: 48 passed.
- [complete] GLM + spatial: 44 passed, 1 optional `spdep` skip.
- [complete] Matching + Synthetic Control: 51 passed, 2 optional package skips (`MatchIt`, `Synth`/`quadprog`).
- [complete] Code commit: `5df5686` (`feat(p7): add final standalone statistical extension packs`).
- [complete] P7 freeze docs: final design, implementation plan, and freeze handoff recorded in `docs/superpowers/`.
- [ ] Agent/CapabilityContract/OperationRegistry/orchestrator/frontend reachability, browser acceptance, full release gate, merge, push, tag, and release remain intentionally deferred; these are not P7 kernel acceptance claims.

### Stage 18 freeze rule

P7 is frozen at this boundary. Any new statistical family, or any expansion of Matching/Synthetic Control beyond the listed contracts, requires a new approved extension line after P1/P2 adoption. Future work first adds a typed adapter and Agent capability declaration; it must not reach into this frozen kernel by dynamic dispatch or raw formula execution.

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

## Stage 11 scope

- Four disjoint standalone packs: `repeated_measures_anova`, `survival_analysis`,
  `roc_diagnostics`, and `meta_analysis`.
- Each pack owns a new model contract, pack directory, focused tests, and an external
  numerical Oracle; no Agent registry, orchestrator, frontend, prediction runner, or
  existing Cox/LMM/automatic statistical-test path changes.
- Oracle policy: statsmodels `AnovaRM` plus R `aov` for RM-ANOVA; R `survival` for KM/
  log-rank; base R rank/trapezoid formulas for ROC; direct statsmodels meta-analysis
  reference calls plus base R formulas for meta-analysis.
- All four modules require explicit semantic columns/policies, bounded JSON-safe output,
  stable error/reason fields, and fail-closed behavior for invalid or ambiguous input.

## Stage 11 execution map

- [complete] Design/spec/plan documents and formal scope rescope.
- [complete] Parallel TDD implementation: RM-ANOVA, Survival, ROC, Meta-analysis.
- [complete] Per-pack spec review, independent quality review, and external Oracle re-run.
- [complete] Integrated P7 regression, protected-path check, FMS verify, and local commit.

## Stage 11 verification

- [complete] RM-ANOVA/mixed design: 34 focused tests, 5 R Oracles including independent `stats::mauchly.test.SSD`; final quality review approved.
- [complete] Survival KM/log-rank/RMST: 29 focused tests, 4 R `survfit` Oracles, bounded 100k-row performance probes; final quality review approved. R `survdiff` does not support delayed-entry counting-process input, so the limitation is explicit.
- [complete] ROC/classification diagnostics: 35 focused tests, base-R Oracle, 500 ROC/PR and 400 calibration randomized checks; exact versus grid-sampled metrics and score-only provenance are contract-validated.
- [complete] Meta-analysis: 52 focused tests, 7 statsmodels/HKSJ/base-R Oracles, 50 randomized fixed/DL/PM checks; nested evidence, correction semantics, and status/reason pairing are contract-validated.
- [complete] Integrated new-pack suite: 150 passed; external Oracle subsets RM 2, Survival 4, ROC 1, Meta 3 passed.
- [complete] Adjacent P7 suite: 171 passed with 2 existing statsmodels ComplexWarnings.
- [complete] Adjacent Agent/workflow regression: 81 passed with existing numerical/third-party warnings.
- [complete] Protected-path comparison is empty; Python compilation and runtime no-R/no-shell scan passed; formal FMS verification passed.
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
