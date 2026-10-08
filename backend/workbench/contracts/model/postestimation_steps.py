"""What each post-estimation workflow step takes: summary, fields, required
fields and field types (V1812-CLI-FROM-CATALOG).

Pure data, imported without the statistics libraries, so the Agent's step
contracts and the `workbench postestimation` command line are generated from
the same declaration.
"""

from __future__ import annotations

from collections.abc import Mapping

MODEL_REF = (
    "Model node to read, as shown in the graph (`model:logit_1`, or its forest key); "
    "the model must belong to `model_run_id`, or to the workflow's target run when that is omitted. "
    "For a model fitted earlier in this same plan, use `step:<step_id>:<branch_id>`; "
    "the named producer declares that branch, and its dependency is added automatically. "
    "Do not guess a future run id or model node id."
)
MODEL_RUN = "Run that owns `model_ref`; omit it for the workflow's target run."
LEVEL = "Confidence level, default 0.95."

# operation -> (summary, fields, required, field types)
STEP_SHAPES: Mapping[str, tuple[str, Mapping[str, str], tuple[str, ...], Mapping[str, str]]] = {
    "wald": (
        "Jointly test linear restrictions on a completed model's coefficients (Wald). "
        "Reads the model's stored covariance; F or chi-square follows the model's own inference.",
        {
            "model_ref": MODEL_REF,
            "model_run_id": MODEL_RUN,
            "constraints": (
                "Non-empty list of {terms, value}: `terms` maps coefficient names to weights and "
                "the restriction is sum(weight * coefficient) = value. Joint significance of x1 "
                "and x2 is [{terms: {x1: 1}, value: 0}, {terms: {x2: 1}, value: 0}]."
            ),
        },
        ("model_ref", "constraints"),
        {"model_ref": "string", "model_run_id": "string", "constraints": "list"},
    ),
    "lincom": (
        "Estimate a linear combination of a completed model's coefficients, with its standard "
        "error, test and confidence interval.",
        {
            "model_ref": MODEL_REF,
            "model_run_id": MODEL_RUN,
            "terms": "Object mapping coefficient names to weights.",
            "constant": "Number added to the combination, default 0.",
            "level": LEVEL,
        },
        ("model_ref", "terms"),
        {"model_ref": "string", "model_run_id": "string", "terms": "object", "constant": "number", "level": "number"},
    ),
    "nlcom": (
        "Estimate a smooth function of a completed model's coefficients by the delta method.",
        {
            "model_ref": MODEL_REF,
            "model_run_id": MODEL_RUN,
            "expression": (
                "Arithmetic over coefficient names: + - * / **, exp, log, sqrt; write a name that is "
                "not an identifier as b[\"name\"]. Example: x1 / x2."
            ),
            "level": LEVEL,
        },
        ("model_ref", "expression"),
        {"model_ref": "string", "model_run_id": "string", "expression": "string", "level": "number"},
    ),
    "lr": (
        "Likelihood-ratio test of a restricted model nested in a fuller one. Both must be "
        "estimated on the same rows with model-based (not robust or clustered) variance. "
        "If the user's original model has robust, clustered or design-based variance, explain "
        "that LR uses the model likelihood and requires two new fits with model-based variance; "
        "keep the original model and actively offer a Wald test using its original covariance "
        "as an alternative. Do not automatically add a Wald step merely because the user asks "
        "you to offer that option; include it only when execution of Wald is requested. "
        "Fit both branches and then reference them in one plan with one confirmation.",
        {
            "model_ref": "The fuller model. " + MODEL_REF,
            "model_run_id": MODEL_RUN,
            "restricted_model_ref": "The restricted model nested in it. " + MODEL_REF,
            "restricted_model_run_id": "Run that owns the restricted model; omit for the target run.",
        },
        ("model_ref", "restricted_model_ref"),
        {
            "model_ref": "string", "model_run_id": "string",
            "restricted_model_ref": "string", "restricted_model_run_id": "string",
        },
    ),
    "margins": (
        "Marginal effects of regressors on the predicted outcome: averaged over the estimation "
        "sample (`at: average`) or at the regressors' means (`at: means`).",
        {
            "model_ref": MODEL_REF,
            "model_run_id": MODEL_RUN,
            "variables": "Non-empty list of regressor names.",
            "at": "`average` (default) or `means`.",
            "level": LEVEL,
        },
        ("model_ref", "variables"),
        {"model_ref": "string", "model_run_id": "string", "variables": "list", "at": "string", "level": "number"},
    ),
}
