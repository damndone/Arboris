---
name: iv-analysis
description: Guide complete IV/2SLS analysis with instrument justification, correctly named first-stage evidence, source-bound sensitivity and explicitly certified or unavailable weak-instrument inference.
---

# IV and 2SLS analysis

Fix the structural outcome, endogenous variables, included controls, excluded instruments, independent unit and estimand before estimation. Instrument relevance does not establish exclusion/exogeneity. The seed OLS estimate, a plausible story or an overidentification non-rejection cannot validate an instrument.

## Analysis and evidence

1. Inspect the original observations and dictionary, missingness and actual sample. State the substantive instrument argument and what the available data cannot test. Fit supported native IV/2SLS through the common operation and approval path.
2. Read actual source-bound coefficients, uncertainty, identification/rank and first-stage evidence. Preserve the native test names and reference distributions; a robust Wald statistic is not an ordinary first-stage F and must not be compared to an unrelated threshold.
3. Inspect native endogeneity and, when overidentified, applicable overidentification tests. Just identification provides no overidentification test. Rejection is a reason to revisit the model, not to discard an inconvenient instrument until significance improves.
4. Weak-instrument inference must be explicit. The current globally certified scalar AR inversion is limited to the admitted HC0, single-endogenous, excluded-instrument q=1–4 combinations. It can produce bounded/disjoint/ray/whole-line/singleton/empty sets; a covariance singularity is unavailable. Do not replace an unbounded set with finite grid endpoints or present unavailable combinations as certified. Empty sets require model revision. Wider model/inference combinations remain research objects, not formal support by renaming.
5. Compare real, defensible control/instrument/sample alternatives, documenting changed assumptions and sample identities. A conventional Wald interval alone is not weak-instrument-robust inference. Preserve original fits, unsuccessful specifications and limitations.

## Completion and report

Use the iv completion contract, native companions, certified-set evidence and a source-bound report. Verify with inspect_analysis_completion before completion claims. Distinguish computability, agreement with R/Stata definitions and valid inference. Scientific validity and identification remain separately reviewable. Keep failed attempts and pause after two; request missing substantive information rather than fabricating exclusion evidence. Isolated review and a specification curve are critiques/summaries, not independent numerical certification or automatic model selection.
