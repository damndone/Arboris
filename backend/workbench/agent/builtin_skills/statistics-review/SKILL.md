---
name: statistics-review
description: Review statistical reporting against Arboris result artifacts and analysis records; identify unsupported n, independent-unit claims and missing evidence.
---

# Statistical evidence review

Modified from nature-statistics at commit
f8797feed6405035e7d57f59cb8ba393c6a98802. See ../NOTICE.md and ../LICENSE.
This is bounded review guidance, not a scientific validation result or authority
to run code, fetch data, approve operations, or change permissions.

1. State the scope and inspect available result artifacts, operation records,
   source references and analysis-disclosure ledger using existing typed tools.
   Manuscript text alone cannot establish that a claim has been verified.
2. Distinguish source rows, the estimation sample and independent units. Repeated
   measurements or technical replicates do not establish independent n. Compare
   each reported n with the exact result sample and declared unit identifiers;
   report exclusions and uncertainty. If the independent unit or hierarchy is
   absent, mark AUTHOR_INPUT_NEEDED rather than inferring independence.
3. Map every conclusion and quantitative claim to its exact committed analysis
   result and artifact reference, including the relevant model or comparison,
   estimand, uncertainty, test, covariance and multiplicity definition. Check
   source ownership and revision; another model's matching number is not proof.
4. Preserve weak or non-significant evidence. A difference between significant
   and non-significant results does not establish a significant group difference.
   Association must not become a causal claim without a supported design.
5. Check claimed analysis counts and prespecified/exploratory status against the
   ledger. Missing ledger coverage is a stated boundary, not evidence of no
   exploration. Never invent sample sizes, estimates, intervals, p values or tests.
6. Return findings with rule, reported claim, exact source reference, observed
   fact, discrepancy and unresolved question. Use AUTHOR_INPUT_NEEDED for missing
   facts and NOT_AUDITABLE for unavailable sources. Only describe a fact check as
   passed when its required evidence was actually read and compared.

For an explicit model sample-count or raw coefficient-field claim, use
check_model_claims with the exact run_id, model_id and coefficient term. It
compares only the supplied fields with that model's public record; another
model's matching number cannot verify the claim. Its exact-value comparison
does not validate presentation rounding or unprovided manuscript text. Missing
evidence is unverifiable. An all-match response is not a whole-report audit.
