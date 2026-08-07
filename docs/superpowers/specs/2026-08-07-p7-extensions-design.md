# P7 Extensions: clustering, discriminant, and time-series kernel design

## Goal

Extend the existing standalone statistical foundation with clustering, discriminant analysis, and time-series statistical kernels that are accurate enough to become future Workbench capabilities, while remaining independent of Claude's current Agent workflow implementation.

## Architecture

The existing multivariate pack remains the home for clustering and discriminant analysis. Each algorithm is a separate module behind explicit option values and the existing versioned JSON result envelope. Time-series work is a separate `engine/packs/time_series` package with a new model contract, so it does not modify the existing time-series diagnostics C1 contract or the Agent layer.

The public kernel boundary accepts a declared data frame and explicit policy. It never discovers data, mutates source frames, performs hidden preprocessing, or registers an operation. Every result contains the executed policy, estimator provenance, bounded optional row-level outputs, and stable reason codes. Future CapabilityContract adapters can translate these fields into proposal, confirmation, execution, and verification packets without changing numerical code.

## Clustering

Support deterministic Lloyd k-means and SciPy hierarchical clustering. Standardization is one of `none` or `zscore_sample`; it is never inferred. K-means requires an explicit `fixed` or `silhouette_candidates` selection policy, a bounded candidate list when comparing k, and an explicit random seed. Hierarchical clustering requires explicit linkage and metric, with `ward` restricted to Euclidean distance. Candidate comparison returns all bounded candidate metrics and does not silently pick a model unless the caller requests the declared selection policy. Assignments are opt-in and row-bounded.

## Discriminant analysis

Support LDA and QDA with explicit class labels, prior policy (`empirical` or declared finite priors), and covariance regularization. The default regularization is zero but is represented in the request and result; singular matrices fail closed unless a positive regularization value is declared. Evaluation is explicit: callers provide either no evaluation or a declared holdout fraction/random seed. Results contain class order, priors, covariance policy, discriminant parameters, confusion matrix and metrics when evaluation is requested, without raw rows.

## Time-series kernel

Provide a strict univariate/multivariate time-index boundary, ACF/PACF, ADF/KPSS unit-root tests, explicit ARIMA/SARIMA fitting, and explicit VAR/Granger/IRF operations. Time values are not sorted or frequency-inferred silently. Missing values require the declared complete-case policy. Model orders, deterministic trend, lag, test regression, and confidence level are explicit. Diagnostics are evidence only; they do not autonomously difference data, choose orders, or claim causality. Granger output is reported as predictive precedence under the tested specification, not structural causality.

## Safety and extensibility

- Reject non-numeric, non-finite, duplicate, and insufficient data rather than coercing it.
- Bound candidate grids, iteration counts, lag/order sizes, score/prediction rows, and impulse-response horizons.
- Preserve exact signs, labels, p-values, confidence endpoints, and estimator versions in JSON-native output.
- Keep agent registration, orchestrator dispatch, context discovery, persistence, frontend, and browser acceptance out of this line until P1/P2 are complete.

## Verification

Each module follows TDD with numerical fixtures and adversarial failure cases. The final batch runs focused tests, adjacent Agent regression tests, `git diff --check`, protected-path comparison against the baseline, and formal FMS verification. Full Agent reachability, browser acceptance, and release readiness remain explicitly unverified.
