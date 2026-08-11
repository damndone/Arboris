"""Declaration-driven registry for the statistical capabilities frozen in P7.

The registry owns capability identity and adapter coverage.  It deliberately
does not know about the workflow executor's dispatch branches; a workflow
step receives one registry entry and the generic runtime invokes that entry.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias

import pandas as pd

from workbench.contracts.model.categorical import (
    CATEGORICAL_CONTRACT,
    CATEGORICAL_OPERATION_IDS,
)
from workbench.contracts.model.glm_extensions import (
    GLM_EXTENSION_CONTRACT,
    GLM_EXTENSION_OPERATION_IDS,
)
from workbench.contracts.model.iv_gmm import IV_GMM_CONTRACT, IV_GMM_OPERATION_IDS
from workbench.contracts.model.matching import MATCHING_CONTRACT, MATCHING_OPERATION_IDS
from workbench.contracts.model.meta_analysis import (
    META_ANALYSIS_COMBINE_METHODS,
    META_ANALYSIS_CONTRACT,
    META_ANALYSIS_EFFECT_MEASURES,
    META_ANALYSIS_OPERATION_IDS,
)
from workbench.contracts.model.missing_data import (
    MISSING_DATA_CONTRACT,
    MISSING_DATA_OPERATION_IDS,
)
from workbench.contracts.model.model_diagnostics import (
    MODEL_DIAGNOSTICS_CONTRACT,
    MODEL_DIAGNOSTICS_OPERATION_IDS,
)
from workbench.contracts.model.multiple_comparisons import (
    MULTIPLE_COMPARISONS_CONTRACT,
    MULTIPLE_COMPARISONS_OPERATION_IDS,
)
from workbench.contracts.model.multivariate import (
    MULTIVARIATE_CONTRACT,
    MULTIVARIATE_ALL_OPERATION_IDS,
)
from workbench.contracts.model.nonparametric import (
    NONPARAMETRIC_CONTRACT,
    NONPARAMETRIC_OPERATION_IDS,
)
from workbench.contracts.model.power_analysis import (
    POWER_ANALYSIS_CONTRACT,
    POWER_ANALYSIS_OPERATION_IDS,
)
from workbench.contracts.model.repeated_measures_anova import (
    REPEATED_MEASURES_ANOVA_CONTRACT,
    REPEATED_MEASURES_ANOVA_OPERATION_IDS,
)
from workbench.contracts.model.resampling import (
    RESAMPLING_CONTRACT,
    RESAMPLING_OPERATION_IDS,
)
from workbench.contracts.model.roc_diagnostics import (
    ROC_DIAGNOSTICS_CONTRACT,
    ROC_DIAGNOSTICS_OPERATION_IDS,
)
from workbench.contracts.model.spatial_statistics import (
    SPATIAL_STATISTICS_CONTRACT,
    SPATIAL_STATISTICS_OPERATION_IDS,
)
from workbench.contracts.model.survival_analysis import (
    SURVIVAL_ANALYSIS_CONTRACT,
    SURVIVAL_ANALYSIS_OPERATION_IDS,
)
from workbench.contracts.model.synthetic_control import (
    SYNTHETIC_CONTROL_CONTRACT,
    SYNTHETIC_CONTROL_OPERATION_IDS,
)
from workbench.contracts.model.time_series_pack import (
    TIME_SERIES_PACK_CONTRACT,
    TIME_SERIES_PACK_OPERATION_IDS,
)


OperationId: TypeAlias = str
InputMode: TypeAlias = Literal["frame", "typed"]
P7BindingShape: TypeAlias = Literal["column", "columns", "column_or_columns"]
Request = Mapping[str, object]
Result = Mapping[str, object]
RequestValidator: TypeAlias = Callable[[Request], Request]
ColumnExtractor: TypeAlias = Callable[[Request], tuple[str, ...]]
Executor: TypeAlias = Callable[[pd.DataFrame | None, Request], Result]
ResultValidator: TypeAlias = Callable[[Result], None]
FrameRequestValidator: TypeAlias = Callable[[pd.DataFrame | None, Request], None]


def _no_frame_preflight(
    _frame: pd.DataFrame | None,
    _request: Request,
) -> None:
    """Default for declarations whose safety contract is frame-independent."""


class P7PackRegistryError(ValueError):
    """Raised when a frozen declaration has an unsafe registry projection."""


@dataclass(frozen=True)
class P7RequestSchema:
    """The typed request surface shared by validation and Agent publication.

    P7 adapters receive one common envelope, but each operation owns different
    binding keys and option requirements. Keeping that shape beside the
    registry projection prevents the workflow vocabulary from collapsing every
    pack into ``object`` and forcing an Agent to guess the inner fields.
    """

    required_bindings: tuple[str, ...]
    binding_shapes: Mapping[str, P7BindingShape]
    required_options: tuple[str, ...] = ()
    option_shapes: Mapping[str, str] = field(default_factory=dict)
    option_enums: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        option_shapes = dict(self.option_shapes or {})
        option_enums = dict(self.option_enums or {})
        object.__setattr__(self, "option_shapes", option_shapes)
        object.__setattr__(self, "option_enums", option_enums)
        binding_names = set(self.binding_shapes)
        if not set(self.required_bindings) <= binding_names:
            raise P7PackRegistryError(
                "P7 request required binding(s) are undeclared: "
                + ", ".join(sorted(set(self.required_bindings) - binding_names))
            )
        if len(set(self.required_bindings)) != len(self.required_bindings):
            raise P7PackRegistryError("P7 request required bindings contain duplicates")
        if not set(self.required_options) <= set(option_shapes) | set(option_enums):
            missing = set(self.required_options) - (set(option_shapes) | set(option_enums))
            raise P7PackRegistryError(
                "P7 request required option(s) have no declared shape: "
                + ", ".join(sorted(missing))
            )
        if not set(option_enums) <= set(option_shapes):
            raise P7PackRegistryError(
                "P7 request option enum(s) have no declared shape: "
                + ", ".join(sorted(set(option_enums) - set(option_shapes)))
            )

    @property
    def optional_bindings(self) -> tuple[str, ...]:
        return tuple(name for name in self.binding_shapes if name not in self.required_bindings)

    @staticmethod
    def _value_matches_shape(value: object, shape: str) -> bool:
        if shape == "string":
            return type(value) is str
        if shape == "boolean":
            return type(value) is bool
        if shape == "integer":
            return type(value) is int
        if shape == "number":
            return type(value) in {int, float} and not isinstance(value, bool)
        if shape == "array":
            return isinstance(value, list)
        if shape == "object":
            return isinstance(value, Mapping)
        if shape == "nullable_string":
            return value is None or type(value) is str
        if shape == "any":
            return True
        raise P7PackRegistryError(f"unknown P7 request value shape: {shape}")

    def validate(self, request: Request) -> Request:
        """Validate the declaration-owned envelope fields before adapter code."""

        bindings = request.get("column_bindings")
        if not isinstance(bindings, Mapping):
            raise P7PackRegistryError("P7 pack request column_bindings must be an object")
        unknown_bindings = set(bindings) - set(self.binding_shapes)
        if unknown_bindings:
            raise P7PackRegistryError(
                "P7 pack column_bindings contains unknown field(s): "
                + ", ".join(sorted(unknown_bindings))
            )
        missing_bindings = set(self.required_bindings) - set(bindings)
        if missing_bindings:
            raise P7PackRegistryError(
                "P7 pack column_bindings is missing: "
                + ", ".join(sorted(missing_bindings))
            )
        for name, value in bindings.items():
            shape = self.binding_shapes[name]
            if shape == "column" and type(value) is not str:
                raise P7PackRegistryError(
                    f"P7 pack binding {name} must be one column name"
                )
            if shape == "columns" and (
                not isinstance(value, list)
                or not value
                or any(type(item) is not str or not item for item in value)
            ):
                raise P7PackRegistryError(
                    f"P7 pack binding {name} must be a non-empty column-name list"
                )
            if shape == "column_or_columns" and (
                type(value) is not str
                and not (
                    isinstance(value, list)
                    and value
                    and all(type(item) is str and item for item in value)
                )
            ):
                raise P7PackRegistryError(
                    f"P7 pack binding {name} must be a column name or column-name list"
                )
        options = request.get("options")
        if not isinstance(options, Mapping):
            raise P7PackRegistryError("P7 pack request options must be an object")
        unknown_options = set(options) - set(self.option_shapes)
        if unknown_options:
            raise P7PackRegistryError(
                "P7 pack options contains unknown field(s): "
                + ", ".join(sorted(unknown_options))
            )
        missing_options = set(self.required_options) - set(options)
        if missing_options:
            raise P7PackRegistryError(
                "P7 pack options are missing: " + ", ".join(sorted(missing_options))
            )
        for name, shape in self.option_shapes.items():
            if name in options and options[name] is None and name not in self.required_options:
                continue
            if name in options and not self._value_matches_shape(options[name], shape):
                raise P7PackRegistryError(
                    f"P7 pack option {name} must have shape {shape}"
                )
        for name, values in self.option_enums.items():
            if name in options and options[name] not in values:
                raise P7PackRegistryError(
                    f"P7 pack option {name} must be one of: " + ", ".join(values)
                )
        return request

    @staticmethod
    def _binding_schema(shape: P7BindingShape) -> dict[str, Any]:
        if shape == "column":
            return {"type": "string", "minLength": 1}
        if shape == "columns":
            return {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1,
            }
        return {
            "oneOf": [
                {"type": "string", "minLength": 1},
                {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                },
            ]
        }

    @staticmethod
    def _option_schema(shape: str) -> dict[str, Any]:
        if shape == "nullable_string":
            return {"type": ["string", "null"]}
        if shape == "any":
            return {}
        return {"type": shape}

    def field_schemas(self) -> dict[str, dict[str, Any]]:
        """Return nested schemas for the workflow step's two P7 fields."""

        return {
            "column_bindings": {
                "type": "object",
                "required": list(self.required_bindings),
                "properties": {
                    name: self._binding_schema(shape)
                    for name, shape in self.binding_shapes.items()
                },
                "additionalProperties": False,
            },
            "options": {
                "type": "object",
                "required": list(self.required_options),
                "properties": {
                    name: {
                        **self._option_schema(shape),
                        **(
                            {"nullable": True}
                            if name not in self.required_options
                            and shape != "nullable_string"
                            else {}
                        ),
                        **(
                            {"enum": list(self.option_enums[name])}
                            if name in self.option_enums
                            else {}
                        ),
                    }
                    for name, shape in self.option_shapes.items()
                },
                "additionalProperties": False,
            },
        }


@dataclass(frozen=True)
class P7PackOperation:
    """One typed adapter declaration projected from a P7 contract family."""

    operation_id: OperationId
    pack_family: str
    input_mode: InputMode
    validate_request: RequestValidator
    extract_columns: ColumnExtractor
    execute: Executor
    validate_result: ResultValidator
    validate_frame_request: FrameRequestValidator = _no_frame_preflight
    request_schema: P7RequestSchema = field(
        default_factory=lambda: P7RequestSchema((), {})
    )

    def __post_init__(self) -> None:
        if not isinstance(self.operation_id, str) or not self.operation_id:
            raise P7PackRegistryError("P7 operation_id must be a non-empty string")
        if not isinstance(self.pack_family, str) or not self.pack_family:
            raise P7PackRegistryError("P7 pack family must be a non-empty string")
        if self.input_mode not in {"frame", "typed"}:
            raise P7PackRegistryError(
                f"P7 operation {self.operation_id!r} has an unsupported input mode"
            )
        for field_name in (
            "validate_request",
            "extract_columns",
            "execute",
            "validate_result",
            "validate_frame_request",
        ):
            if not callable(getattr(self, field_name)):
                raise P7PackRegistryError(
                    f"P7 operation {self.operation_id!r} has no callable {field_name}"
                )
        if not isinstance(self.request_schema, P7RequestSchema):
            raise P7PackRegistryError(
                f"P7 operation {self.operation_id!r} has no request schema"
            )

    def validate(self, request: Request) -> Request:
        """Validate the adapter request and its registry-declared input mode."""

        if request.get("operation_id") != self.operation_id:
            raise P7PackRegistryError(
                f"P7 registry entry {self.operation_id!r} cannot validate "
                f"request operation_id={request.get('operation_id')!r}"
            )
        if request.get("input_mode") != self.input_mode:
            raise P7PackRegistryError(
                f"P7 operation {self.operation_id!r} requires input_mode={self.input_mode!r}"
            )
        # Let the adapter's recursive safety checks run first. In particular,
        # a forbidden executable field must remain the reported error even if
        # another required policy option is absent.
        validated = self.validate_request(request)
        self.request_schema.validate(validated)
        return validated

    def preflight(self, frame: pd.DataFrame | None, request: Request) -> Request:
        """Validate request semantics that depend on the resolved source frame."""

        validated = self.validate(request)
        self.validate_frame_request(frame, validated)
        return validated


@dataclass(frozen=True)
class P7FamilyDeclaration:
    """A pack-family declaration whose operation values come from its contract."""

    pack_family: str
    operation_ids: frozenset[str]
    input_mode: InputMode
    result_contract: str
    consumes_input_frame: bool = True

    def __post_init__(self) -> None:
        if not self.pack_family or not self.operation_ids or not self.result_contract:
            raise P7PackRegistryError("P7 family declarations must not be empty")
        if any(not isinstance(value, str) or not value for value in self.operation_ids):
            raise P7PackRegistryError(
                f"P7 family {self.pack_family!r} contains an invalid operation_id"
            )


# This tuple names contract modules, not a second operation inventory.  The
# operation values are imported from each module's declaration above and the
# union below is recomputed whenever the projection is requested.
P7_FAMILY_DECLARATIONS: tuple[P7FamilyDeclaration, ...] = (
    P7FamilyDeclaration(
        "categorical", CATEGORICAL_OPERATION_IDS, "typed", CATEGORICAL_CONTRACT
    ),
    P7FamilyDeclaration(
        "glm_extensions",
        frozenset(GLM_EXTENSION_OPERATION_IDS),
        "frame",
        GLM_EXTENSION_CONTRACT,
    ),
    P7FamilyDeclaration("iv_gmm", IV_GMM_OPERATION_IDS, "typed", IV_GMM_CONTRACT),
    P7FamilyDeclaration("matching", MATCHING_OPERATION_IDS, "frame", MATCHING_CONTRACT),
    P7FamilyDeclaration(
        "meta_analysis", META_ANALYSIS_OPERATION_IDS, "typed", META_ANALYSIS_CONTRACT
    ),
    P7FamilyDeclaration(
        "missing_data", MISSING_DATA_OPERATION_IDS, "frame", MISSING_DATA_CONTRACT
    ),
    P7FamilyDeclaration(
        "model_diagnostics",
        MODEL_DIAGNOSTICS_OPERATION_IDS,
        "typed",
        MODEL_DIAGNOSTICS_CONTRACT,
    ),
    P7FamilyDeclaration(
        "multiple_comparisons",
        MULTIPLE_COMPARISONS_OPERATION_IDS,
        "typed",
        MULTIPLE_COMPARISONS_CONTRACT,
    ),
    P7FamilyDeclaration(
        "multivariate", MULTIVARIATE_ALL_OPERATION_IDS, "frame", MULTIVARIATE_CONTRACT
    ),
    P7FamilyDeclaration(
        "nonparametric", NONPARAMETRIC_OPERATION_IDS, "typed", NONPARAMETRIC_CONTRACT
    ),
    P7FamilyDeclaration(
        "power_analysis",
        POWER_ANALYSIS_OPERATION_IDS,
        "typed",
        POWER_ANALYSIS_CONTRACT,
        False,
    ),
    P7FamilyDeclaration(
        "repeated_measures_anova",
        REPEATED_MEASURES_ANOVA_OPERATION_IDS,
        "frame",
        REPEATED_MEASURES_ANOVA_CONTRACT,
    ),
    P7FamilyDeclaration(
        "resampling", RESAMPLING_OPERATION_IDS, "typed", RESAMPLING_CONTRACT
    ),
    P7FamilyDeclaration(
        "roc_diagnostics", ROC_DIAGNOSTICS_OPERATION_IDS, "frame", ROC_DIAGNOSTICS_CONTRACT
    ),
    P7FamilyDeclaration(
        "spatial_statistics",
        SPATIAL_STATISTICS_OPERATION_IDS,
        "typed",
        SPATIAL_STATISTICS_CONTRACT,
    ),
    P7FamilyDeclaration(
        "survival_analysis",
        SURVIVAL_ANALYSIS_OPERATION_IDS,
        "frame",
        SURVIVAL_ANALYSIS_CONTRACT,
    ),
    P7FamilyDeclaration(
        "synthetic_control",
        SYNTHETIC_CONTROL_OPERATION_IDS,
        "typed",
        SYNTHETIC_CONTROL_CONTRACT,
    ),
    P7FamilyDeclaration(
        "time_series", TIME_SERIES_PACK_OPERATION_IDS, "frame", TIME_SERIES_PACK_CONTRACT
    ),
)


def declared_p7_operation_ids(
    declarations: Sequence[P7FamilyDeclaration] = P7_FAMILY_DECLARATIONS,
) -> frozenset[str]:
    """Derive the complete P7 denominator from live family declarations."""

    operation_ids: set[str] = set()
    for declaration in declarations:
        duplicate = operation_ids.intersection(declaration.operation_ids)
        if duplicate:
            raise P7PackRegistryError(
                "duplicate P7 operation declaration(s): "
                + ", ".join(sorted(duplicate))
            )
        operation_ids.update(declaration.operation_ids)
    return frozenset(operation_ids)


def _request_schema(
    required_bindings: tuple[str, ...] = (),
    *,
    optional_bindings: tuple[str, ...] = (),
    binding_shapes: Mapping[str, P7BindingShape] | None = None,
    required_options: tuple[str, ...] = (),
    option_shapes: Mapping[str, str] | None = None,
    option_enums: Mapping[str, tuple[str, ...]] | None = None,
) -> P7RequestSchema:
    shapes = dict(binding_shapes or {})
    for name in (*required_bindings, *optional_bindings):
        shapes.setdefault(name, "column")
    options = dict(option_shapes or {})
    for name in required_options:
        options.setdefault(name, "any")
    return P7RequestSchema(
        required_bindings=required_bindings,
        binding_shapes=shapes,
        required_options=required_options,
        option_shapes=options,
        option_enums=dict(option_enums or {}),
    )


P7_REQUEST_SCHEMAS: dict[str, P7RequestSchema] = {}


def _register_request_schema(
    operation_ids: Iterable[str],
    schema: P7RequestSchema,
) -> None:
    for operation_id in operation_ids:
        if operation_id in P7_REQUEST_SCHEMAS:
            raise P7PackRegistryError(
                f"duplicate P7 request schema declaration: {operation_id}"
            )
        P7_REQUEST_SCHEMAS[operation_id] = schema


_register_request_schema(
    ("categorical.cramers_v",),
    _request_schema(
        ("row", "column"),
        required_options=("correction",),
        option_shapes={"correction": "boolean"},
    ),
)
_register_request_schema(
    ("categorical.mcnemar",),
    _request_schema(
        ("row", "column"),
        required_options=("exact", "correction"),
        option_shapes={"exact": "boolean", "correction": "boolean"},
    ),
)
_register_request_schema(
    GLM_EXTENSION_OPERATION_IDS,
    _request_schema(
        ("outcome", "predictors"),
        binding_shapes={"outcome": "column", "predictors": "columns"},
        option_shapes={"maxiter": "integer"},
    ),
)
_register_request_schema(
    ("iv.gmm",),
    _request_schema(
        ("outcome", "exog", "endog", "instruments"),
        binding_shapes={
            "outcome": "column",
            "exog": "columns",
            "endog": "columns",
            "instruments": "columns",
        },
        option_shapes={
            "estimator": "string",
            "covariance_method": "string",
            "center_moments": "boolean",
            "confidence_level": "number",
        },
    ),
)
_register_request_schema(
    ("iv.weak_instruments",),
    _request_schema(
        ("outcome", "exog", "endog", "instruments"),
        binding_shapes={
            "outcome": "column",
            "exog": "columns",
            "endog": "columns",
            "instruments": "columns",
        },
    ),
)
_register_request_schema(
    ("matching.att",),
    _request_schema(
        ("treatment", "outcome", "id", "covariates"),
        binding_shapes={
            "treatment": "column",
            "outcome": "column",
            "id": "column",
            "covariates": "columns",
        },
        required_options=(
            "propensity_policy",
            "distance_policy",
            "ratio",
            "caliper",
            "replacement",
            "tie_policy",
            "common_support_policy",
            "unmatched_policy",
            "balance_threshold",
            "missing_policy",
        ),
        option_shapes={
            "propensity_policy": "object",
            "distance_policy": "string",
            "ratio": "integer",
            "caliper": "number",
            "replacement": "boolean",
            "tie_policy": "string",
            "common_support_policy": "string",
            "unmatched_policy": "string",
            "balance_threshold": "number",
            "missing_policy": "string",
        },
        option_enums={"missing_policy": ("reject",)},
    ),
)
_register_request_schema(
    ("matching.balance",),
    _request_schema(
        ("treatment", "id", "covariates"),
        binding_shapes={
            "treatment": "column",
            "id": "column",
            "covariates": "columns",
        },
        required_options=("balance_threshold", "missing_policy"),
        option_shapes={
            "balance_threshold": "number",
            "missing_policy": "string",
            "matched_pairs": "array",
        },
        option_enums={"missing_policy": ("reject",)},
    ),
)
_register_request_schema(
    ("meta.combine",),
    _request_schema(
        ("study_id", "effect", "variance"),
        required_options=("effect_measure", "method"),
        option_shapes={
            "effect_measure": "string",
            "method": "string",
            "alpha": "number",
            "ci_method": "string",
            "use_t": "boolean",
            "leave_one_out": "boolean",
            "max_leave_one_out": "integer",
            "continuity_correction": "number",
            "zero_correction": "number",
        },
        option_enums={
            "effect_measure": tuple(sorted(META_ANALYSIS_EFFECT_MEASURES)),
            "method": tuple(sorted(META_ANALYSIS_COMBINE_METHODS)),
        },
    ),
)
_register_request_schema(
    ("meta.effect_size",),
    _request_schema(
        ("study_id", "effect", "variance"),
        required_options=("effect_measure",),
        option_shapes={
            "effect_measure": "string",
            "alpha": "number",
            "continuity_correction": "number",
            "zero_correction": "number",
        },
        option_enums={
            "effect_measure": tuple(sorted(META_ANALYSIS_EFFECT_MEASURES)),
        },
    ),
)
_register_request_schema(
    ("missingness.profile",),
    _request_schema(),
)
_register_request_schema(
    ("missing_data.rubin_pool",),
    _request_schema(
        required_options=("model_results",),
        option_shapes={
            "model_results": "array",
            "alpha": "number",
            "null_value": "number",
            "complete_data_degrees_of_freedom": "number",
        },
    ),
)
_register_request_schema(
    ("diagnostics.vif",),
    _request_schema(
        ("design",),
        binding_shapes={"design": "columns"},
        option_shapes={
            "intercept": "boolean",
            "intercept_column": "nullable_string",
            "model_metadata": "object",
            "max_output_rows": "integer",
        },
    ),
)
_register_request_schema(
    ("diagnostics.breusch_pagan", "diagnostics.white"),
    _request_schema(
        ("response", "design"),
        binding_shapes={"response": "column", "design": "columns"},
        option_shapes={
            "intercept": "boolean",
            "intercept_column": "nullable_string",
            "model_metadata": "object",
        },
    ),
)
_register_request_schema(
    ("diagnostics.breusch_godfrey",),
    _request_schema(
        ("response", "design"),
        binding_shapes={"response": "column", "design": "columns"},
        required_options=("lag", "time_order"),
        option_shapes={
            "intercept": "boolean",
            "intercept_column": "nullable_string",
            "model_metadata": "object",
            "lag": "integer",
            "time_order": "string",
        },
    ),
)
_register_request_schema(
    ("diagnostics.reset",),
    _request_schema(
        ("response", "design"),
        binding_shapes={"response": "column", "design": "columns"},
        required_options=("reset_powers",),
        option_shapes={
            "intercept": "boolean",
            "intercept_column": "nullable_string",
            "model_metadata": "object",
            "reset_powers": "array",
        },
    ),
)
_register_request_schema(
    ("diagnostics.influence",),
    _request_schema(
        ("response", "design"),
        binding_shapes={"response": "column", "design": "columns"},
        option_shapes={
            "intercept": "boolean",
            "intercept_column": "nullable_string",
            "model_metadata": "object",
            "max_output_rows": "integer",
        },
    ),
)
_register_request_schema(
    MULTIPLE_COMPARISONS_OPERATION_IDS,
    _request_schema(
        ("group", "value"),
        option_shapes={"alpha": "number"},
    ),
)
_register_request_schema(
    ("multivariate.pca",),
    _request_schema(
        ("columns",),
        binding_shapes={"columns": "columns"},
        option_shapes={
            "matrix": "string",
            "component_selection": "string",
            "n_components": "integer",
            "variance_threshold": "number",
            "include_scores": "boolean",
            "max_score_rows": "integer",
            "missing_policy": "string",
        },
    ),
)
_register_request_schema(
    ("multivariate.efa",),
    _request_schema(
        ("columns",),
        binding_shapes={"columns": "columns"},
        required_options=(
            "n_factors",
            "extraction",
            "rotation",
            "kmo_threshold",
            "bartlett_alpha",
        ),
        option_shapes={
            "n_factors": "integer",
            "extraction": "string",
            "rotation": "string",
            "kmo_threshold": "number",
            "bartlett_alpha": "number",
            "missing_policy": "string",
        },
    ),
)
_register_request_schema(
    ("multivariate.cronbach_alpha",),
    _request_schema(
        ("columns",),
        binding_shapes={"columns": "columns"},
        option_shapes={
            "reverse_scored": "array",
            "reverse_bounds": "object",
            "missing_policy": "string",
        },
    ),
)
_register_request_schema(
    ("multivariate.clustering",),
    _request_schema(
        ("columns",),
        binding_shapes={"columns": "columns"},
        required_options=("algorithm", "standardization", "selection"),
        option_shapes={
            "algorithm": "string",
            "standardization": "string",
            "selection": "string",
            "n_clusters": "integer",
            "candidate_ks": "array",
            "random_state": "integer",
            "linkage": "string",
            "metric": "string",
            "max_iter": "integer",
            "tol": "number",
            "include_assignments": "boolean",
            "max_assignment_rows": "integer",
            "missing_policy": "string",
        },
    ),
)
_register_request_schema(
    ("multivariate.mca",),
    _request_schema(
        ("columns",),
        binding_shapes={"columns": "columns"},
        option_shapes={
            "n_dimensions": "integer",
            "missing_policy": "string",
        },
    ),
)
_register_request_schema(
    ("multivariate.discriminant",),
    _request_schema(
        ("features", "target"),
        binding_shapes={"features": "columns", "target": "column"},
        required_options=("method", "prior_policy", "regularization", "evaluation"),
        option_shapes={
            "method": "string",
            "prior_policy": "string",
            "regularization": "number",
            "evaluation": "string",
            "priors": "object",
            "test_size": "number",
            "random_state": "integer",
            "include_predictions": "boolean",
            "max_prediction_rows": "integer",
            "missing_policy": "string",
        },
    ),
)
_register_request_schema(
    ("multivariate.correspondence",),
    _request_schema(
        ("row", "column"),
        option_shapes={"n_dimensions": "integer"},
    ),
)
_register_request_schema(
    ("multivariate.manova",),
    _request_schema(
        ("responses", "factors"),
        optional_bindings=("covariates",),
        binding_shapes={
            "responses": "columns",
            "factors": "columns",
            "covariates": "columns",
        },
        required_options=("interaction_terms", "intercept", "missing_policy"),
        option_shapes={
            "interaction_terms": "array",
            "intercept": "boolean",
            "missing_policy": "string",
            "max_retained_positions": "integer",
        },
    ),
)
_register_request_schema(
    ("nonparametric.mann_whitney",),
    _request_schema(
        ("x", "y"),
        option_shapes={
            "alternative": "string",
            "method": "string",
            "missing_policy": "string",
            "n_resamples": "integer",
            "seed": "integer",
            "alpha": "number",
        },
    ),
)
_register_request_schema(
    ("nonparametric.wilcoxon_signed_rank",),
    _request_schema(
        ("x", "y"),
        option_shapes={
            "alternative": "string",
            "method": "string",
            "zero_method": "string",
            "missing_policy": "string",
            "alpha": "number",
        },
    ),
)
_register_request_schema(
    ("nonparametric.spearman",),
    _request_schema(
        ("x", "y"),
        option_shapes={"missing_policy": "string", "alpha": "number"},
    ),
)
_register_request_schema(
    ("nonparametric.kendall",),
    _request_schema(
        ("x", "y"),
        option_shapes={
            "variant": "string",
            "missing_policy": "string",
            "alpha": "number",
        },
    ),
)
_register_request_schema(
    ("nonparametric.kruskal_wallis",),
    _request_schema(
        ("group", "value"),
        option_shapes={
            "method": "string",
            "missing_policy": "string",
            "alpha": "number",
        },
    ),
)
_register_request_schema(
    ("nonparametric.friedman",),
    _request_schema(
        ("columns",),
        binding_shapes={"columns": "columns"},
        option_shapes={"method": "string", "alpha": "number"},
    ),
)
_register_request_schema(
    ("nonparametric.robust_summary",),
    _request_schema(
        ("values",),
        option_shapes={
            "trim_fraction": "number",
            "winsor_fraction": "number",
            "missing_policy": "string",
            "alpha": "number",
        },
    ),
)
_register_request_schema(
    ("power_analysis.solve",),
    _request_schema(
        required_options=("design", "solve_for"),
        option_shapes={"design": "string", "solve_for": "string"},
        option_enums={
            "design": ("independent_t", "one_way_anova", "two_proportion_z"),
            "solve_for": ("power", "sample_size", "effect_size", "alpha"),
        },
    ),
)
_register_request_schema(
    ("power_analysis.sensitivity_grid",),
    _request_schema(
        required_options=("design", "solve_for", "axes"),
        option_shapes={"design": "string", "solve_for": "string", "axes": "object"},
        option_enums={
            "design": ("independent_t", "one_way_anova", "two_proportion_z"),
            "solve_for": ("power", "sample_size", "effect_size", "alpha"),
        },
    ),
)
_register_request_schema(
    REPEATED_MEASURES_ANOVA_OPERATION_IDS,
    _request_schema(
        ("response", "subject", "within"),
        optional_bindings=("between",),
        binding_shapes={
            "response": "column",
            "subject": "column",
            "within": "column_or_columns",
            "between": "column",
        },
        option_shapes={"correction": "string"},
    ),
)
_register_request_schema(
    ("resampling.bootstrap",),
    _request_schema(
        ("values",),
        required_options=("statistic_id", "n_resamples", "seed", "confidence_level", "interval_method"),
        option_shapes={
            "statistic_id": "string",
            "n_resamples": "integer",
            "seed": "integer",
            "confidence_level": "number",
            "interval_method": "string",
        },
    ),
)
_register_request_schema(
    ("resampling.permutation",),
    _request_schema(
        ("left", "right"),
        required_options=("statistic_id", "n_resamples", "seed", "alternative"),
        option_shapes={
            "statistic_id": "string",
            "n_resamples": "integer",
            "seed": "integer",
            "alternative": "string",
        },
    ),
)
_register_request_schema(
    ("roc.curve",),
    _request_schema(
        ("truth", "scores"),
        required_options=("positive_label",),
        option_shapes={
            "positive_label": "any",
            "score_semantics": "string",
            "threshold_policy": "string",
            "quantile_grid_size": "integer",
            "max_thresholds": "integer",
            "missing_policy": "string",
            "constraint_policy": "object",
            "cost_policy": "object",
        },
    ),
)
_register_request_schema(
    ("roc.calibration",),
    _request_schema(
        ("truth", "scores"),
        required_options=("positive_label", "score_semantics", "calibration_method", "n_bins"),
        option_shapes={
            "positive_label": "any",
            "score_semantics": "string",
            "calibration_method": "string",
            "n_bins": "integer",
            "max_bins": "integer",
            "missing_policy": "string",
        },
    ),
)
_register_request_schema(
    SPATIAL_STATISTICS_OPERATION_IDS,
    _request_schema(
        ("values", "weights"),
        binding_shapes={"values": "column", "weights": "columns"},
        required_options=("weight_policy", "permutation_policy"),
        option_shapes={"weight_policy": "object", "permutation_policy": "object"},
    ),
)
_register_request_schema(
    ("survival.kaplan_meier",),
    _request_schema(
        ("duration", "event"),
        optional_bindings=("entry", "group"),
        binding_shapes={
            "duration": "column",
            "event": "column",
            "entry": "column",
            "group": "column",
        },
        option_shapes={
            "ci_method": "string",
            "confidence_level": "number",
            "tau": "number",
        },
    ),
)
_register_request_schema(
    ("survival.log_rank",),
    _request_schema(
        ("duration", "event"),
        optional_bindings=("entry", "group"),
        binding_shapes={
            "duration": "column",
            "event": "column",
            "entry": "column",
            "group": "column",
        },
        option_shapes={"tie_policy": "string"},
    ),
)
_register_request_schema(
    ("survival.rmst",),
    _request_schema(
        ("duration", "event"),
        optional_bindings=("entry", "group"),
        binding_shapes={
            "duration": "column",
            "event": "column",
            "entry": "column",
            "group": "column",
        },
        option_shapes={
            "ci_method": "string",
            "confidence_level": "number",
            "tau": "number",
        },
    ),
)
_register_request_schema(
    ("synthetic_control.fit",),
    _request_schema(
        ("outcomes",),
        binding_shapes={"outcomes": "columns"},
        required_options=("treated_unit", "donor_pool", "periods", "pre_periods", "post_periods"),
        option_shapes={
            "treated_unit": "string",
            "donor_pool": "array",
            "periods": "array",
            "pre_periods": "array",
            "post_periods": "array",
            "solver_policy": "object",
            "tolerance_policy": "object",
        },
    ),
)
_register_request_schema(
    ("synthetic_control.placebo",),
    _request_schema(
        ("outcomes",),
        binding_shapes={"outcomes": "columns"},
        required_options=(
            "treated_unit",
            "donor_pool",
            "periods",
            "pre_periods",
            "post_periods",
            "placebo_policy",
        ),
        option_shapes={
            "treated_unit": "string",
            "donor_pool": "array",
            "periods": "array",
            "pre_periods": "array",
            "post_periods": "array",
            "placebo_policy": "object",
            "solver_policy": "object",
            "tolerance_policy": "object",
        },
    ),
)
_register_request_schema(
    ("time_series.acf",),
    _request_schema(
        ("time", "value"),
        binding_shapes={"time": "column", "value": "column"},
        required_options=("time_order", "nlags"),
        option_shapes={
            "time_order": "string",
            "nlags": "integer",
            "confidence_level": "number",
            "adjusted": "boolean",
        },
    ),
)
_register_request_schema(
    ("time_series.pacf",),
    _request_schema(
        ("time", "value"),
        binding_shapes={"time": "column", "value": "column"},
        required_options=("time_order", "nlags"),
        option_shapes={
            "time_order": "string",
            "nlags": "integer",
            "confidence_level": "number",
            "method": "string",
        },
    ),
)
_register_request_schema(
    ("time_series.adf",),
    _request_schema(
        ("time", "value"),
        binding_shapes={"time": "column", "value": "column"},
        required_options=("time_order",),
        option_shapes={
            "time_order": "string",
            "regression": "string",
            "autolag": "string",
            "max_lag": "integer",
        },
    ),
)
_register_request_schema(
    ("time_series.kpss",),
    _request_schema(
        ("time", "value"),
        binding_shapes={"time": "column", "value": "column"},
        required_options=("time_order",),
        option_shapes={
            "time_order": "string",
            "regression": "string",
            "nlags": "any",
        },
    ),
)
_register_request_schema(
    ("time_series.arima",),
    _request_schema(
        ("time", "value"),
        binding_shapes={"time": "column", "value": "column"},
        required_options=("time_order", "order"),
        option_shapes={
            "time_order": "string",
            "order": "array",
            "seasonal_order": "array",
            "trend": "string",
            "forecast_horizon": "integer",
            "confidence_level": "number",
        },
    ),
)
_register_request_schema(
    ("time_series.var",),
    _request_schema(
        ("time", "values"),
        binding_shapes={"time": "column", "values": "columns"},
        required_options=("time_order", "lags"),
        option_shapes={
            "time_order": "string",
            "lags": "integer",
            "trend": "string",
            "forecast_horizon": "integer",
            "confidence_level": "number",
            "stability_policy": "string",
        },
    ),
)
_register_request_schema(
    ("time_series.irf",),
    _request_schema(
        ("time", "values"),
        binding_shapes={"time": "column", "values": "columns"},
        required_options=("time_order", "lags"),
        option_shapes={
            "time_order": "string",
            "lags": "integer",
            "trend": "string",
            "horizon": "integer",
            "orthogonalized": "boolean",
            "confidence_level": "number",
            "ci_method": "string",
            "stability_policy": "string",
        },
    ),
)
_register_request_schema(
    ("time_series.cointegration",),
    _request_schema(
        ("time", "values"),
        binding_shapes={"time": "column", "values": "columns"},
        required_options=("time_order", "method"),
        option_shapes={
            "time_order": "string",
            "method": "string",
            "confidence_level": "number",
            "max_lag": "integer",
            "trend": "string",
            "det_order": "integer",
            "k_ar_diff": "integer",
        },
    ),
)
_register_request_schema(
    ("time_series.vecm",),
    _request_schema(
        ("time", "values"),
        binding_shapes={"time": "column", "values": "columns"},
        required_options=("time_order", "deterministic"),
        option_shapes={
            "time_order": "string",
            "det_order": "integer",
            "k_ar_diff": "integer",
            "deterministic": "string",
            "forecast_horizon": "integer",
            "confidence_level": "number",
        },
    ),
)
_register_request_schema(
    ("time_series.granger",),
    _request_schema(
        ("time", "cause", "effect"),
        required_options=("time_order", "max_lag"),
        option_shapes={"time_order": "string", "max_lag": "integer", "test": "string"},
    ),
)


if set(P7_REQUEST_SCHEMAS) != set(declared_p7_operation_ids()):
    missing = set(declared_p7_operation_ids()) - set(P7_REQUEST_SCHEMAS)
    extra = set(P7_REQUEST_SCHEMAS) - set(declared_p7_operation_ids())
    detail = []
    if missing:
        detail.append("missing request schemas: " + ", ".join(sorted(missing)))
    if extra:
        detail.append("undeclared request schemas: " + ", ".join(sorted(extra)))
    raise P7PackRegistryError("; ".join(detail))


def p7_request_schema(operation_id: str) -> P7RequestSchema:
    try:
        return P7_REQUEST_SCHEMAS[operation_id]
    except KeyError as exc:
        raise P7PackRegistryError(
            f"P7 operation has no request schema: {operation_id!r}"
        ) from exc


class P7PackRegistry:
    """Immutable lookup table with exact declaration-to-adapter coverage."""

    def __init__(self, operations: Iterable[P7PackOperation]) -> None:
        by_id: dict[str, P7PackOperation] = {}
        for operation in operations:
            if operation.operation_id in by_id:
                raise P7PackRegistryError(
                    f"duplicate P7 adapter declaration: {operation.operation_id}"
                )
            by_id[operation.operation_id] = operation
        if not by_id:
            raise P7PackRegistryError("P7 adapter registry must not be empty")
        self._by_id = by_id

    def operation_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_id))

    def get(self, operation_id: str) -> P7PackOperation:
        try:
            return self._by_id[operation_id]
        except KeyError as exc:
            raise P7PackRegistryError(
                f"P7 operation is not registered: {operation_id!r}"
            ) from exc

    def assert_covers(self, declarations: Sequence[P7FamilyDeclaration]) -> None:
        declared = declared_p7_operation_ids(declarations)
        registered = frozenset(self._by_id)
        missing = declared - registered
        extra = registered - declared
        if missing or extra:
            details: list[str] = []
            if missing:
                details.append("missing adapters: " + ", ".join(sorted(missing)))
            if extra:
                details.append("undeclared adapters: " + ", ".join(sorted(extra)))
            raise P7PackRegistryError("; ".join(details))


def _build_initial_operations() -> tuple[P7PackOperation, ...]:
    from .p7_pack_adapters import p7_family_adapter

    operations: list[P7PackOperation] = []
    for declaration in P7_FAMILY_DECLARATIONS:
        adapter = p7_family_adapter(declaration.pack_family)
        operations.extend(
            P7PackOperation(
                operation_id=operation_id,
                pack_family=declaration.pack_family,
                input_mode=declaration.input_mode,
                validate_request=adapter.validate_request,
                extract_columns=adapter.extract_columns,
                execute=adapter.execute,
                validate_result=adapter.validate_result,
                validate_frame_request=adapter.validate_frame_request,
                request_schema=p7_request_schema(operation_id),
            )
            for operation_id in declaration.operation_ids
        )
    return tuple(operations)


p7_pack_registry = P7PackRegistry(_build_initial_operations())
p7_pack_registry.assert_covers(P7_FAMILY_DECLARATIONS)


def p7_workflow_step_contracts() -> dict[str, object]:
    """Project every registered adapter into the P3 workflow-step seam."""

    from .workflow_contracts import pack_step_contract

    contracts: dict[str, object] = {}
    for declaration in P7_FAMILY_DECLARATIONS:
        for operation_id in declaration.operation_ids:
            operation = p7_pack_registry.get(operation_id)
            contracts[operation_id] = pack_step_contract(
                summary=(
                    f"Run the frozen {declaration.pack_family} statistical operation "
                    "through its typed, bounded adapter."
                ),
                fields={
                    "input_mode": (
                        "Registry-declared adapter input mode; it is not inferred from the data."
                    ),
                    "column_bindings": (
                        "Server-resolved source column bindings declared by this operation."
                    ),
                    "options": (
                        "Operation policy and estimator options validated by the frozen pack contract."
                    ),
                },
                required=("input_mode", "column_bindings", "options"),
                field_types={
                    "input_mode": "string",
                    "column_bindings": "object",
                    "options": "object",
                },
                field_enums={"input_mode": (operation.input_mode,)},
                field_schemas=operation.request_schema.field_schemas(),
                dispatcher_key="workbench.agent.workflow_runtime.p7_pack",
                output_schema_ref=declaration.result_contract,
                consumes_input_frame=declaration.consumes_input_frame,
                accepted_dataset_kinds=("derived_data", "prepared_data"),
                top_level_exposure_note=(
                    f"Composable {declaration.pack_family} step; it is not a standalone "
                    "natural-language proposal until a separate top-level declaration exists."
                ),
            )
            # The registry entry is intentionally touched here so a declaration
            # cannot create a workflow contract without a concrete adapter.
            if operation.pack_family != declaration.pack_family:
                raise P7PackRegistryError(
                    f"P7 operation {operation_id!r} is assigned to the wrong family"
                )
    return contracts


__all__ = [
    "P7FamilyDeclaration",
    "P7RequestSchema",
    "P7PackOperation",
    "P7PackRegistry",
    "P7PackRegistryError",
    "P7_FAMILY_DECLARATIONS",
    "declared_p7_operation_ids",
    "p7_request_schema",
    "P7_REQUEST_SCHEMAS",
    "p7_workflow_step_contracts",
    "p7_pack_registry",
]
