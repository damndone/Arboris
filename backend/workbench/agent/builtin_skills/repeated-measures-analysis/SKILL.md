---
name: repeated-measures-analysis
description: Guide native LMM research using real subject grouping, random-effect structure, admission-gated persisted evidence, residual diagnostics, sensitivity fits and explicit singularity limits.
---

# Repeated measures and linear mixed effects

Use when repeated observations or a hierarchy motivate a supported LMM. Fix the subject/unit, outcome scale, repeated-time structure, fixed effects and random effects before estimation. Repeated rows from the same person are not independent subjects.

## Analysis and evidence

1. Inspect the registered source and dictionary. Verify subject IDs, repeated observations, missingness and the actual retained sample. Avoid constructing pseudo-replicates or inventing subject identities.
2. Execute the native LMM through the original admission and proposal/approval path. The sealed native packet and FD-only persistence owner are authoritative. Never write a substitute model JSON or read configuration summaries as if they were numerical results.
3. Read actual coefficients/SE/covariance conventions, convergence, random-effect covariance and singularity evidence. Inspect the native observation-level residual diagnostic summaries and source companion through the admitted reader; do not send row residuals to the model. Convergence alone is not an adequate analysis and singularity is not automatically solved by dropping a random effect.
4. Compare a substantively justified fixed/random structure or analysis sample with real persisted results. Record what changed and why. Distinguish ML/REML and fixed-effect changes where relevant; do not interpret incomparable likelihoods as a valid selection test.
5. Bind every reported number to the native source/model/term and preserve sample changes, diagnostic concerns and unavailable methods. A seed OLS or fake model_type cannot satisfy an LMM request.

## Completion and recovery

Use the lmm completion contract and source-bound report; inspect the machine evidence before claiming delivery complete. It does not certify distributional assumptions, scientific validity or report fidelity. Keep both failures; pause the affected step after the second and offer data/structure/capability corrections. Do not bypass admission or loosen persistence/approval to keep going. Ask uses /review on demand; Auto may revise within its approved plan after isolated critique, using the same remaining budget. That critique is not an independent oracle.
