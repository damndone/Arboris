---
name: generalized-outcome-analysis
description: Guide complete analyses of count or binary outcomes using currently supported models, recorded effect scales and uncertainty, appropriate diagnostics, sensitivity evidence, and explicit limits on completion.
---

# Generalized outcome analysis

## Applicability

Use this skill for a requested complete analysis of a count outcome or a binary outcome, including an interpretable effect and its uncertainty. Establish applicability from user definitions and recorded metadata. A numeric column or an imported seed OLS model is not a model-choice justification. This guidance does not certify an estimate, a model choice, or the truth of a substantive conclusion.

A single-question lookup of an existing model coefficient, rate ratio, or probability effect needs only the evidence relevant to that question. Do not force a new plan, a refit, a full diagnostic suite, or an extra report. A saved proposal awaiting approval is not an executed model. Repeated measures, survival outcomes, and other designs need their own appropriate contract; do not force them into this skill's two branches.

## Design, sample, and estimand

Identify the independent unit, sampling or treatment assignment, repeated observations or grouping, source dataset, analytic sample, missingness policy, and outcome coding. For counts, establish whether exposure or observation time varies and whether the estimand is a rate or an expected count. For binary outcomes, establish which recorded value represents the event. Do not invent event coding from a variable name.

Define the estimand and focal contrast, covariate adjustment, reference values, and intended reporting scale before selecting a preferred specification. Distinguish a log-scale coefficient, rate ratio, probability contrast and marginal effect. Observational associations do not become causal effects merely by changing the link function. Record known identification assumptions and leave unsupported ones unstated.

Choose a primary specification and a substantive sensitivity question before comparing results. Approval of an execution plan is not statistical preregistration or proof that results were unseen. Do not choose families, links, controls, reference values, or sample restrictions because a result is significant. Preserve later changes and their rationale.

## Required evidence

Take the currently registered model and post-estimation steps from the step reference in the protocol, or from inspect_operation_contract for steps it does not cover, before constructing an operation. Candidate families include Poisson or negative-binomial for counts, and logit, probit or binomial GLM for binary outcomes, only when the current contract declares them for the requested design. This skill does not add new model or inference capabilities. Do not offer HC3 or unsupported cluster covariance as available methods. Do not silently substitute seed OLS, an unsupported link, or independent-row inference when the requested design or model is unavailable; explain the boundary and leave the requirement incomplete.

For a complete analysis, retain these actual products:

- An outcome-coding, independent-unit, sample and missingness account; for a rate question, the recorded exposure definition and handling.
- A persisted fitted model belonging to the intended count or binary family, with its actual covariates, link or parameterization when exposed, covariance, nobs and focal-term uncertainty.
- Applicable model adequacy and inferential diagnostics, with a disposition of the findings.
- An interpretable effect at the user-requested scale, using a supported server-produced result with matching uncertainty where available.
- A defensible sensitivity comparison addressing a stated threat, plus a short report of the result, assumptions and remaining limitations.

Use inspect_project_model_coefficients for named visible runs and stored terms. Preserve run_id, model_id, result_ref and evidence_ref alongside nobs, model_type, covariance, inference, coefficients and their returned estimate, std_error, p_value, ci_lower and ci_upper. Inspect missing_terms. None, missing models, an unavailable parameterization or an omitted field remain unknown; do not infer them from prose, the imported model or a plausible method name.

Use emitted completed-operation artifacts through inspect_operation_artifact and check available/status, result and evidence_ref. For committed Notebook workflows, use their own receipt reader and returned public post-estimation evidence rather than an operation-only artifact reader. Record artifact_id, sha256 and the producing step when returned. Keep model and post-estimation results on the same source and actual fitted specification, or explicitly document sample and specification changes. Do not request raw rows or filesystem paths to fill gaps in a bounded projection.

## Diagnostics and sensitivity

For count outcomes, examine the evidence about overdispersion and model adequacy before endorsing Poisson uncertainty. Do not equate a successful fit with adequate model-based standard errors. Negative-binomial and supported robust Poisson approaches are possible comparisons only if the published contracts allow the exact specification and inference. Do not add zero inflation, offsets, weights or dependence corrections by assuming an undocumented field exists. If exposure is needed but unsupported, explain the limitation rather than silently estimating a different quantity.

For binary outcomes, obtain the actual fitted-model result and, when the question requests a probability effect, a supported postestimation.margins result or another explicitly published probability contrast. Cite the recorded evaluation/reference values and uncertainty. Check the variance source actually used for that result; do not borrow the variance of a coefficient and describe it as the variance of a marginal effect. Report omitted covariance or variance metadata as unverified.

Do not compute a percentage or marginal effect from prose. Use only a currently exposed server-side transform appropriate to the documented scale, or an explicit post-estimation result. A logit coefficient is not a probability change. A count coefficient is not itself a percentage. If a point effect exists but matching uncertainty is not exposed, report that limitation and do not construct an interval yourself.

Use substantively justified sensitivity, such as a supported alternative family, link or adjustment set addressing a stated threat. Keep the primary result and explain what the comparison changes. Do not rank specifications by p-value or retain only a favorable result. Extra testing must remain within the user's scope, inference budget and approval boundaries.

## Completion self-check

Before declaring the requested analysis complete:

1. Verify the independent unit, sample, outcome coding and estimand, including any required exposure definition.
2. Verify an actual fitted count or binary model; the seed OLS result and descriptive statistics alone are insufficient.
3. Review applicable adequacy and inference diagnostics and explain unresolved findings.
4. Check that the effect scale, evaluation values and uncertainty answer the user's question and come from real server results.
5. Check a genuine sensitivity comparison and preserve references to the primary and alternative specifications.
6. Tie claims to genuine evidence_ref values, matching model_id/run_id and emitted post-estimation artifacts. State missing fields, observational limits and exploratory revisions explicitly.

This is a qualitative self-check, not a deterministic statistical certification. It does not verify a paper checklist or prove a result correct. Report complete, partial completion, blocked work or awaiting approval honestly. A completed workflow or exported report alone is not proof that the requested estimand was answered.

## Failure and partial completion

Stop after at most two unsuccessful attempts at the same blocked requirement. Make a concrete correction using the published contract and returned error, preserving both failed attempts. Do not retry with weaker validation, an invented option or a nearby unsupported method.

Pause affected work and name the missing evidence, capability, coding clarification or approval. Continue independent authorized work where useful, but state exactly which requested model, diagnostic, sensitivity or probability result remains incomplete. Do not announce completion on the strength of an unrelated fit or turn a failed specification into an unreported model search.
