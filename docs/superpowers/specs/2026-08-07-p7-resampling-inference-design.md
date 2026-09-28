# P7 Resampling Inference: Bootstrap and Permutation

## Boundary

This slice adds standalone, evidence-bearing kernels only. It does not register
operations with the Agent, OperationRegistry, orchestrator, frontend, or any
Claude-owned P0/P1/P2 seam. Runtime code never calls R, a shell, an import path,
or a user callback.

## Shared execution model

`ReplicatePlan` declares the replicate kind, bounded count, deterministic seed,
typed strategy/adapter IDs, combiner ID, and evidence budgets. The runner
executes code-registered `ReplicateStrategy` and `ReplicateAdapter` instances.
`execute_and_combine` gives the registered typed combiner the adapted scalar
evidence internally, then publishes only an aggregate result plus the batch's
seed/provenance commitments. Replicate rows and distributions are never part
of the public envelope.

Rubin pooling, bootstrap intervals, permutation p-values, and survey covariance
are deliberately separate combiners. They share the execution and lineage
boundary, not a falsely generic statistical formula.

## Bootstrap contract

`run_bootstrap` accepts a finite real vector, a closed statistic ID (`mean` or
`median`), a bounded replicate count, seed, confidence level, and one of
`percentile`, `basic`, or `bca`. The result reports the observed estimate,
bootstrap SE, bias, interval method and semantics, successful count, and the
shared batch envelope. Percentile quantiles use R type-7/NumPy linear
interpolation; basic intervals reflect the percentile endpoints around the
observed estimate. BCa uses explicit jackknife acceleration and bias
correction. Undefined or degenerate BCa evidence is rejected rather than
silently downgraded to a percentile interval.

## Permutation contract

`run_permutation` accepts two finite real vectors, a closed statistic ID
(`difference_in_means` or `difference_in_medians`), an alternative policy, and
either bounded Monte Carlo resampling or exact enumeration. Exact enumeration
is allowed only below the hard state-space cap and uses inclusive extreme
counts over all allocations. Monte Carlo p-values use the explicit plus-one
correction. The result labels `exact` versus `monte_carlo` and the p-value
semantics; it never presents a Monte Carlo value as exact.

## Oracle and safety policy

Focused tests include direct formula checks and optional base-R checks for
R type-7 quantiles, standard deviations, and exact combinations. The public
result digest is SHA-256 bound to `{batch, result}`. Input, state-space,
non-finite, unsupported-option, raw-output, and global-RNG violations fail
closed with stable reason codes.
