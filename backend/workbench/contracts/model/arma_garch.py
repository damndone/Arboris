"""Frozen public input contract for the v1.8 ARMA-GARCH Model Pack."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from workbench.canonical import sha256_canonical
from workbench.contracts.common.envelope import (
    ContractError,
    freeze_json,
    require_exact_keys,
    thaw_json,
)


ARMA_GARCH_PACK_ID = "time_series.arma_garch"
ARMA_GARCH_CONTRACT_VERSION = "1.0"

AR_ORDER_LIMIT = 10
MA_ORDER_LIMIT = 10
AUTO_AR_ORDER_LIMIT = 3
AUTO_MA_ORDER_LIMIT = 3
AUTO_TOTAL_ORDER_LIMIT = 4
ARCH_ORDER_LIMIT = 10
GARCH_P_ORDER_LIMIT = 5
GARCH_Q_ORDER_LIMIT = 5

_TOP_LEVEL_FIELDS = {
    "pack_id",
    "contract_version",
    "dataset_ref",
    "time_column",
    "value_column",
    "time_index_semantics",
    "transform",
    "transform_confirmed",
    "analysis_goal",
    "selection_mode",
    "arma",
    "variance",
    "estimation_strategy",
    "innovation_distribution",
    "missing_value_policy",
    "validation",
    "forecast",
    "random_seed",
}
_REQUIRED_TOP_LEVEL_FIELDS = {
    "dataset_ref",
    "time_column",
    "value_column",
    "time_index_semantics",
    "transform",
    "transform_confirmed",
    "validation",
}

_ARMA_DEFAULTS: dict[str, object] = {
    "p": None,
    "q": None,
    "constant_mode": "auto",
    "auto_max_p": 3,
    "auto_max_q": 3,
    "auto_max_total_order": 4,
}
_VARIANCE_DEFAULTS: dict[str, object] = {
    "model": "auto",
    "arch_p": None,
    "garch_p": None,
    "garch_q": None,
    "auto_arch_max_p": 10,
    "include_garch_1_1": True,
}
_VALIDATION_DEFAULTS: dict[str, object] = {
    "method": "expanding_window_one_step",
    "validation_n": None,
    "refit_every": 1,
    "selection_repeated_during_validation": False,
}
_FORECAST_DEFAULTS: dict[str, object] = {
    "horizon": 1,
    "interval_level": 0.95,
    "lower_quantile": 0.05,
}


class ArmaGarchContractError(ContractError):
    """A public, structured rejection of an ARMA-GARCH input payload."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        evidence: Mapping[str, object] | None = None,
        impact: str = "The analysis contract cannot be frozen or executed.",
        recommended_actions: list[Mapping[str, object]] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        frozen_evidence = freeze_json(evidence or {}, "error.evidence")
        frozen_actions = freeze_json(
            recommended_actions or [], "error.recommended_actions"
        )
        assert isinstance(frozen_evidence, Mapping)
        assert isinstance(frozen_actions, tuple)
        self.evidence = frozen_evidence
        self.impact = impact
        self.recommended_actions = frozen_actions
        super().__init__(f"{code}: {message}")

    def to_dict(self) -> dict[str, object]:
        return {
            "severity": "blocking",
            "code": self.code,
            "message": self.message,
            "evidence": thaw_json(self.evidence),
            "impact": self.impact,
            "recommended_actions": thaw_json(self.recommended_actions),
        }


def _invalid(message: str, *, evidence: Mapping[str, object] | None = None) -> None:
    raise ArmaGarchContractError("INVALID_ORDER", message, evidence=evidence)


def _require_non_empty_string(value: object, field_name: str) -> str:
    if type(value) is not str or not value:
        _invalid(f"{field_name} must be a non-empty string")
    return value


def _require_choice(value: object, allowed: set[str], field_name: str) -> str:
    if type(value) is not str or value not in allowed:
        _invalid(f"{field_name} must be one of: {', '.join(sorted(allowed))}")
    return value


def _require_int(
    value: object,
    field_name: str,
    *,
    minimum: int,
    maximum: int | None = None,
) -> int:
    if type(value) is not int or value < minimum:
        _invalid(
            f"{field_name} must be an integer greater than or equal to {minimum}",
            evidence={"field": field_name, "value": value},
        )
    if maximum is not None and value > maximum:
        raise ArmaGarchContractError(
            "CANDIDATE_LIMIT_EXCEEDED",
            f"{field_name} exceeds the server hard limit",
            evidence={"field": field_name, "limit": maximum, "value": value},
        )
    return value


def _require_optional_order(
    value: object, field_name: str, maximum: int, *, minimum: int = 0
) -> int | None:
    if value is None:
        return None
    return _require_int(value, field_name, minimum=minimum, maximum=maximum)


def _merged_section(
    value: object, defaults: Mapping[str, object], section_name: str
) -> dict[str, object]:
    if value is None:
        return dict(defaults)
    if not isinstance(value, Mapping):
        _invalid(f"{section_name} must be a mapping")
    merged = {**defaults, **dict(value)}
    try:
        require_exact_keys(merged, set(defaults), section_name)
    except ContractError as exc:
        raise ArmaGarchContractError("INVALID_ORDER", str(exc)) from exc
    return merged


@dataclass(frozen=True)
class ArmaOptions:
    p: int | None
    q: int | None
    constant_mode: Literal["auto", "include", "exclude"]
    auto_max_p: int
    auto_max_q: int
    auto_max_total_order: int

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ArmaOptions":
        return cls(
            p=_require_optional_order(value["p"], "arma.p", AR_ORDER_LIMIT),
            q=_require_optional_order(value["q"], "arma.q", MA_ORDER_LIMIT),
            constant_mode=_require_choice(
                value["constant_mode"], {"auto", "include", "exclude"}, "arma.constant_mode"
            ),
            auto_max_p=_require_int(
                value["auto_max_p"],
                "arma.auto_max_p",
                minimum=0,
                maximum=AUTO_AR_ORDER_LIMIT,
            ),
            auto_max_q=_require_int(
                value["auto_max_q"],
                "arma.auto_max_q",
                minimum=0,
                maximum=AUTO_MA_ORDER_LIMIT,
            ),
            auto_max_total_order=_require_int(
                value["auto_max_total_order"],
                "arma.auto_max_total_order",
                minimum=0,
                maximum=AUTO_TOTAL_ORDER_LIMIT,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "p": self.p,
            "q": self.q,
            "constant_mode": self.constant_mode,
            "auto_max_p": self.auto_max_p,
            "auto_max_q": self.auto_max_q,
            "auto_max_total_order": self.auto_max_total_order,
        }


@dataclass(frozen=True)
class VarianceOptions:
    model: Literal["auto", "constant_variance", "arch", "garch"]
    arch_p: int | None
    garch_p: int | None
    garch_q: int | None
    auto_arch_max_p: int
    include_garch_1_1: bool

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "VarianceOptions":
        include_garch = value["include_garch_1_1"]
        if type(include_garch) is not bool:
            _invalid("variance.include_garch_1_1 must be a bool")
        return cls(
            model=_require_choice(
                value["model"],
                {"auto", "constant_variance", "arch", "garch"},
                "variance.model",
            ),
            arch_p=_require_optional_order(
                value["arch_p"], "variance.arch_p", ARCH_ORDER_LIMIT, minimum=1
            ),
            garch_p=_require_optional_order(
                value["garch_p"], "variance.garch_p", GARCH_P_ORDER_LIMIT, minimum=1
            ),
            garch_q=_require_optional_order(
                value["garch_q"], "variance.garch_q", GARCH_Q_ORDER_LIMIT, minimum=1
            ),
            auto_arch_max_p=_require_int(
                value["auto_arch_max_p"],
                "variance.auto_arch_max_p",
                minimum=1,
                maximum=ARCH_ORDER_LIMIT,
            ),
            include_garch_1_1=include_garch,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "arch_p": self.arch_p,
            "garch_p": self.garch_p,
            "garch_q": self.garch_q,
            "auto_arch_max_p": self.auto_arch_max_p,
            "include_garch_1_1": self.include_garch_1_1,
        }


@dataclass(frozen=True)
class ValidationOptions:
    method: Literal["expanding_window_one_step"]
    validation_n: int | None
    refit_every: int
    selection_repeated_during_validation: Literal[False]

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ValidationOptions":
        method = _require_choice(
            value["method"], {"expanding_window_one_step"}, "validation.method"
        )
        validation_n = value["validation_n"]
        if validation_n is not None:
            validation_n = _require_int(
                validation_n, "validation.validation_n", minimum=1
            )
        refit_every = _require_int(
            value["refit_every"], "validation.refit_every", minimum=1
        )
        if value["selection_repeated_during_validation"] is not False:
            _invalid("selection_repeated_during_validation must be false in v1.8")
        return cls(method, validation_n, refit_every, False)

    def to_dict(self) -> dict[str, object]:
        return {
            "method": self.method,
            "validation_n": self.validation_n,
            "refit_every": self.refit_every,
            "selection_repeated_during_validation": self.selection_repeated_during_validation,
        }


@dataclass(frozen=True)
class ForecastOptions:
    horizon: Literal[1]
    interval_level: float
    lower_quantile: float

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ForecastOptions":
        if value["horizon"] != 1 or type(value["horizon"]) is not int:
            _invalid("forecast.horizon must be exactly 1 in v1.8")
        interval = value["interval_level"]
        quantile = value["lower_quantile"]
        if type(interval) is not float or not 0.0 < interval < 1.0:
            _invalid("forecast.interval_level must be a float between zero and one")
        if type(quantile) is not float or not 0.0 < quantile < 1.0:
            _invalid("forecast.lower_quantile must be a float between zero and one")
        return cls(1, interval, quantile)

    def to_dict(self) -> dict[str, object]:
        return {
            "horizon": self.horizon,
            "interval_level": self.interval_level,
            "lower_quantile": self.lower_quantile,
        }


@dataclass(frozen=True)
class ArmaGarchAnalysisContract:
    """The fully resolved, immutable analysis options used by an execution."""

    dataset_ref: str
    time_column: str
    value_column: str
    time_index_semantics: Literal[
        "regular_calendar",
        "business_or_trading_observations",
        "observation_order",
    ]
    transform: Literal["level", "log_level", "diff_1", "log_return_pct"]
    transform_confirmed: Literal[True]
    analysis_goal: Literal["balanced", "forecast", "parsimony", "replication"]
    selection_mode: Literal["auto", "manual"]
    arma: ArmaOptions
    variance: VarianceOptions
    estimation_strategy: Literal["auto", "sequential", "joint"]
    innovation_distribution: Literal["normal", "student_t"]
    missing_value_policy: Literal["block", "drop_missing_confirmed"]
    validation: ValidationOptions
    forecast: ForecastOptions
    random_seed: int
    pack_id: str = ARMA_GARCH_PACK_ID
    contract_version: str = ARMA_GARCH_CONTRACT_VERSION

    @property
    def contract_hash(self) -> str:
        return sha256_canonical(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "pack_id": self.pack_id,
            "contract_version": self.contract_version,
            "dataset_ref": self.dataset_ref,
            "time_column": self.time_column,
            "value_column": self.value_column,
            "time_index_semantics": self.time_index_semantics,
            "transform": self.transform,
            "transform_confirmed": self.transform_confirmed,
            "analysis_goal": self.analysis_goal,
            "selection_mode": self.selection_mode,
            "arma": self.arma.to_dict(),
            "variance": self.variance.to_dict(),
            "estimation_strategy": self.estimation_strategy,
            "innovation_distribution": self.innovation_distribution,
            "missing_value_policy": self.missing_value_policy,
            "validation": self.validation.to_dict(),
            "forecast": self.forecast.to_dict(),
            "random_seed": self.random_seed,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ArmaGarchAnalysisContract":
        if not isinstance(value, Mapping):
            raise ArmaGarchContractError("INVALID_ORDER", "analysis input must be a mapping")
        if any(type(key) is not str for key in value):
            raise ArmaGarchContractError(
                "INVALID_ORDER", "ARMA-GARCH input mapping keys must be strings"
            )
        unknown = set(value) - _TOP_LEVEL_FIELDS
        missing = _REQUIRED_TOP_LEVEL_FIELDS - set(value)
        if unknown:
            raise ArmaGarchContractError(
                "INVALID_ORDER",
                "unknown ARMA-GARCH input field: " + ", ".join(sorted(unknown)),
            )
        if missing:
            raise ArmaGarchContractError(
                "INVALID_ORDER",
                "missing ARMA-GARCH input field: " + ", ".join(sorted(missing)),
            )

        resolved = {
            "pack_id": ARMA_GARCH_PACK_ID,
            "contract_version": ARMA_GARCH_CONTRACT_VERSION,
            "analysis_goal": "balanced",
            "selection_mode": "auto",
            "arma": None,
            "variance": None,
            "estimation_strategy": "auto",
            "innovation_distribution": "normal",
            "missing_value_policy": "block",
            "validation": None,
            "forecast": None,
            "random_seed": 0,
            **dict(value),
        }
        if resolved["pack_id"] != ARMA_GARCH_PACK_ID:
            _invalid(f"pack_id must be {ARMA_GARCH_PACK_ID}")
        if resolved["contract_version"] != ARMA_GARCH_CONTRACT_VERSION:
            _invalid(f"contract_version must be {ARMA_GARCH_CONTRACT_VERSION}")
        if resolved["transform_confirmed"] is not True:
            _invalid("transform_confirmed must be true before execution")

        arma = ArmaOptions.from_dict(
            _merged_section(resolved["arma"], _ARMA_DEFAULTS, "arma")
        )
        variance = VarianceOptions.from_dict(
            _merged_section(resolved["variance"], _VARIANCE_DEFAULTS, "variance")
        )
        selection_mode = _require_choice(
            resolved["selection_mode"], {"auto", "manual"}, "selection_mode"
        )
        _validate_selection_mode(selection_mode, arma, variance)
        estimation_strategy = _require_choice(
            resolved["estimation_strategy"],
            {"auto", "sequential", "joint"},
            "estimation_strategy",
        )
        if estimation_strategy == "joint" and arma.q is not None and arma.q > 0:
            raise ArmaGarchContractError(
                "UNSUPPORTED_JOINT_ARMA_GARCH",
                "v1.8 does not support joint estimation when arma.q is greater than zero",
                evidence={"arma_q": arma.q, "estimation_strategy": "joint"},
                impact="当前公共后端不能联合估计包含 MA 项的 ARMA-GARCH",
                recommended_actions=[
                    {
                        "operation": "model.rerun",
                        "patch": {"estimation_strategy": "sequential"},
                    },
                    {
                        "operation": "model.rerun",
                        "patch": {"arma": {"q": 0}, "estimation_strategy": "joint"},
                    },
                ],
            )
        random_seed = _require_int(
            resolved["random_seed"], "random_seed", minimum=0
        )
        return cls(
            dataset_ref=_require_non_empty_string(resolved["dataset_ref"], "dataset_ref"),
            time_column=_require_non_empty_string(resolved["time_column"], "time_column"),
            value_column=_require_non_empty_string(resolved["value_column"], "value_column"),
            time_index_semantics=_require_choice(
                resolved["time_index_semantics"],
                {
                    "regular_calendar",
                    "business_or_trading_observations",
                    "observation_order",
                },
                "time_index_semantics",
            ),
            transform=_require_choice(
                resolved["transform"],
                {"level", "log_level", "diff_1", "log_return_pct"},
                "transform",
            ),
            transform_confirmed=True,
            analysis_goal=_require_choice(
                resolved["analysis_goal"],
                {"balanced", "forecast", "parsimony", "replication"},
                "analysis_goal",
            ),
            selection_mode=selection_mode,
            arma=arma,
            variance=variance,
            estimation_strategy=estimation_strategy,
            innovation_distribution=_require_choice(
                resolved["innovation_distribution"],
                {"normal", "student_t"},
                "innovation_distribution",
            ),
            missing_value_policy=_require_choice(
                resolved["missing_value_policy"],
                {"block", "drop_missing_confirmed"},
                "missing_value_policy",
            ),
            validation=ValidationOptions.from_dict(
                _merged_section(resolved["validation"], _VALIDATION_DEFAULTS, "validation")
            ),
            forecast=ForecastOptions.from_dict(
                _merged_section(resolved["forecast"], _FORECAST_DEFAULTS, "forecast")
            ),
            random_seed=random_seed,
        )


def _validate_selection_mode(
    selection_mode: str, arma: ArmaOptions, variance: VarianceOptions
) -> None:
    if selection_mode == "auto":
        if arma.p is not None or arma.q is not None:
            _invalid("automatic selection requires arma.p and arma.q to be null")
        if variance.model != "auto" or any(
            order is not None for order in (variance.arch_p, variance.garch_p, variance.garch_q)
        ):
            _invalid("automatic selection requires variance.model=auto and null fixed orders")
        return

    if arma.p is None or arma.q is None:
        _invalid("manual selection requires explicit arma.p and arma.q")
    if variance.model == "auto":
        _invalid("manual selection requires an explicit variance.model")
    if variance.model == "constant_variance":
        valid = variance.arch_p is None and variance.garch_p is None and variance.garch_q is None
    elif variance.model == "arch":
        valid = variance.arch_p is not None and variance.garch_p is None and variance.garch_q is None
    else:
        valid = variance.arch_p is None and variance.garch_p is not None and variance.garch_q is not None
    if not valid:
        _invalid("manual variance orders do not match variance.model")


__all__ = [
    "ARCH_ORDER_LIMIT",
    "ARMA_GARCH_CONTRACT_VERSION",
    "ARMA_GARCH_PACK_ID",
    "AR_ORDER_LIMIT",
    "ArmaGarchAnalysisContract",
    "ArmaGarchContractError",
    "ArmaOptions",
    "GARCH_P_ORDER_LIMIT",
    "GARCH_Q_ORDER_LIMIT",
    "MA_ORDER_LIMIT",
    "VarianceOptions",
]
