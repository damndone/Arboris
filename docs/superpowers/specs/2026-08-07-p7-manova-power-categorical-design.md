# P7 MANOVA, Power Analysis, and Categorical Tests Design

## Goal

Add three standalone statistical packs—MANOVA, power analysis, and categorical-table tests—without touching Claude's Agent, workflow, data-management, persistence, or frontend surfaces. The numerical boundary must be explicit enough for a future CapabilityContract adapter and natural-language Agent planner to compose safely.

## Non-goals and ownership boundary

This slice does not add OperationRegistry entries, Agent vocabulary, orchestrator branches, context discovery, automatic data reshaping, frontend controls, persistence, or release wiring. It stays in the existing `workbench-v1.8.8-p7-multivariate` worktree and the existing `v1-8-8-p7-extensions` formal line. New contracts are standalone and are not reachable through the current Agent.

## Architecture

MANOVA lives beside the existing PCA/EFA/reliability code under `engine/packs/multivariate`, but uses its own module and the existing multivariate result envelope. Power analysis and categorical tests are separate packs with separate versioned envelopes because neither is a multivariate data-frame operation and neither should inherit multivariate column assumptions.

Every public function receives an explicit request boundary, validates before numerical execution, returns a JSON-native result envelope, and records the policy used. The kernels never mutate caller frames, invoke a shell, call R at runtime, infer defaults from the data, or expose raw rows.

## MANOVA

`fit_manova` accepts numeric response columns plus explicitly classified factor columns, numeric covariates, optional explicit interaction terms, and an explicit intercept policy. Complete-case filtering is the only declared missing-data policy. Factor levels use deterministic string identity and the model formula is generated internally from quoted column names; arbitrary user formula text is not accepted.

The result contains the model specification, retained-row positions, response/design dimensions and rank, residual degrees of freedom, and per-term Wilks' lambda, Pillai's trace, Hotelling–Lawley trace, and Roy's greatest root with numerator/denominator degrees of freedom, F values, and p values. Singular design, insufficient residual degrees of freedom, non-finite values, unsupported term combinations, and invalid factor levels fail closed. The result is evidence, not an automatic post-hoc or causal claim.

## Power analysis

The first independent solver supports three explicit design families: independent two-sample t, one-way fixed-effects ANOVA, and two-proportion normal approximation. The caller declares the design, the quantity to solve for, all other required parameters, and any group/ratio parameters. Exactly one solve target is omitted; no effect size, alpha, power, group count, or allocation ratio is silently chosen.

The result records the design, solve target, requested inputs, solved value, estimator/library provenance, and a bounded optional sensitivity grid. Sensitivity analysis is a grid of explicitly supplied values, not automatic tuning. Invalid ranges, multiple unknowns, non-finite inputs, unbounded grids, and unsupported design/alternative combinations fail closed. Effect-size conventions are named (`cohens_d`, `cohens_f`, or `cohens_h`) so an Agent can explain rather than guess assumptions.

## Cramér's V and McNemar

The categorical pack accepts finite non-negative integer count tables only. Cramér's V accepts a bounded table with at least two rows and columns and an explicit chi-square correction policy. It returns the chi-square statistic, degrees of freedom, p value, expected-count diagnostics, sample size, and Cramér's V.

McNemar accepts an explicit 2×2 paired table and explicit exact/asymptotic and continuity-correction policies. It returns the discordant counts, test statistic, p value, method, and a bounded paired-effect summary. A table with no discordant pairs is rejected rather than reported as a fabricated zero-effect result.

## Oracle and verification

Oracle tests use independent direct statsmodels calls for MANOVA and power-analysis calculations, and base R `mcnemar.test`/independent chi-square arithmetic for categorical checks when `Rscript` is available. Oracle code exists only under tests with fixed inputs and argv-based subprocess invocation; runtime code never depends on R. If an external executable is unavailable, the test is skipped and the handoff records that it is not an oracle pass.

The focused suite covers normal results, JSON finiteness, deterministic repeated calls, invalid-input rejection, exact policy preservation, bounded sensitivity output, and numerical agreement with the external reference. Adjacent Agent/workflow tests and protected-path comparisons remain separate gates.
