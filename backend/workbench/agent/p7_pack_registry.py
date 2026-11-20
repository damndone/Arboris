"""Declaration-driven registry for the statistical capabilities frozen in P7.

The registry owns capability identity and adapter coverage.  It deliberately
does not know about the workflow executor's dispatch branches; a workflow
step receives one registry entry and the generic runtime invokes that entry.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal, TypeAlias

import pandas as pd

from workbench.agent.p7_option_vocabularies import OPTION_VOCABULARIES
from workbench.agent.p7_request_declarations import declare_request_schemas

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
from workbench.contracts.treatment_effects import TREATMENT_EFFECTS_CONTRACT, TREATMENT_EFFECTS_OPERATION_IDS
from workbench.contracts.model.meta_analysis import (
    META_ANALYSIS_CONTRACT,
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
                        # Leaving an optional field out means the kernel's
                        # default. A closed-vocabulary option is not
                        # nullable: null is not one of its values.
                        **(
                            {"nullable": True}
                            if name not in self.required_options
                            and shape != "nullable_string"
                            and name not in self.option_enums
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
    P7FamilyDeclaration("treatment_effects", TREATMENT_EFFECTS_OPERATION_IDS, "frame", TREATMENT_EFFECTS_CONTRACT),
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
        # The allowed values of closed-vocabulary options come from one table
        # (p7_option_vocabularies), itself built from the contracts' sets.
        vocabulary = OPTION_VOCABULARIES.get(operation_id, {})
        undeclared = set(vocabulary) - set(schema.option_shapes)
        if undeclared:
            raise P7PackRegistryError(
                f"{operation_id}: vocabulary for undeclared option(s): " + ", ".join(sorted(undeclared))
            )
        P7_REQUEST_SCHEMAS[operation_id] = replace(schema, option_enums={**schema.option_enums, **vocabulary})


declare_request_schemas(_register_request_schema, _request_schema)

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

    from .workflow_contract_parts.contracts import pack_step_contract

    contracts: dict[str, object] = {}
    for declaration in P7_FAMILY_DECLARATIONS:
        # operation_ids is a frozenset: its order follows the per-process string
        # hash, which reordered the Agent's protocol text in every new process.
        for operation_id in sorted(declaration.operation_ids):
            operation = p7_pack_registry.get(operation_id)
            contracts[operation_id] = pack_step_contract(
                # The index line carries the fields; this summary only names the family.
                summary=f"{declaration.pack_family.replace('_', ' ').capitalize()} method (typed adapter).",
                fields={
                    "input_mode": (
                        "Registry-declared adapter input mode; it is not inferred from the data."
                    ),
                    "column_bindings": (
                        "Which columns of the dataset play which role."
                    ),
                    "options": (
                        "Settings for this method; each is checked against the method's contract."
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
