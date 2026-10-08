"""The run submission request, declared once (V1812-CLI-FROM-CATALOG).

POST /runs builds its form signature from ``RUN_REQUEST_FIELDS`` and
``workbench run`` builds its options from it; both turn the submitted values
into the service's form with ``form_from_request`` and submit through
``services.run_service._submit_run``. A field added here reaches the API, the
generated frontend types and the command line together.

Standard library only: the command line imports this module at start-up.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

Encoding = Literal["text", "json_array", "comma", "json"]


@dataclass(frozen=True)
class RunField:
    """One submission field.

    ``default`` is the form default (``None`` = optional, sent only when
    given; ``required`` fields have none). ``many`` fields repeat on the
    command line and travel as ``encoding`` (a JSON array, or comma-joined).
    ``json`` fields hold a JSON document; the command line also reads one
    from ``@path``.
    """

    name: str
    help: str
    default: str | int | bool | None = ""
    required: bool = False
    many: bool = False
    encoding: Encoding = "text"
    cli_aliases: tuple[str, ...] = ()

    @property
    def annotation(self) -> Any:
        if isinstance(self.default, bool):
            return bool
        if isinstance(self.default, int):
            return int
        if self.default is None and not self.required:
            return str | None
        return str


RUN_REQUEST_FIELDS: tuple[RunField, ...] = (
    RunField("mode", "Pipeline mode.", "auto"),
    RunField("model_type", "Model type; `workbench models` lists them.", "auto"),
    RunField("y", "Outcome column.", None, required=True),
    RunField(
        "x", "Regressor column; repeat for several. Omit for zero-covariate DID families.",
        many=True, encoding="json_array",
    ),
    RunField("sheet_name", "Excel sheet to read."),
    RunField("transpose", "Read the sheet transposed: true | false.", "false"),
    RunField("imputation", "Missing-value imputation request (JSON)."),
    RunField("by_group", "Run the analysis separately by group (JSON)."),
    RunField("entity_col", "Panel entity (unit id) column, or the cluster column for clustered covariance."),
    RunField("time_col", "Panel time-period column."),
    RunField("covariance", "Covariance estimator: robust | clustered | unadjusted. Default: robust."),
    RunField("prediction_model_type", "Prediction model: prediction_lasso | prediction_ridge | prediction_random_forest."),
    RunField("prediction_cv_folds", "Cross-validation folds; 0 = engine default.", "0"),
    RunField("prediction_sampling_method", "Class-imbalance resampling: smote | oversample | undersample."),
    RunField("prediction_data_structure", "Prediction data structure: iid | grouped | temporal | panel.", None),
    RunField("prediction_entity_column", "Prediction panel entity column."),
    RunField("prediction_group_column", "Prediction group column."),
    RunField("prediction_time_column", "Prediction time column."),
    RunField("prediction_final_holdout_fraction", "Fraction of rows held out for the final evaluation.", None),
    RunField("prediction_shuffle", "Shuffle before splitting: true | false.", None),
    RunField("frequency_weight", "Frequency-weight column (Stata fweight)."),
    RunField("analysis_weight", "Analytic-weight column (Stata aweight)."),
    RunField("sampling_weight", "Sampling-weight column (Stata pweight)."),
    RunField("survey_strata_col", "Complex survey design: stratum column."),
    RunField("survey_psu_col", "Complex survey design: primary sampling unit column."),
    RunField("survey_fpc_col", "Complex survey design: finite population correction column."),
    RunField(
        "survey_replicate_weights", "Replicate weight column; repeat for several.",
        many=True, encoding="json_array", cli_aliases=("--survey-replicate-weight",),
    ),
    RunField("survey_replicate_type", "Replicate variance method: brr | jackknife | bootstrap | provided."),
    RunField("survey_lonely_psu", "Single-PSU stratum policy: fail | remove | adjust | average | certainty."),
    RunField("survey_weight_frame", "Panel weight semantics: cross_sectional | longitudinal."),
    RunField("survey_subpop", "Subpopulation expression evaluated on the full design."),
    RunField(
        "survey_df",
        "Coefficient test df under a survey design: design (default, #PSU - #strata) | design_minus_p (R survey).",
    ),
    RunField("iv_endog", "Endogenous regressor; repeat for several.", many=True, encoding="json_array"),
    RunField("iv_instruments", "Instrument column; repeat for several.", many=True, encoding="json_array"),
    RunField("did_mode", "DID design: cohort | two_by_two | status. Default: cohort."),
    RunField("did_cohort_col", "Cohort (first-treatment period) column; required for mode cohort."),
    RunField("did_treat_col", "Treated-group dummy column; required for mode two_by_two."),
    RunField("did_post_col", "Post-period dummy column; required for mode two_by_two."),
    RunField("did_status_col", "Per-period treatment-status column; required for mode status."),
    RunField("did_treatment_path", "Treatment-path column for dCDH (non-absorbing/switching treatment)."),
    RunField("cs_control_group", "Callaway-Sant'Anna control group: never | not_yet. Default: never."),
    RunField("cs_est_method", "Callaway-Sant'Anna estimation method: dr | reg | ipw. Default: dr."),
    RunField("cs_base_period", "Callaway-Sant'Anna base period: varying | universal. Default: varying."),
    RunField("cs_cluster_var", "Cluster column for Callaway-Sant'Anna inference."),
    RunField("cs_anticipation", "Anticipation periods for Callaway-Sant'Anna.", 0),
    RunField("honest_did", "Run the Rambachan-Roth honest-DID sensitivity analysis (slow).", False),
    RunField("focal_x", "Focal regressor; repeat for several.", many=True, encoding="comma"),
    RunField("model_options", "Model options (JSON object); `workbench models MODEL` lists the fields.", "{}", encoding="json"),
    RunField("labels", "Variable and value labels (JSON object).", "{}", encoding="json"),
    RunField("statistical_tests", "Statistical tests to run with the model (JSON object).", "{}", encoding="json"),
)

FIELDS_BY_NAME: Mapping[str, RunField] = {field.name: field for field in RUN_REQUEST_FIELDS}


class RunRequestError(ValueError):
    """A submitted value the run service cannot accept; ``detail`` is the API's 422 detail."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def encode_many(field: RunField, values: list[str]) -> str:
    """The wire text of a repeated command-line value."""

    if not values:
        return ""
    if field.encoding == "comma":
        return ",".join(values)
    return json.dumps(list(values), ensure_ascii=False)


def form_from_request(values: Mapping[str, Any]) -> dict[str, Any]:
    """The run service's form from submitted field values.

    ``values`` maps field names to their wire values (missing fields take
    their defaults). JSON documents are parsed here so a malformed one is
    refused before a run slot is taken.
    """

    from .model_options import ModelOptionsError, parse_model_options
    from .services.run_service import _normalize_labels

    def get(name: str) -> Any:
        return values.get(name, FIELDS_BY_NAME[name].default)

    try:
        model_options = parse_model_options(get("model_options"))
    except ModelOptionsError as exc:
        raise RunRequestError(exc.code) from exc
    try:
        labels = _normalize_labels(parse_model_options(get("labels")))
    except (ModelOptionsError, ValueError) as exc:
        raise RunRequestError(f"INVALID_LABELS: {exc}") from exc
    try:
        statistical_tests = parse_model_options(get("statistical_tests"))
    except ModelOptionsError as exc:
        raise RunRequestError(f"INVALID_STATISTICAL_TESTS: {exc.code}") from exc

    by_group = get("by_group")
    survey_df = get("survey_df")
    form: dict[str, Any] = {
        name: get(name)
        for name in (
            "mode", "model_type", "y", "x", "sheet_name", "transpose", "imputation",
            "entity_col", "time_col", "covariance",
            "prediction_model_type", "prediction_cv_folds", "prediction_sampling_method",
            "prediction_data_structure", "prediction_entity_column", "prediction_group_column",
            "prediction_time_column", "prediction_final_holdout_fraction", "prediction_shuffle",
            "frequency_weight", "analysis_weight", "sampling_weight",
            "survey_strata_col", "survey_psu_col", "survey_fpc_col", "survey_replicate_weights",
            "survey_replicate_type", "survey_lonely_psu", "survey_weight_frame", "survey_subpop",
            "iv_endog", "iv_instruments",
            "did_mode", "did_cohort_col", "did_treat_col", "did_post_col", "did_status_col",
            "did_treatment_path",
            "cs_control_group", "cs_est_method", "cs_base_period", "cs_cluster_var",
            "focal_x",
        )
    }
    if str(by_group).strip():
        form["by_group"] = by_group
    if str(survey_df).strip():
        form["survey_df"] = survey_df
    form["cs_anticipation"] = str(get("cs_anticipation"))
    form["honest_did"] = str(get("honest_did")).lower()
    form["model_options"] = model_options
    if labels:
        form["labels"] = labels
    if statistical_tests:
        form["statistical_tests"] = statistical_tests
    return form
