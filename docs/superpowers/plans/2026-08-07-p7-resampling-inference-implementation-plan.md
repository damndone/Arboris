# P7 Resampling Inference Implementation Plan

1. Extend the existing replicate-and-combine runner with a typed internal
   combiner boundary while preserving the aggregate-only `execute` API.
2. Add a closed resampling result envelope and shared numeric/seed/statistic
   validators with hard observation, replicate, and exact-state bounds.
3. Add red tests for Bootstrap and permutation semantics, safety, determinism,
   and no raw replicate output.
4. Implement Bootstrap strategy/adapter/combiner with percentile, basic, and
   BCa intervals; reject undefined BCa evidence.
5. Implement permutation strategy/adapter/combiner with exact enumeration and
   Monte Carlo plus-one p-values, including explicit alternative semantics.
6. Validate with base-R formula/combination Oracles, shared/MI regressions,
   compile and diff checks, and protected-path comparison.

The pack remains standalone until the later CapabilityContract/P1/P2
integration wave. No release, merge, push, or Agent registration is part of
this plan.
