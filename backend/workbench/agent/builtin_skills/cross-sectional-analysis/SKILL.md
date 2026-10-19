---
name: cross-sectional-analysis
description: Guide a requested cross-sectional linear association analysis through source and estimand definition, fitted-model evidence, influence diagnostics, defensible sensitivity, and an honest completion review.
---

# Cross-sectional analysis

## Applicability

Use this skill when the user requests a complete cross-sectional linear analysis, a regression table with robustness columns, or an assessment of whether influential observations or control choices drive an association. Select it from the user's design and recorded data metadata, not from a benchmark label. This is analytical guidance; following the text does not certify a result or create a deterministic completion receipt.

A single-question lookup of an existing coefficient, interval, or diagnostic does not require the full workflow. Read the requested evidence and answer that question. Do not refit a model or run additional tests simply because this skill is loaded. A pending proposal is awaiting approval, not a completed analysis.

## Design, sample, and estimand

Establish the independent unit, repeated observations or grouping, source dataset and run, inclusion rules, missing-value handling, and analytic sample. Do not treat rows as independent because the file is rectangular. If dependence makes this cross-sectional specification inappropriate, explain the mismatch and use only a method actually exposed by the current operation contract.

State the estimand, outcome scale, focal contrast, adjustment variables and their rationale before comparing estimates. Distinguish conditional association from an identified causal effect. Names such as wage, ability, or price do not establish a transformation, measurement unit, causal role, or identification assumption. Use the user's definition and persisted metadata; leave unknowns explicit.

Keep the primary specification and the reason for each sensitivity analysis fixed before choosing a preferred result. Mark later revisions and their reasons. An approved execution plan is permission to carry out work, not statistical preregistration or proof that results were unseen. Do not choose specifications, controls, exclusions, or covariance estimates because their p-values are significant.

## Required evidence

Before constructing a new operation, call inspect_operation_contract for the actual operation and the named workflow steps. Use exactly its declared fields, options, and scope. Do not offer HC3 or unsupported cluster covariance as available methods. Do not silently substitute a nearby estimator, independent-row standard errors for required dependence-aware inference, or a weaker diagnostic when the requested method is unavailable. State the boundary and leave the affected requirement incomplete.

For a complete analysis, retain these actual products:

- A source and sample account, including transformations, exclusions, missingness decisions, and sample counts. Prefer existing bounded source summaries; do not request raw rows or filesystem paths.
- A persisted primary fitted model with its actual specification, outcome and focal term, covariance, nobs, estimate, and public uncertainty fields.
- Applicable diagnostic results and a documented disposition of their findings.
- At least one defensible sensitivity comparison addressing the substantive threat, with both the primary and comparison model references. Do not manufacture a comparison by relabelling the same model.
- A short account of the effect, uncertainty, assumptions, limitations, and unresolved work, with genuine references rather than a claim that an operation completed.

Use inspect_project_model_coefficients for explicitly named visible runs and exact stored terms. Read its models, missing_terms, and evidence_ref. Preserve run_id, model_id, result_ref, term, nobs, covariance and the returned estimate, std_error, p_value, ci_lower and ci_upper. A value of None is missing evidence; an empty model list or missing term cannot be inferred from earlier prose. Do not pad rounded values with zeros to invent precision.

For diagnostics and sensitivity products, use the existing completed-operation and artifact readers. inspect_operation_artifact admits only an emitted artifact in the current Chain and node scope; inspect its available/status, result and evidence_ref, including artifact_id and sha256. A committed Notebook workflow instead uses its Notebook receipt and returned public evidence; do not pass those artifact IDs into an operation-only reader. Bind each comparison to the same source or explicitly document changed samples and why they differ.

## Diagnostics and sensitivity

Use checks appropriate to the specification and the user's question. For linear regression this can include heteroskedasticity, functional form, VIF or other collinearity evidence, residual behavior, and influence. Read the relevant public results before interpreting them; an already computed diagnostic need not be rerun. The existence of a diagnostic artifact is not a passed diagnosis.

If Cook's distance or another influence result identifies a concern, do not stop at the full-sample slope. Preserve that estimate and obtain a defensible sensitivity result, or explain why it cannot be obtained and report partial completion. Do not delete observations merely to improve significance. A leave-out analysis must state its rule and sample change, preserve the original result, and pass the normal data/proposal approval boundary. If only bounded aggregate influence evidence is available, do not invent observation identities or exclusions.

For a control-choice question, compare substantively justified specifications and state how the estimand or conditioning set changed. For near-duplicate predictors, report the identification limitation and use only a supported contrast with an actual persisted result. A changed coefficient alone does not establish omitted-variable bias. Differences between conventional and robust standard errors alone do not establish heteroskedasticity or select the correct estimator.

## Completion self-check

Before claiming the requested analysis is complete, check the scope of the question against the actual evidence:

1. Are the independent unit, sample, estimand and recorded outcome scale clear?
2. Does the primary model answer that estimand, with the requested focal term and usable uncertainty?
3. Were applicable diagnostic findings interpreted, including any influence concern, rather than merely listed?
4. Is there a real, justified sensitivity result, or is that requirement explicitly incomplete?
5. Do every number and model comparison refer to the correct persisted source, run and specification? Keep genuine evidence_ref values and report missing fields as missing.
6. Are causal limits, changed samples, exploratory revisions and unavailable methods visible in the conclusion?

This self-check is qualitative guidance, not deterministic certification. Do not report that a paper checklist has validated the numerical result. Distinguish complete, partial completion, blocked work and awaiting approval in plain language. A successful fit, saved plan, generated report, or proposal alone does not satisfy the full analysis request.

## Failure and partial completion

Stop after at most two unsuccessful attempts at the same blocked requirement. Use the exact published contract and returned error to make a concrete correction; do not repeat rejected payloads or relax validation. Preserve both errors and the last trustworthy evidence. Pause the affected work and explain what input, capability, or approval is needed.

Continue independent work only when it is still within the user's request and permissions. Never claim the blocked diagnostic or sensitivity succeeded. State which products exist, which remain missing, and how that limits the answer. Do not change the question or search more specifications to obtain significance.
