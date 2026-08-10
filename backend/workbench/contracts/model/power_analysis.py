"""Versioned JSON-safe contracts for the standalone power-analysis pack."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import product
import math
from types import MappingProxyType
from typing import Any

from workbench.canonical import sha256_canonical
from workbench.contracts.common.envelope import (
    ContractError,
    freeze_json,
    require_exact_keys,
    thaw_json,
)


POWER_ANALYSIS_CONTRACT = "power_analysis.result"
POWER_ANALYSIS_CONTRACT_VERSION = "1.0"
POWER_ANALYSIS_DESIGNS = frozenset(
    {"independent_t", "one_way_anova", "two_proportion_z"}
)
POWER_ANALYSIS_SOLVE_TARGETS = frozenset(
    {"alpha", "power", "sample_size", "effect_size"}
)
# These are the two typed workflow entry points exposed by the frozen pack.
# Design and solve-target coverage remains an explicit contract dimension;
# callers must not manufacture operation IDs from those values.
POWER_ANALYSIS_OPERATION_IDS = frozenset(
    {"power_analysis.solve", "power_analysis.sensitivity_grid"}
)
POWER_ANALYSIS_EFFECT_SIZE_TYPES = frozenset(
    {"cohens_d", "cohens_f", "cohens_h"}
)
POWER_ANALYSIS_ALTERNATIVES = frozenset({"two-sided", "larger", "smaller"})
POWER_ANALYSIS_DESIGN_EFFECT_SIZE_TYPES = MappingProxyType(
    {
        "independent_t": "cohens_d",
        "one_way_anova": "cohens_f",
        "two_proportion_z": "cohens_h",
    }
)
POWER_ANALYSIS_SAMPLE_SIZE_SEMANTICS = frozenset(
    {"nobs1_per_group", "total_nobs"}
)
POWER_ANALYSIS_ROUNDING_POLICIES = frozenset({"none"})
POWER_ANALYSIS_STATUS_COMPLETED = "completed"
POWER_ANALYSIS_STATUS_REJECTED = "rejected"
POWER_ANALYSIS_STATUS_FAILED = "failed"
POWER_ANALYSIS_STATUSES = frozenset(
    {
        POWER_ANALYSIS_STATUS_COMPLETED,
        POWER_ANALYSIS_STATUS_REJECTED,
        POWER_ANALYSIS_STATUS_FAILED,
    }
)
POWER_ANALYSIS_COMPLETED = "POWER_ANALYSIS_COMPLETED"
POWER_ANALYSIS_REJECTED = "POWER_ANALYSIS_REJECTED"
POWER_ANALYSIS_FAILED = "POWER_ANALYSIS_FAILED"
POWER_ANALYSIS_REASON_CODES = frozenset(
    {POWER_ANALYSIS_COMPLETED, POWER_ANALYSIS_REJECTED, POWER_ANALYSIS_FAILED}
)
POWER_ANALYSIS_STATUS_REASON_CODES = MappingProxyType(
    {
        POWER_ANALYSIS_STATUS_COMPLETED: POWER_ANALYSIS_COMPLETED,
        POWER_ANALYSIS_STATUS_REJECTED: POWER_ANALYSIS_REJECTED,
        POWER_ANALYSIS_STATUS_FAILED: POWER_ANALYSIS_FAILED,
    }
)
POWER_ANALYSIS_EVIDENCE_DIGEST_ALGORITHM = "sha256"
POWER_ANALYSIS_PROVENANCE_FIELDS = frozenset(
    {"library", "version", "solver_class"}
)
POWER_ANALYSIS_PROVENANCE_LIBRARY = "statsmodels"
POWER_ANALYSIS_SOLVER_CLASSES = MappingProxyType(
    {
        "independent_t": "TTestIndPower",
        "one_way_anova": "FTestAnovaPower",
        "two_proportion_z": "NormalIndPower",
    }
)
POWER_ANALYSIS_MAX_NUMERIC_INPUT = 1e12
POWER_ANALYSIS_MAX_GROUPS = 10000
POWER_ANALYSIS_MAX_GRID_AXES = 6
POWER_ANALYSIS_MAX_GRID_VALUES_PER_AXIS = 20
POWER_ANALYSIS_MAX_GRID_SCENARIOS = 100

_INPUT_FIELDS = {
    "design",
    "solve_for",
    "effect_size_type",
    "alpha",
    "power",
    "sample_size",
    "effect_size",
    "ratio",
    "alternative",
    "k_groups",
}
_RESULT_FIELDS = {
    "contract",
    "contract_version",
    "status",
    "reason_code",
    "design",
    "solve_for",
    "effect_size_type",
    "design_semantics",
    "inputs",
    "solved_value",
    "provenance",
    "evidence_digest",
}
_RESULT_FIELDS_WITH_GRID = _RESULT_FIELDS | {"sensitivity_grid"}
_SCENARIO_INPUT_FIELDS = (
    "design",
    "solve_for",
    "effect_size_type",
    "alpha",
    "power",
    "sample_size",
    "effect_size",
    "ratio",
    "alternative",
    "k_groups",
)
_NUMERIC_INPUT_FIELDS = frozenset(
    {"alpha", "power", "sample_size", "effect_size", "ratio"}
)


def compute_power_analysis_evidence_digest(payload: Mapping[str, Any]) -> str:
    """Hash a result payload after excluding its evidence digest field."""

    if not isinstance(payload, Mapping):
        raise ContractError("power-analysis evidence payload must be a mapping")
    digest_payload = {
        key: value for key, value in payload.items() if key != "evidence_digest"
    }
    try:
        return sha256_canonical(digest_payload)
    except (TypeError, ValueError) as exc:
        raise ContractError("power-analysis evidence payload is not canonical JSON") from exc


def _result_payload_without_digest(
    *,
    status: str,
    reason_code: str,
    design: str,
    solve_for: str,
    effect_size_type: str,
    design_semantics: Mapping[str, Any],
    inputs: Mapping[str, Any],
    solved_value: float,
    provenance: Mapping[str, Any],
    sensitivity_grid: Mapping[str, Any] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract": POWER_ANALYSIS_CONTRACT,
        "contract_version": POWER_ANALYSIS_CONTRACT_VERSION,
        "status": status,
        "reason_code": reason_code,
        "design": design,
        "solve_for": solve_for,
        "effect_size_type": effect_size_type,
        "design_semantics": thaw_json(design_semantics),
        "inputs": thaw_json(inputs),
        "solved_value": solved_value,
        "provenance": thaw_json(provenance),
    }
    if sensitivity_grid is not None:
        payload["sensitivity_grid"] = thaw_json(sensitivity_grid)
    return payload


def _validate_evidence_digest(value: Any, expected: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or value.lower() != value
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ContractError("evidence_digest must be a lowercase SHA-256 hexadecimal digest")
    if value != expected:
        raise ContractError("evidence_digest does not match the result evidence")


def _require_string(value: Any, field_name: str) -> None:
    if type(value) is not str or not value:
        raise ContractError(f"{field_name} must be a non-empty string")


def _require_optional_number(value: Any, field_name: str) -> None:
    if value is not None and (
        type(value) not in {int, float} or isinstance(value, bool)
    ):
        raise ContractError(f"{field_name} must be a finite JSON number or null")
    if value is None:
        return
    if type(value) is int and abs(value) > POWER_ANALYSIS_MAX_NUMERIC_INPUT:
        raise ContractError(f"{field_name} is outside the supported numeric bound")
    if type(value) is float and (
        not math.isfinite(value) or abs(value) > POWER_ANALYSIS_MAX_NUMERIC_INPUT
    ):
        raise ContractError(f"{field_name} must be finite")


def _require_declared_choice(value: Any, choices: frozenset[str], field_name: str) -> None:
    if type(value) is not str or value not in choices:
        raise ContractError(f"{field_name} is not declared")


def _validate_probability(value: float | int | None, field_name: str) -> None:
    if value is None:
        return
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError):
        raise ContractError(f"{field_name} must be finite") from None
    if not 0.0 < normalized < 1.0:
        raise ContractError(f"{field_name} must be strictly between 0 and 1")


def _sample_size_minimum(request: "PowerAnalysisInput") -> float:
    if request.design in {"independent_t", "two_proportion_z"}:
        return 2.0
    return float(request.k_groups + 1)


def _validate_input_semantics(
    *,
    design: str,
    solve_for: str,
    effect_size_type: str,
    alpha: float | int | None,
    power: float | int | None,
    sample_size: float | int | None,
    effect_size: float | int | None,
    ratio: float | int | None,
    alternative: str | None,
    k_groups: int | None,
) -> None:
    _require_declared_choice(design, POWER_ANALYSIS_DESIGNS, "design")
    _require_declared_choice(solve_for, POWER_ANALYSIS_SOLVE_TARGETS, "solve_for")
    _require_declared_choice(
        effect_size_type, POWER_ANALYSIS_EFFECT_SIZE_TYPES, "effect_size_type"
    )
    expected_effect_size = POWER_ANALYSIS_DESIGN_EFFECT_SIZE_TYPES[design]
    if effect_size_type != expected_effect_size:
        raise ContractError(
            f"effect_size_type must be {expected_effect_size} for {design}"
        )

    for field_name, value in (
        ("alpha", alpha),
        ("power", power),
        ("sample_size", sample_size),
        ("effect_size", effect_size),
        ("ratio", ratio),
    ):
        _require_optional_number(value, field_name)
    _validate_probability(alpha, "alpha")
    _validate_probability(power, "power")
    if sample_size is not None and sample_size <= 0:
        raise ContractError("sample_size must be positive")
    if effect_size is not None:
        if effect_size == 0:
            raise ContractError("effect_size must be non-zero")
        if design == "one_way_anova" and effect_size < 0:
            raise ContractError("cohens_f must be positive")

    unknowns = [
        field_name
        for field_name, value in (
            ("alpha", alpha),
            ("power", power),
            ("sample_size", sample_size),
            ("effect_size", effect_size),
        )
        if value is None
    ]
    if len(unknowns) != 1 or unknowns[0] != solve_for:
        raise ContractError(
            "exactly one of alpha, power, sample_size, and effect_size must be null and match solve_for"
        )

    if design in {"independent_t", "two_proportion_z"}:
        if ratio is None or alternative is None:
            raise ContractError("ratio and alternative are required for this design")
        if ratio <= 0:
            raise ContractError("ratio must be positive")
        _require_declared_choice(
            alternative, POWER_ANALYSIS_ALTERNATIVES, "alternative"
        )
        if k_groups is not None:
            raise ContractError("k_groups is not valid for this design")
    else:
        if ratio is not None or alternative is not None:
            raise ContractError("ratio and alternative are not valid for one_way_anova")
        if type(k_groups) is not int or isinstance(k_groups, bool) or k_groups < 2:
            raise ContractError("k_groups must be an integer of at least 2")
        if k_groups > POWER_ANALYSIS_MAX_GROUPS:
            raise ContractError("k_groups is outside the supported bound")

    if sample_size is not None:
        minimum = 2.0 if design in {"independent_t", "two_proportion_z"} else float(k_groups + 1)
        if sample_size < minimum:
            raise ContractError(
                f"sample_size must be at least {minimum:g} for {design}"
            )


def _validate_design_semantics(
    semantics: Mapping[str, Any], request: "PowerAnalysisInput"
) -> None:
    if not isinstance(semantics, Mapping) or not semantics:
        raise ContractError("design_semantics must be a non-empty mapping")
    if any(type(key) is not str for key in semantics):
        raise ContractError("design_semantics keys must be strings")

    required = {"family", "effect_size", "sample_size", "rounding_policy"}
    if request.design in {"independent_t", "two_proportion_z"}:
        required.update({"ratio", "alternative"})
    else:
        required.add("k_groups")
    missing = required - set(semantics)
    if missing:
        raise ContractError(
            "design_semantics is missing fields: " + ", ".join(sorted(missing))
        )
    if semantics["family"] != request.design:
        raise ContractError("design_semantics.family must match design")
    if semantics["effect_size"] != request.effect_size_type:
        raise ContractError("design_semantics.effect_size must match effect_size_type")
    expected_sample_size = (
        "total_nobs"
        if request.design == "one_way_anova"
        else "nobs1_per_group"
    )
    if semantics["sample_size"] != expected_sample_size:
        raise ContractError("design_semantics.sample_size is invalid for design")
    _require_declared_choice(
        semantics["rounding_policy"], POWER_ANALYSIS_ROUNDING_POLICIES, "rounding_policy"
    )
    if request.design in {"independent_t", "two_proportion_z"}:
        if semantics["ratio"] != "nobs2_over_nobs1":
            raise ContractError("design_semantics.ratio must describe nobs2_over_nobs1")
        if semantics["alternative"] != request.alternative:
            raise ContractError("design_semantics.alternative must match inputs.alternative")
    elif semantics["k_groups"] != request.k_groups:
        raise ContractError("design_semantics.k_groups must match inputs.k_groups")


def _validate_provenance(
    provenance: Mapping[str, Any], request: "PowerAnalysisInput"
) -> None:
    if not isinstance(provenance, Mapping) or not provenance:
        raise ContractError("provenance must be a non-empty mapping")
    if any(type(key) is not str for key in provenance):
        raise ContractError("provenance keys must be strings")
    missing = POWER_ANALYSIS_PROVENANCE_FIELDS - set(provenance)
    if missing:
        raise ContractError(
            "provenance is missing fields: " + ", ".join(sorted(missing))
        )
    for field_name in POWER_ANALYSIS_PROVENANCE_FIELDS:
        _require_string(provenance[field_name], f"provenance.{field_name}")
    if provenance["library"] != POWER_ANALYSIS_PROVENANCE_LIBRARY:
        raise ContractError("provenance.library must be statsmodels")
    if provenance["solver_class"] != POWER_ANALYSIS_SOLVER_CLASSES[request.design]:
        raise ContractError("provenance.solver_class does not match design")


def _validate_solved_value(
    solved_value: Any, request: "PowerAnalysisInput"
) -> None:
    if type(solved_value) is not float:
        raise ContractError("solved_value must be a native float")
    if not math.isfinite(solved_value):
        raise ContractError("solved_value must be finite")
    if request.solve_for in {"alpha", "power"}:
        if not 0.0 < solved_value < 1.0:
            raise ContractError("solved probability must be strictly between 0 and 1")
    elif request.solve_for == "sample_size":
        if solved_value < _sample_size_minimum(request):
            raise ContractError("solved sample_size is below the design minimum")
    elif solved_value == 0.0 or (
        request.design == "one_way_anova" and solved_value < 0.0
    ):
        raise ContractError("solved effect_size violates the declared sign convention")


def _validate_grid_number(value: Any, field_name: str) -> None:
    if type(value) not in {int, float} or isinstance(value, bool):
        raise ContractError(f"sensitivity_grid.{field_name} values must be numeric")
    if type(value) is int and abs(value) > POWER_ANALYSIS_MAX_NUMERIC_INPUT:
        raise ContractError(f"sensitivity_grid.{field_name} exceeds the numeric bound")
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError):
        raise ContractError(f"sensitivity_grid.{field_name} values must be finite") from None
    if not math.isfinite(normalized) or abs(normalized) > POWER_ANALYSIS_MAX_NUMERIC_INPUT:
        raise ContractError(f"sensitivity_grid.{field_name} values must be finite and bounded")


def _canonical_input_value(field_name: str, value: Any) -> Any:
    if value is None or field_name == "k_groups" or field_name not in _NUMERIC_INPUT_FIELDS:
        return value
    return float(value)


def _scenario_signature(inputs: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(
        _canonical_input_value(field_name, inputs[field_name])
        for field_name in _SCENARIO_INPUT_FIELDS
    )


def _validate_sensitivity_grid(
    sensitivity_grid: Mapping[str, Any], request: "PowerAnalysisInput"
) -> None:
    if not isinstance(sensitivity_grid, Mapping) or not sensitivity_grid:
        raise ContractError("sensitivity_grid must be a non-empty mapping")
    if any(type(key) is not str for key in sensitivity_grid):
        raise ContractError("sensitivity_grid keys must be strings")
    if "axes" not in sensitivity_grid or "scenarios" not in sensitivity_grid:
        raise ContractError("sensitivity_grid requires axes and scenarios")

    axes = sensitivity_grid["axes"]
    scenarios = sensitivity_grid["scenarios"]
    if not isinstance(axes, Mapping) or not axes:
        raise ContractError("sensitivity_grid.axes must be a non-empty mapping")
    if len(axes) > POWER_ANALYSIS_MAX_GRID_AXES:
        raise ContractError("sensitivity_grid has too many axes")
    if any(type(key) is not str for key in axes):
        raise ContractError("sensitivity_grid axis names must be strings")
    if not isinstance(scenarios, (list, tuple)) or not scenarios:
        raise ContractError("sensitivity_grid.scenarios must be a non-empty array")

    allowed_axes = {
        "alpha",
        "power",
        "sample_size",
        "effect_size",
        "ratio",
        "k_groups",
    }
    if request.design == "one_way_anova":
        allowed_axes.discard("ratio")
    else:
        allowed_axes.discard("k_groups")
    normalized_axes: dict[str, list[Any]] = {}
    for field_name in sorted(axes):
        if type(field_name) is not str or field_name not in allowed_axes:
            raise ContractError(f"sensitivity_grid axis is not valid: {field_name!r}")
        if field_name == request.solve_for:
            raise ContractError("sensitivity_grid cannot vary solve_for")
        values = axes[field_name]
        if not isinstance(values, (list, tuple)) or not values:
            raise ContractError(f"sensitivity_grid axis {field_name} must be non-empty")
        if len(values) > POWER_ANALYSIS_MAX_GRID_VALUES_PER_AXIS:
            raise ContractError(f"sensitivity_grid axis {field_name} is unbounded")
        normalized_values: list[Any] = []
        for value in values:
            _validate_grid_number(value, field_name)
            if field_name == "k_groups" and (
                type(value) is not int or value < 2
            ):
                raise ContractError("sensitivity_grid k_groups must be integer >= 2")
            normalized_values.append(_canonical_input_value(field_name, value))
        if len(set(normalized_values)) != len(normalized_values):
            raise ContractError(f"sensitivity_grid axis {field_name} has duplicates")
        normalized_axes[field_name] = normalized_values

    expected_scenarios = math.prod(len(values) for values in normalized_axes.values())
    if expected_scenarios > POWER_ANALYSIS_MAX_GRID_SCENARIOS:
        raise ContractError("sensitivity_grid has too many scenarios")
    if len(scenarios) != expected_scenarios:
        raise ContractError("sensitivity_grid.scenarios does not cover all axis combinations")

    base_inputs = request.to_dict()
    expected_signatures: set[tuple[Any, ...]] = set()
    for axis_values in product(
        *(normalized_axes[field_name] for field_name in sorted(normalized_axes))
    ):
        expected_inputs = dict(base_inputs)
        for field_name, value in zip(sorted(normalized_axes), axis_values, strict=True):
            expected_inputs[field_name] = value
        expected_signatures.add(_scenario_signature(expected_inputs))

    actual_signatures: list[tuple[Any, ...]] = []
    for scenario in scenarios:
        if not isinstance(scenario, Mapping):
            raise ContractError("sensitivity_grid scenarios must be mappings")
        require_exact_keys(
            scenario,
            {"inputs", "solved_value"},
            "sensitivity_grid scenario",
        )
        scenario_request = PowerAnalysisInput.from_dict(scenario["inputs"])
        if (
            scenario_request.design != request.design
            or scenario_request.solve_for != request.solve_for
            or scenario_request.effect_size_type != request.effect_size_type
        ):
            raise ContractError("sensitivity_grid scenario inputs do not match result")
        actual_signatures.append(_scenario_signature(scenario_request.to_dict()))
        _validate_solved_value(scenario["solved_value"], scenario_request)
    if len(set(actual_signatures)) != len(actual_signatures):
        raise ContractError("sensitivity_grid contains duplicate scenario inputs")
    if set(actual_signatures) != expected_signatures:
        raise ContractError(
            "sensitivity_grid scenarios must exactly cover the Cartesian product without drift"
        )


@dataclass(frozen=True)
class PowerAnalysisInput:
    """All explicit power-analysis inputs, including the one solve target."""

    design: str
    solve_for: str
    effect_size_type: str
    alpha: float | int | None = None
    power: float | int | None = None
    sample_size: float | int | None = None
    effect_size: float | int | None = None
    ratio: float | int | None = None
    alternative: str | None = None
    k_groups: int | None = None

    def __post_init__(self) -> None:
        _validate_input_semantics(
            design=self.design,
            solve_for=self.solve_for,
            effect_size_type=self.effect_size_type,
            alpha=self.alpha,
            power=self.power,
            sample_size=self.sample_size,
            effect_size=self.effect_size,
            ratio=self.ratio,
            alternative=self.alternative,
            k_groups=self.k_groups,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "design": self.design,
            "solve_for": self.solve_for,
            "effect_size_type": self.effect_size_type,
            "alpha": self.alpha,
            "power": self.power,
            "sample_size": self.sample_size,
            "effect_size": self.effect_size,
            "ratio": self.ratio,
            "alternative": self.alternative,
            "k_groups": self.k_groups,
        }
        return thaw_json(freeze_json(payload, "power-analysis input"))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PowerAnalysisInput":
        require_exact_keys(value, _INPUT_FIELDS, "power-analysis input")
        return cls(**{field: value[field] for field in _INPUT_FIELDS})


@dataclass(frozen=True)
class PowerAnalysisResult:
    """Completed power-analysis evidence with immutable JSON-safe storage."""

    design: str
    solve_for: str
    effect_size_type: str
    design_semantics: Mapping[str, Any]
    inputs: Mapping[str, Any]
    solved_value: float
    provenance: Mapping[str, Any]
    evidence_digest: str | None = None
    sensitivity_grid: Mapping[str, Any] | None = None
    status: str = POWER_ANALYSIS_STATUS_COMPLETED
    reason_code: str = POWER_ANALYSIS_COMPLETED

    def __post_init__(self) -> None:
        request = PowerAnalysisInput.from_dict(self.inputs)
        if self.design != request.design:
            raise ContractError("design must match inputs.design")
        if self.solve_for != request.solve_for:
            raise ContractError("solve_for must match inputs.solve_for")
        if self.effect_size_type != request.effect_size_type:
            raise ContractError("effect_size_type must match inputs.effect_size_type")
        _require_declared_choice(self.status, POWER_ANALYSIS_STATUSES, "status")
        _require_string(self.reason_code, "reason_code")
        if self.reason_code not in POWER_ANALYSIS_REASON_CODES:
            raise ContractError("reason_code is not a declared power-analysis reason code")
        if self.reason_code != POWER_ANALYSIS_STATUS_REASON_CODES[self.status]:
            raise ContractError("reason_code must match status")
        _validate_solved_value(self.solved_value, request)
        _validate_design_semantics(self.design_semantics, request)
        _validate_provenance(self.provenance, request)
        frozen_semantics = freeze_json(self.design_semantics, "design_semantics")
        frozen_inputs = freeze_json(request.to_dict(), "inputs")
        frozen_provenance = freeze_json(self.provenance, "provenance")
        frozen_grid = None
        if self.sensitivity_grid is not None:
            _validate_sensitivity_grid(self.sensitivity_grid, request)
            frozen_grid = freeze_json(self.sensitivity_grid, "sensitivity_grid")
        payload = _result_payload_without_digest(
            status=self.status,
            reason_code=self.reason_code,
            design=self.design,
            solve_for=self.solve_for,
            effect_size_type=self.effect_size_type,
            design_semantics=frozen_semantics,
            inputs=frozen_inputs,
            solved_value=self.solved_value,
            provenance=frozen_provenance,
            sensitivity_grid=frozen_grid,
        )
        _validate_evidence_digest(
            self.evidence_digest,
            compute_power_analysis_evidence_digest(payload),
        )
        object.__setattr__(self, "design_semantics", frozen_semantics)
        object.__setattr__(self, "inputs", frozen_inputs)
        object.__setattr__(self, "provenance", frozen_provenance)
        object.__setattr__(self, "sensitivity_grid", frozen_grid)

    def to_dict(self) -> dict[str, Any]:
        payload = _result_payload_without_digest(
            status=self.status,
            reason_code=self.reason_code,
            design=self.design,
            solve_for=self.solve_for,
            effect_size_type=self.effect_size_type,
            design_semantics=self.design_semantics,
            inputs=self.inputs,
            solved_value=self.solved_value,
            provenance=self.provenance,
            sensitivity_grid=self.sensitivity_grid,
        )
        _validate_evidence_digest(
            self.evidence_digest,
            compute_power_analysis_evidence_digest(payload),
        )
        payload["evidence_digest"] = self.evidence_digest
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PowerAnalysisResult":
        if not isinstance(value, Mapping):
            raise ContractError("power-analysis result must be a mapping")
        if value.get("contract") != POWER_ANALYSIS_CONTRACT:
            raise ContractError("contract is not the declared power-analysis contract")
        if value.get("contract_version") != POWER_ANALYSIS_CONTRACT_VERSION:
            raise ContractError("contract_version is not the declared power-analysis version")
        fields = _RESULT_FIELDS_WITH_GRID if "sensitivity_grid" in value else _RESULT_FIELDS
        require_exact_keys(value, fields, "power-analysis result")
        return cls(
            design=value["design"],
            solve_for=value["solve_for"],
            effect_size_type=value["effect_size_type"],
            design_semantics=value["design_semantics"],
            inputs=value["inputs"],
            solved_value=value["solved_value"],
            provenance=value["provenance"],
            evidence_digest=value["evidence_digest"],
            sensitivity_grid=value.get("sensitivity_grid"),
            status=value["status"],
            reason_code=value["reason_code"],
        )


PowerAnalysisRequest = PowerAnalysisInput
PowerAnalysisResultEnvelope = PowerAnalysisResult


def make_power_analysis_result(**kwargs: Any) -> dict[str, Any]:
    """Build a validated, thawed result envelope at the public boundary."""

    return PowerAnalysisResult(**kwargs).to_dict()


__all__ = [
    "POWER_ANALYSIS_ALTERNATIVES",
    "POWER_ANALYSIS_COMPLETED",
    "POWER_ANALYSIS_CONTRACT",
    "POWER_ANALYSIS_CONTRACT_VERSION",
    "POWER_ANALYSIS_DESIGNS",
    "POWER_ANALYSIS_DESIGN_EFFECT_SIZE_TYPES",
    "POWER_ANALYSIS_EVIDENCE_DIGEST_ALGORITHM",
    "POWER_ANALYSIS_EFFECT_SIZE_TYPES",
    "POWER_ANALYSIS_FAILED",
    "POWER_ANALYSIS_MAX_GROUPS",
    "POWER_ANALYSIS_MAX_GRID_AXES",
    "POWER_ANALYSIS_MAX_GRID_SCENARIOS",
    "POWER_ANALYSIS_MAX_GRID_VALUES_PER_AXIS",
    "POWER_ANALYSIS_MAX_NUMERIC_INPUT",
    "POWER_ANALYSIS_OPERATION_IDS",
    "POWER_ANALYSIS_PROVENANCE_FIELDS",
    "POWER_ANALYSIS_PROVENANCE_LIBRARY",
    "POWER_ANALYSIS_REASON_CODES",
    "POWER_ANALYSIS_REJECTED",
    "POWER_ANALYSIS_ROUNDING_POLICIES",
    "POWER_ANALYSIS_SAMPLE_SIZE_SEMANTICS",
    "POWER_ANALYSIS_STATUS_COMPLETED",
    "POWER_ANALYSIS_STATUS_FAILED",
    "POWER_ANALYSIS_STATUS_REASON_CODES",
    "POWER_ANALYSIS_STATUS_REJECTED",
    "POWER_ANALYSIS_STATUSES",
    "POWER_ANALYSIS_SOLVER_CLASSES",
    "POWER_ANALYSIS_SOLVE_TARGETS",
    "PowerAnalysisInput",
    "PowerAnalysisRequest",
    "PowerAnalysisResult",
    "PowerAnalysisResultEnvelope",
    "compute_power_analysis_evidence_digest",
    "make_power_analysis_result",
]
