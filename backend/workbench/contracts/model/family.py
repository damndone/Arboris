"""Model-family contracts: what each family accepts, builds and returns.

One ``ModelFamilyContract`` per family declares the fields a fit takes, how its
engine parameters are built, the weights, covariance and split kinds it
allows, its model_options fields and validators, and the artifacts and result
shape it produces. The engine, the orchestrator, admission, the capability
catalog and the Agent all read this table; it lives in the contract layer so
none of them depends on another for it (moved from ``agent/workflow_contracts``
in v1.8.12, V1812-CONTRACT-LAYERING).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import pandas as pd

from ..common.errors import OperationValidationError
from .result_shapes import (
    ResultShapeError,
    get_result_shape,
    is_registered,
    register_result_shape,
    registered_result_shapes,
)

# Closed values are declarations owned by the contract layer. Consumers
# (schema projection, validation, and Agent vocabulary) must derive from these
# tuples instead of maintaining another list of accepted strings.
WORKFLOW_SPLIT_KINDS = ("iid", "grouped", "temporal", "panel")
DID_MODE_VALUES = ("cohort", "two_by_two", "status")


ModelParameterBuilder = Callable[[Mapping[str, Any], Mapping[str, Any], list[str], str], dict[str, Any]]
ModelFamilySpecValidator = Callable[[Mapping[str, Any]], None]
ModelFamilyDataValidator = Callable[[pd.DataFrame, Mapping[str, Any]], None]

@dataclass(frozen=True)
class ModelFamilyContract:
    """The complete workflow admission contract for one model family.

    The contract separates a family from the runtime's execution mechanics:
    validation, Genesis parameters, required evidence, and result semantics all
    travel together.  A future family therefore cannot silently inherit OLS
    diagnostics or coefficient-interval assumptions merely because it reaches
    the generic workflow executor.
    """

    family: str
    required_spec_fields: tuple[str, ...]
    required_spec_field_mode: str
    forbidden_spec_fields: tuple[str, ...]
    build_model_params: ModelParameterBuilder
    expected_artifacts: tuple[str, ...]
    result_shape: str
    missing_required_fields_message: str | None = None
    forbidden_spec_fields_message: str | None = None
    cluster_requires_entity: bool = False
    allows_categorical_terms: bool = True
    allows_polynomial_terms: bool = True
    requires_nonempty_predictors: bool = True
    allows_covariance: bool = True
    #: v1.8.11. The covariance a branch gets when it names none. Panel and DID
    #: fits cluster by entity, as Stata's xtreg, fe vce(robust); the others keep
    #: the conventional default.
    default_covariance: str = "unadjusted"
    allows_weights: tuple[str, ...] = ()
    #: v1.8.7. Which statsmodels GLM link this family's fit corresponds to, if
    #: any. Declaring it is the whole cost of joining the design-variance engine
    #: -- the shared adapter does the rest, and neither the engine nor the
    #: adapter ever asks which family it is holding.
    survey_glm_family: str | None = None
    supported_split_kinds: tuple[str, ...] = ()
    requires_branch_figures: bool = False
    context_spec_fields: tuple[str, ...] = ()
    column_spec_fields: tuple[str, ...] = ()
    builds_native_params: bool = False
    validate_spec: ModelFamilySpecValidator | None = None
    validate_branch_frame: ModelFamilyDataValidator | None = None
    model_options_fields: tuple[str, ...] = ()
    model_options_required_fields: tuple[str, ...] = ()
    model_options_column_fields: tuple[str, ...] = ()
    validate_model_options: ModelFamilySpecValidator | None = None
    #: v1.8.12. What a Notebook option of this family publishes: artifact id
    #: -> artifact kind. Each id is one of ``expected_artifacts`` or a part of
    #: one (``<artifact>.<part>``). Empty means the primary expected artifact
    #: as a ``model_result``.
    published_artifacts: tuple[tuple[str, str], ...] = ()

    @property
    def published_artifact_types(self) -> dict[str, str]:
        if self.published_artifacts:
            return dict(self.published_artifacts)
        return {self.expected_artifacts[0]: "model_result"}

    def __post_init__(self) -> None:
        if self.required_spec_field_mode not in {"all", "any"}:
            raise ValueError("ModelFamilyContract required_spec_field_mode is invalid")
        # The shape must be declared, not drawn from a fixed list.  A closed
        # enum here is what kept factor loadings, reliability coefficients and
        # cluster assignments from being registrable at all -- their results are
        # none of the three kinds a regression produces.
        if not is_registered(self.result_shape):
            raise ResultShapeError(
                f"ModelFamilyContract result_shape {self.result_shape!r} is not declared; "
                "call register_result_shape() with its minimal payload schema first"
            )
        if not self.family or not self.expected_artifacts:
            raise ValueError("ModelFamilyContract requires family and expected artifacts")
        if not set(self.column_spec_fields) <= set(self.context_spec_fields):
            raise ValueError("ModelFamilyContract column fields must be context fields")
        allowed_weight_kinds = {"sampling", "analysis", "frequency"}
        if any(weight not in allowed_weight_kinds for weight in self.allows_weights):
            raise ValueError("ModelFamilyContract allows_weights contains an unknown weight kind")
        if len(set(self.allows_weights)) != len(self.allows_weights):
            raise ValueError("ModelFamilyContract allows_weights must not contain duplicates")
        allowed_split_kinds = set(WORKFLOW_SPLIT_KINDS)
        if any(split not in allowed_split_kinds for split in self.supported_split_kinds):
            raise ValueError("ModelFamilyContract supported_split_kinds contains an unknown split kind")
        if len(set(self.supported_split_kinds)) != len(self.supported_split_kinds):
            raise ValueError("ModelFamilyContract supported_split_kinds must not contain duplicates")
        if len(set(self.model_options_fields)) != len(self.model_options_fields):
            raise ValueError("ModelFamilyContract model_options_fields must not contain duplicates")
        if not set(self.model_options_required_fields) <= set(self.model_options_fields):
            raise ValueError(
                "ModelFamilyContract model_options_required_fields must be declared"
            )
        if not set(self.model_options_column_fields) <= set(self.model_options_fields):
            raise ValueError(
                "ModelFamilyContract model_options_column_fields must be declared"
            )
        published_ids = [artifact_id for artifact_id, _ in self.published_artifacts]
        if len(set(published_ids)) != len(published_ids):
            raise ValueError("ModelFamilyContract published artifact ids must not repeat")
        for artifact_id, kind in self.published_artifacts:
            own = any(
                artifact_id == expected or artifact_id.startswith(expected + ".")
                for expected in self.expected_artifacts
            )
            if not own or not isinstance(kind, str) or not kind:
                raise ValueError(
                    f"ModelFamilyContract published artifact {artifact_id!r} must be one of the "
                    "family's expected artifacts (or a part of one) with a non-empty kind"
                )

def _build_ols_model_params(
    spec: Mapping[str, Any], branch: Mapping[str, Any], predictors: list[str], covariance: str
) -> dict[str, Any]:
    from .ols import OLS_HAC_FIELDS

    options = spec.get("model_options") or {}
    hac = {key: options[key] for key in OLS_HAC_FIELDS if key in options} if covariance == "hac" else {}
    return {
        "model_type": "ols",
        "y": branch["outcome"],
        "x": list(predictors),
        "covariance": covariance,
        "model_options": {"covariance": covariance, **hac},
    }

def _build_panel_ols_model_params(
    spec: Mapping[str, Any], branch: Mapping[str, Any], predictors: list[str], covariance: str
) -> dict[str, Any]:
    return {
        "model_type": "panel_ols",
        "y": branch["outcome"],
        "x": list(predictors),
        "covariance": covariance,
        "model_options": _panel_model_options(spec, covariance),
        "entity_col": spec.get("entity_col"),
        "time_col": spec.get("time_col"),
    }

def _panel_model_options(spec: Mapping[str, Any], covariance: str) -> dict[str, Any]:
    """A panel or DID fit's options: its covariance and, if named, its cluster column."""
    cluster = (spec.get("model_options") or {}).get("cluster")
    return {"covariance": covariance, **({"cluster": cluster} if cluster else {})}

def _build_generalized_model_params(
    model_type: str,
) -> ModelParameterBuilder:
    def _build(
        spec: Mapping[str, Any], branch: Mapping[str, Any], predictors: list[str], covariance: str
    ) -> dict[str, Any]:
        return {
            "model_type": model_type,
            "y": branch["outcome"],
            "x": list(predictors),
        }

    return _build

def _build_model_params_with_options(
    model_type: str,
) -> ModelParameterBuilder:
    def _build(
        spec: Mapping[str, Any], branch: Mapping[str, Any], predictors: list[str], covariance: str
    ) -> dict[str, Any]:
        return {
            "model_type": model_type,
            "y": branch["outcome"],
            "x": list(predictors),
            "model_options": dict(spec.get("model_options") or {}),
        }

    return _build

def validate_family_options(
    spec: Mapping[str, Any], contract: ModelFamilyContract
) -> None:
    raw_options = spec.get("model_options")
    options = {} if raw_options is None else raw_options
    if not isinstance(options, Mapping):
        raise OperationValidationError(
            f"model.genesis {contract.family} model_options must be an object"
        )
    unknown = sorted(set(options) - set(contract.model_options_fields))
    if unknown:
        raise OperationValidationError(
            f"model.genesis {contract.family} model_options does not accept field(s): "
            + ", ".join(unknown)
        )
    missing = sorted(
        field_name
        for field_name in contract.model_options_required_fields
        if field_name not in options or options[field_name] in (None, "")
    )
    if missing:
        raise OperationValidationError(
            f"model.genesis {contract.family} model_options requires: "
            + ", ".join(missing)
        )
    if contract.validate_model_options is not None:
        contract.validate_model_options(options)

def _validate_nb_options(options: Mapping[str, Any]) -> None:
    from .count_models import validate_negative_binomial_model_options
    try:
        validate_negative_binomial_model_options(options)
    except ValueError as exc:
        raise OperationValidationError(str(exc)) from exc

def _validate_glm_nb_options(options: Mapping[str, Any]) -> None:
    from .count_models import validate_glm_family_options
    try:
        validate_glm_family_options(options, "negative_binomial")
    except ValueError as exc:
        raise OperationValidationError(str(exc)) from exc

def _validate_ordinal_model_options(options: Mapping[str, Any]) -> None:
    if "optimizer" in options and options["optimizer"] not in {"bfgs", "lbfgs"}:
        raise OperationValidationError(
            "model.genesis ordinal_logit model_options.optimizer must be bfgs or lbfgs"
        )
    if "link" in options and options["link"] not in {"logit", "probit"}:
        raise OperationValidationError(
            "model.genesis ordinal_logit model_options.link must be logit or probit"
        )
    outcome_order = options.get("outcome_order")
    if outcome_order is not None and (
        not isinstance(outcome_order, list)
        or len(outcome_order) < 3
        or any(not isinstance(level, str) or not level for level in outcome_order)
        or len(set(outcome_order)) != len(outcome_order)
    ):
        raise OperationValidationError(
            "model.genesis ordinal_logit model_options.outcome_order must be a list of at least three unique non-empty labels"
        )
    maxiter = options.get("maxiter")
    if maxiter is not None and (
        not isinstance(maxiter, int) or isinstance(maxiter, bool) or not 50 <= maxiter <= 5000
    ):
        raise OperationValidationError(
            "model.genesis ordinal_logit model_options.maxiter must be an integer between 50 and 5000"
        )

def _validate_multinomial_model_options(options: Mapping[str, Any]) -> None:
    if "base_category" in options and (
        not isinstance(options["base_category"], str) or not options["base_category"]
    ):
        raise OperationValidationError(
            "model.genesis multinomial_logit model_options.base_category must be a non-empty string"
        )
    maxiter = options.get("maxiter")
    if maxiter is not None and (
        not isinstance(maxiter, int) or isinstance(maxiter, bool) or not 50 <= maxiter <= 5000
    ):
        raise OperationValidationError(
            "model.genesis multinomial_logit model_options.maxiter must be an integer between 50 and 5000"
        )

def _validate_survival_model_options(options: Mapping[str, Any]) -> None:
    for field_name in ("event_column", "group_column", "entry_column"):
        if field_name in options and (
            not isinstance(options[field_name], str) or not options[field_name]
        ):
            raise OperationValidationError(
                f"model.genesis survival_cox model_options.{field_name} must be a non-empty string"
            )
    if options.get("ties", "breslow") not in {"breslow", "efron"}:
        raise OperationValidationError(
            "model.genesis survival_cox model_options.ties must be breslow or efron"
        )

def _validate_quantile_model_options(options: Mapping[str, Any]) -> None:
    quantiles = options.get("quantiles", [0.25, 0.5, 0.75])
    if (
        not isinstance(quantiles, list)
        or not quantiles
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not np.isfinite(float(value))
            or not 0 < float(value) < 1
            for value in quantiles
        )
        or len(set(float(value) for value in quantiles)) != len(quantiles)
        or len(quantiles) > 7
    ):
        raise OperationValidationError(
            "model.genesis quantile_regression model_options.quantiles must be a unique list of at most seven values strictly between 0 and 1"
        )
    bootstrap_reps = options.get("bootstrap_reps", 0)
    if (
        not isinstance(bootstrap_reps, int)
        or isinstance(bootstrap_reps, bool)
        or not 0 <= bootstrap_reps <= 1000
    ):
        raise OperationValidationError(
            "model.genesis quantile_regression model_options.bootstrap_reps must be an integer between 0 and 1000"
        )
    random_state = options.get("random_state")
    if random_state is not None and (
        not isinstance(random_state, int)
        or isinstance(random_state, bool)
        or random_state < 0
    ):
        raise OperationValidationError(
            "model.genesis quantile_regression model_options.random_state must be a non-negative integer"
        )

def _validate_ordinal_outcome(frame: pd.DataFrame, branch: Mapping[str, Any]) -> None:
    outcome = branch.get("outcome")
    if not isinstance(outcome, str) or outcome not in frame.columns:
        raise OperationValidationError(
            "model.genesis ordinal_logit requires an available outcome before execution"
        )
    if frame[outcome].dropna().nunique() < 3:
        raise OperationValidationError(
            "model.genesis ordinal_logit requires at least three ordered outcome levels"
        )

def _validate_multinomial_outcome(frame: pd.DataFrame, branch: Mapping[str, Any]) -> None:
    outcome = branch.get("outcome")
    if not isinstance(outcome, str) or outcome not in frame.columns:
        raise OperationValidationError(
            "model.genesis multinomial_logit requires an available outcome before execution"
        )
    if frame[outcome].dropna().nunique() < 3:
        raise OperationValidationError(
            "model.genesis multinomial_logit requires at least three outcome levels"
        )

def _validate_continuous_outcome(frame: pd.DataFrame, branch: Mapping[str, Any]) -> None:
    _require_outcome_values(frame, branch, "quantile_regression")

def _require_outcome_values(
    frame: pd.DataFrame, branch: Mapping[str, Any], family: str
) -> pd.Series:
    outcome = branch.get("outcome")
    if not isinstance(outcome, str) or outcome not in frame.columns:
        raise OperationValidationError(
            f"model.genesis {family} requires an available outcome before execution"
        )
    values = pd.to_numeric(frame[outcome], errors="coerce").dropna()
    if values.empty or not np.isfinite(values).all():
        raise OperationValidationError(
            f"model.genesis {family} requires finite numeric outcome values before execution"
        )
    return values

def _validate_binary_outcome(
    family: str,
) -> ModelFamilyDataValidator:
    def _validate(frame: pd.DataFrame, branch: Mapping[str, Any]) -> None:
        values = _require_outcome_values(frame, branch, family)
        if not values.isin((0, 1)).all():
            raise OperationValidationError(
                f"model.genesis {family} requires a binary 0/1 outcome before execution"
            )

    return _validate

def _validate_count_outcome(
    family: str,
) -> ModelFamilyDataValidator:
    def _validate(frame: pd.DataFrame, branch: Mapping[str, Any]) -> None:
        values = _require_outcome_values(frame, branch, family)
        if (values < 0).any() or not np.isclose(values, np.round(values)).all():
            raise OperationValidationError(
                f"model.genesis {family} requires a non-negative integer count outcome before execution"
            )

    return _validate

def _validate_nb_outcome(frame: pd.DataFrame, branch: Mapping[str, Any]) -> None:
    values = _require_outcome_values(frame, branch, "negative_binomial")
    fixed = (branch.get("model_options") or {}).get("alpha") is not None
    if (values < 0).any() or (not fixed and not (values == np.floor(values)).all()):
        raise OperationValidationError("NB_COUNTS_INVALID: estimated dispersion requires integer counts; fixed alpha allows finite nonnegative responses.")

def _validate_fixed_count_outcome(frame: pd.DataFrame, branch: Mapping[str, Any]) -> None:
    values = _require_outcome_values(frame, branch, "fixed-dispersion GLM")
    if (values < 0).any():
        raise OperationValidationError("GLM_RESPONSE_INVALID: fixed count-family GLM requires finite nonnegative responses.")

def _build_iv_2sls_model_params(
    spec: Mapping[str, Any], branch: Mapping[str, Any], predictors: list[str], covariance: str
) -> dict[str, Any]:
    return {
        "model_type": "iv_2sls",
        "y": branch["outcome"],
        "x": list(predictors),
        "iv_endog": list(spec["iv_endog"]),
        "iv_instruments": list(spec["iv_instruments"]),
        "covariance": covariance,
    }

def _build_did_model_params(
    spec: Mapping[str, Any], branch: Mapping[str, Any], predictors: list[str], covariance: str
) -> dict[str, Any]:
    model_params = {
        "model_type": "did",
        "y": branch["outcome"],
        "x": list(predictors),
        "entity_col": spec["entity_col"],
        "time_col": spec["time_col"],
        "did_mode": spec["did_mode"],
        "covariance": covariance,
        "model_options": _panel_model_options(spec, covariance),
    }
    for field_name in ("did_cohort_col", "did_treat_col", "did_post_col", "did_status_col"):
        value = spec.get(field_name)
        if value is not None:
            model_params[field_name] = value
    return model_params

def _require_column_list(spec: Mapping[str, Any], field_name: str, family: str) -> list[str]:
    value = spec.get(field_name)
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise OperationValidationError(
            f"model.genesis {family} requires a non-empty {field_name} column list"
        )
    if len(set(value)) != len(value):
        raise OperationValidationError(
            f"model.genesis {family} {field_name} must not contain duplicate columns"
        )
    return list(value)

def _validate_iv_2sls_spec(spec: Mapping[str, Any]) -> None:
    from ...engine.iv_spec import IVSpecError, validate_iv_spec

    endog = _require_column_list(spec, "iv_endog", "iv_2sls")
    instruments = _require_column_list(spec, "iv_instruments", "iv_2sls")
    for branch in spec["branches"]:
        try:
            validate_iv_spec(
                y=str(branch["outcome"]),
                exog=[str(item) for item in branch["predictors"]],
                endog=endog,
                instruments=instruments,
            )
        except IVSpecError as exc:
            raise OperationValidationError(f"model.genesis iv_2sls: {exc}") from exc

def _require_column(spec: Mapping[str, Any], field_name: str, family: str) -> str:
    value = spec.get(field_name)
    if not isinstance(value, str) or not value:
        raise OperationValidationError(
            f"model.genesis {family} requires {field_name} for the selected treatment definition"
        )
    return value

def _validate_did_spec(spec: Mapping[str, Any]) -> None:
    mode = spec.get("did_mode")
    if mode not in DID_MODE_VALUES:
        raise OperationValidationError(
            "model.genesis did requires did_mode: " + ", ".join(DID_MODE_VALUES)
        )
    if mode == "cohort":
        _require_column(spec, "did_cohort_col", "did")
    elif mode == "two_by_two":
        _require_column(spec, "did_treat_col", "did")
        _require_column(spec, "did_post_col", "did")
    else:
        _require_column(spec, "did_status_col", "did")

def _build_cs_did_model_params(
    spec: Mapping[str, Any], branch: Mapping[str, Any], predictors: list[str], covariance: str
) -> dict[str, Any]:
    return {
        "model_type": "cs_did",
        "y": branch["outcome"],
        "x": list(predictors),
        "entity_col": spec["entity_col"],
        "time_col": spec["time_col"],
        "did_mode": "cohort",
        "did_cohort_col": spec["cohort_col"],
    }

def _build_sa_did_model_params(
    spec: Mapping[str, Any], branch: Mapping[str, Any], predictors: list[str], covariance: str
) -> dict[str, Any]:
    return {
        "model_type": "sa_did",
        "y": branch["outcome"],
        "x": list(predictors),
        "entity_col": spec["entity_col"],
        "time_col": spec["time_col"],
        "did_mode": "cohort",
        "did_cohort_col": spec["cohort_col"],
    }

def _build_dcdh_model_params(
    spec: Mapping[str, Any], branch: Mapping[str, Any], predictors: list[str], covariance: str
) -> dict[str, Any]:
    return {
        "model_type": "dcdh",
        "y": branch["outcome"],
        "x": list(predictors),
        "entity_col": spec["entity_col"],
        "time_col": spec["time_col"],
        "did_treatment_path": spec["treatment_path_col"],
    }

MODEL_FAMILY_CONTRACTS: dict[str, ModelFamilyContract] = {
    "anova": ModelFamilyContract(
        family="anova",
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=lambda spec: {},
        expected_artifacts=("anova_1",),
        result_shape="anova_table",
        allows_covariance=False,
        model_options_fields=("sums_of_squares", "categorical", "interactions", "posthoc"),
        model_options_required_fields=("sums_of_squares",),
    ),
    "ols": ModelFamilyContract(
        family="ols",
        survey_glm_family="gaussian",
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_ols_model_params,
        expected_artifacts=("ols_1", "diagnostic_summary"),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message="model.genesis ols does not accept panel entity_col or time_col",
        # HAC (Newey-West) takes its time order here, not as time_col: for OLS
        # time_col would mean panel time effects, which OLS does not estimate.
        model_options_fields=("time_order", "hac_lags"),
        model_options_column_fields=("time_order",),
        allows_weights=("frequency", "analysis", "sampling"),
        supported_split_kinds=("iid", "grouped"),
        requires_branch_figures=True,
    ),
    "logit": ModelFamilyContract(
        family="logit",
        survey_glm_family="binomial",
        allows_weights=("sampling",),
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_generalized_model_params("logit"),
        expected_artifacts=("logit_1", "diagnostics_logit_1", "diagnostic_summary"),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message="model.genesis logit does not accept panel entity_col or time_col",
        allows_covariance=False,
        validate_branch_frame=_validate_binary_outcome("logit"),
    ),
    "probit": ModelFamilyContract(
        family="probit",
        survey_glm_family="binomial",
        allows_weights=("sampling",),
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_generalized_model_params("probit"),
        expected_artifacts=("probit_1", "diagnostics_probit_1", "diagnostic_summary"),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message="model.genesis probit does not accept panel entity_col or time_col",
        allows_covariance=False,
        validate_branch_frame=_validate_binary_outcome("probit"),
    ),
    "poisson": ModelFamilyContract(
        family="poisson",
        survey_glm_family="poisson",
        allows_weights=("sampling",),
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_generalized_model_params("poisson"),
        expected_artifacts=("poisson_1", "diagnostics_poisson_1", "diagnostic_summary"),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message="model.genesis poisson does not accept panel entity_col or time_col",
        allows_covariance=False,
        validate_branch_frame=_validate_count_outcome("poisson"),
    ),
    "negative_binomial": ModelFamilyContract(
        family="negative_binomial",
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_model_params_with_options("negative_binomial"),
        expected_artifacts=(
            "negative_binomial_1",
            "diagnostics_negative_binomial_1",
            "diagnostic_summary",
        ),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message=(
            "model.genesis negative_binomial does not accept panel entity_col or time_col"
        ),
        allows_covariance=False,
        validate_branch_frame=_validate_nb_outcome,
        model_options_fields=("dispersion", "alpha"),
        validate_model_options=_validate_nb_options,
    ),
    "glm:binomial": ModelFamilyContract(
        family="glm:binomial",
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_generalized_model_params("glm:binomial"),
        expected_artifacts=("glm_1",),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message=(
            "model.genesis glm:binomial does not accept panel entity_col or time_col"
        ),
        allows_covariance=False,
        validate_branch_frame=_validate_binary_outcome("glm:binomial"),
    ),
    "glm:poisson": ModelFamilyContract(
        family="glm:poisson",
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_generalized_model_params("glm:poisson"),
        expected_artifacts=("glm_1",),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message=(
            "model.genesis glm:poisson does not accept panel entity_col or time_col"
        ),
        allows_covariance=False,
        validate_branch_frame=_validate_count_outcome("glm:poisson"),
    ),
    "glm:negative_binomial": ModelFamilyContract(
        family="glm:negative_binomial",
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_model_params_with_options("glm:negative_binomial"),
        expected_artifacts=("glm_1",),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message=(
            "model.genesis glm:negative_binomial does not accept panel entity_col or time_col"
        ),
        allows_covariance=False,
        validate_branch_frame=_validate_fixed_count_outcome,
        model_options_fields=("alpha",),
        model_options_required_fields=("alpha",),
        validate_model_options=_validate_glm_nb_options,
    ),
    "panel_ols": ModelFamilyContract(
        family="panel_ols",
        required_spec_fields=("entity_col", "time_col"),
        required_spec_field_mode="any",
        forbidden_spec_fields=(),
        build_model_params=_build_panel_ols_model_params,
        expected_artifacts=("panel_ols_1",),
        result_shape="coefficient_intervals",
        missing_required_fields_message=(
            "model.genesis panel_ols requires entity_col or time_col"
        ),
        cluster_requires_entity=True,
        default_covariance="clustered",
        allows_categorical_terms=False,
        context_spec_fields=("entity_col", "time_col"),
        column_spec_fields=("entity_col", "time_col"),
    ),
    "iv_2sls": ModelFamilyContract(
        family="iv_2sls",
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_iv_2sls_model_params,
        expected_artifacts=(
            "iv_2sls_1",
            "diagnostics_iv_2sls_1",
            "iv_diagnostics",
            "diagnostic_summary",
        ),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message="model.genesis iv_2sls does not accept panel entity_col or time_col",
        requires_nonempty_predictors=False,
        context_spec_fields=("iv_endog", "iv_instruments"),
        column_spec_fields=("iv_endog", "iv_instruments"),
        builds_native_params=True,
        validate_spec=_validate_iv_2sls_spec,
    ),
    "did": ModelFamilyContract(
        family="did",
        required_spec_fields=("entity_col", "time_col"),
        required_spec_field_mode="all",
        forbidden_spec_fields=(),
        build_model_params=_build_did_model_params,
        expected_artifacts=(
            "did_1",
            "diagnostics_did_1",
            "did_diagnostics",
            "diagnostic_summary",
        ),
        result_shape="coefficient_intervals",
        missing_required_fields_message="model.genesis did requires entity_col and time_col",
        requires_nonempty_predictors=False,
        default_covariance="clustered",
        context_spec_fields=(
            "entity_col",
            "time_col",
            "did_mode",
            "did_cohort_col",
            "did_treat_col",
            "did_post_col",
            "did_status_col",
        ),
        column_spec_fields=(
            "entity_col",
            "time_col",
            "did_cohort_col",
            "did_treat_col",
            "did_post_col",
            "did_status_col",
        ),
        builds_native_params=True,
        validate_spec=_validate_did_spec,
    ),
    "cs_did": ModelFamilyContract(
        family="cs_did",
        required_spec_fields=("entity_col", "time_col", "cohort_col"),
        required_spec_field_mode="all",
        forbidden_spec_fields=(),
        build_model_params=_build_cs_did_model_params,
        expected_artifacts=("cs_did_1", "cs_did"),
        result_shape="effect_estimate_bundle",
        missing_required_fields_message=(
            "model.genesis cs_did requires entity_col, time_col, and cohort_col"
        ),
        allows_categorical_terms=False,
        allows_polynomial_terms=False,
        requires_nonempty_predictors=False,
        allows_covariance=False,
        context_spec_fields=("entity_col", "time_col", "cohort_col"),
        column_spec_fields=("entity_col", "time_col", "cohort_col"),
        builds_native_params=True,
    ),
    "sa_did": ModelFamilyContract(
        family="sa_did",
        required_spec_fields=("entity_col", "time_col", "cohort_col"),
        required_spec_field_mode="all",
        forbidden_spec_fields=(),
        build_model_params=_build_sa_did_model_params,
        expected_artifacts=("sa_did_1", "sa_did"),
        result_shape="effect_estimate_bundle",
        missing_required_fields_message=(
            "model.genesis sa_did requires entity_col, time_col, and cohort_col"
        ),
        allows_categorical_terms=False,
        allows_polynomial_terms=False,
        requires_nonempty_predictors=False,
        allows_covariance=False,
        context_spec_fields=("entity_col", "time_col", "cohort_col"),
        column_spec_fields=("entity_col", "time_col", "cohort_col"),
        builds_native_params=True,
    ),
    "dcdh": ModelFamilyContract(
        family="dcdh",
        required_spec_fields=("entity_col", "time_col", "treatment_path_col"),
        required_spec_field_mode="all",
        forbidden_spec_fields=(),
        build_model_params=_build_dcdh_model_params,
        expected_artifacts=("dcdh_1", "dcdh"),
        result_shape="event_study_bundle",
        missing_required_fields_message=(
            "model.genesis dcdh requires entity_col, time_col, and treatment_path_col"
        ),
        allows_categorical_terms=False,
        allows_polynomial_terms=False,
        requires_nonempty_predictors=False,
        allows_covariance=False,
        context_spec_fields=("entity_col", "time_col", "treatment_path_col"),
        column_spec_fields=("entity_col", "time_col", "treatment_path_col"),
        builds_native_params=True,
    ),
    "ordinal_logit": ModelFamilyContract(
        family="ordinal_logit",
        published_artifacts=(("ordinal_logit_1", "model_result"), ("diagnostics_ordinal_logit_1", "diagnostic_result")),
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_model_params_with_options("ordinal_logit"),
        expected_artifacts=("ordinal_logit_1", "diagnostics_ordinal_logit_1"),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message=(
            "model.genesis ordinal_logit does not accept panel entity_col or time_col"
        ),
        allows_covariance=False,
        allows_categorical_terms=False,
        allows_polynomial_terms=False,
        model_options_fields=("optimizer", "maxiter", "link", "outcome_order"),
        validate_model_options=_validate_ordinal_model_options,
        validate_branch_frame=_validate_ordinal_outcome,
        supported_split_kinds=("iid", "grouped"),
    ),
    "multinomial_logit": ModelFamilyContract(
        family="multinomial_logit",
        published_artifacts=(
            ("multinomial_logit_1", "model_result"),
            ("diagnostics_multinomial_logit_1", "diagnostic_result"),
        ),
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_model_params_with_options("multinomial_logit"),
        expected_artifacts=("multinomial_logit_1", "diagnostics_multinomial_logit_1"),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message=(
            "model.genesis multinomial_logit does not accept panel entity_col or time_col"
        ),
        allows_covariance=False,
        allows_categorical_terms=False,
        allows_polynomial_terms=False,
        model_options_fields=("maxiter", "base_category"),
        validate_model_options=_validate_multinomial_model_options,
        validate_branch_frame=_validate_multinomial_outcome,
        supported_split_kinds=("iid", "grouped"),
    ),
    "survival_cox": ModelFamilyContract(
        family="survival_cox",
        published_artifacts=(("survival_cox_1", "model_result"), ("survival_evidence", "survival_evidence")),
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_model_params_with_options("survival_cox"),
        expected_artifacts=("survival_cox_1", "survival_evidence"),
        result_shape="effect_estimate_bundle",
        forbidden_spec_fields_message=(
            "model.genesis survival_cox does not accept panel entity_col or time_col"
        ),
        allows_covariance=False,
        allows_categorical_terms=False,
        allows_polynomial_terms=False,
        model_options_fields=("event_column", "group_column", "entry_column", "ties"),
        model_options_required_fields=("event_column",),
        model_options_column_fields=("event_column", "group_column", "entry_column"),
        validate_model_options=_validate_survival_model_options,
        supported_split_kinds=("iid", "grouped"),
    ),
    # v1.8.7. LMM was the one family the form could run and an Agent could not
    # start. Nothing about its execution changes here -- the options contract,
    # the pre-fit sealed input and the packet envelope are untouched; this only
    # states, where every other family states it, which declarations it takes.
    "linear_mixed_effects": ModelFamilyContract(
        family="linear_mixed_effects",
        published_artifacts=(("linear_mixed_effects_1.result", "model_result_packet"),),
        required_spec_fields=(),
        required_spec_field_mode="all",
        # The repeated-measures structure lives in model_options, not in the
        # panel fields: `subject_id` is the unit measured repeatedly, which is
        # not the same idea as a panel entity with fixed effects.
        forbidden_spec_fields=("entity_col", "time_col"),
        forbidden_spec_fields_message=(
            "model.genesis linear_mixed_effects takes subject_id and time through "
            "model_options, not the panel entity_col/time_col fields"
        ),
        build_model_params=_build_model_params_with_options("linear_mixed_effects"),
        expected_artifacts=("linear_mixed_effects_1",),
        result_shape="coefficient_intervals",
        allows_covariance=False,
        allows_categorical_terms=False,
        allows_polynomial_terms=False,
        model_options_fields=(
            "subject_id", "time", "group", "fit_method", "random_slope",
        ),
        # A plan without these would fit an ordinary regression and call it a
        # repeated-measures model.
        model_options_required_fields=("subject_id", "time", "group"),
        model_options_column_fields=("subject_id", "time", "group"),
        supported_split_kinds=("grouped",),
    ),
    "quantile_regression": ModelFamilyContract(
        family="quantile_regression",
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_model_params_with_options("quantile_regression"),
        expected_artifacts=("quantile_regression_1",),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message=(
            "model.genesis quantile_regression does not accept panel entity_col or time_col"
        ),
        allows_covariance=False,
        allows_categorical_terms=False,
        allows_polynomial_terms=False,
        model_options_fields=("quantiles", "bootstrap_reps", "random_state"),
        validate_model_options=_validate_quantile_model_options,
        validate_branch_frame=_validate_continuous_outcome,
        supported_split_kinds=("iid", "grouped"),
    ),
}

MODEL_FAMILY_SPEC_FIELDS = frozenset(
    field_name
    for contract in MODEL_FAMILY_CONTRACTS.values()
    for field_name in contract.context_spec_fields
)

def model_family_contract(model_family: Any) -> ModelFamilyContract:
    if not isinstance(model_family, str) or model_family not in MODEL_FAMILY_CONTRACTS:
        raise OperationValidationError(
            "model.genesis model_family must be a workflow-executable family: "
            + " or ".join(MODEL_FAMILY_CONTRACTS)
        )
    return MODEL_FAMILY_CONTRACTS[model_family]

def family_context_columns(
    contract: ModelFamilyContract, spec: Mapping[str, Any]
) -> tuple[str, ...]:
    """Project only source-column fields, preserving declared lists elementwise."""

    values: list[str] = []
    for field_name in contract.column_spec_fields:
        value = spec.get(field_name)
        if value is None:
            continue
        if isinstance(value, str) and value:
            values.append(value)
            continue
        if isinstance(value, list) and value and all(
            isinstance(item, str) and item for item in value
        ):
            values.extend(value)
            continue
        raise OperationValidationError(
            f"model.genesis {contract.family} {field_name} must declare source column names"
        )
    options = spec.get("model_options")
    if options is not None:
        if not isinstance(options, Mapping):
            raise OperationValidationError(
                f"model.genesis {contract.family} model_options must be an object"
            )
        for field_name in contract.model_options_column_fields:
            value = options.get(field_name)
            if value is None:
                continue
            if not isinstance(value, str) or not value:
                raise OperationValidationError(
                    f"model.genesis {contract.family} model_options.{field_name} must declare a source column"
                )
            values.append(value)
    return tuple(dict.fromkeys(values))
