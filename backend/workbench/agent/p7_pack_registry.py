"""Declaration-driven registry for the statistical capabilities frozen in P7.

The registry owns capability identity and adapter coverage.  It deliberately
does not know about the workflow executor's dispatch branches; a workflow
step receives one registry entry and the generic runtime invokes that entry.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, TypeAlias

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
Request = Mapping[str, object]
Result = Mapping[str, object]
RequestValidator: TypeAlias = Callable[[Request], Request]
ColumnExtractor: TypeAlias = Callable[[Request], tuple[str, ...]]
Executor: TypeAlias = Callable[[pd.DataFrame | None, Request], Result]
ResultValidator: TypeAlias = Callable[[Result], None]


class P7PackRegistryError(ValueError):
    """Raised when a frozen declaration has an unsafe registry projection."""


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
        ):
            if not callable(getattr(self, field_name)):
                raise P7PackRegistryError(
                    f"P7 operation {self.operation_id!r} has no callable {field_name}"
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
        return self.validate_request(request)


@dataclass(frozen=True)
class P7FamilyDeclaration:
    """A pack-family declaration whose operation values come from its contract."""

    pack_family: str
    operation_ids: frozenset[str]
    input_mode: InputMode
    result_contract: str

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
        "power_analysis", POWER_ANALYSIS_OPERATION_IDS, "typed", POWER_ANALYSIS_CONTRACT
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
                dispatcher_key="workbench.agent.workflow_runtime.p7_pack",
                output_schema_ref=declaration.result_contract,
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
    "P7PackOperation",
    "P7PackRegistry",
    "P7PackRegistryError",
    "P7_FAMILY_DECLARATIONS",
    "declared_p7_operation_ids",
    "p7_workflow_step_contracts",
    "p7_pack_registry",
]
