"""The Agent-facing option vocabulary for the ARMA-GARCH pack.

`model.rerun` carries `model_options` as a generic object patch, which is the
right transport but tells a natural-language Agent nothing: it cannot know that
`arma.p` exists, that `variance.model` is a closed set, that `auto_max_p` is
capped at three, or that `selection_mode` couples several fields at once. Left
to guess, the Agent produces patches the frozen contract rejects.

This module publishes that vocabulary. Every enum is read out of the contract's
own `Literal` annotations and every limit is the contract's own constant, so the
vocabulary cannot drift away from the validator by editing one side only. The
cross-field rules carry executable violation examples for the same reason: a
rule that stopped being true would fail its test rather than quietly mislead.
"""

from __future__ import annotations

from typing import Any, Literal, get_args, get_origin, get_type_hints

from ...contracts.model.arma_garch import (
    ARCH_ORDER_LIMIT,
    ARMA_GARCH_CONTRACT_VERSION,
    ARMA_GARCH_PACK_ID,
    AR_ORDER_LIMIT,
    AUTO_AR_ORDER_LIMIT,
    AUTO_MA_ORDER_LIMIT,
    AUTO_TOTAL_ORDER_LIMIT,
    GARCH_P_ORDER_LIMIT,
    GARCH_Q_ORDER_LIMIT,
    MA_ORDER_LIMIT,
    ArmaGarchAnalysisContract,
    ArmaOptions,
    ForecastOptions,
    ValidationOptions,
    VarianceOptions,
)


def _choices(cls: type, field: str) -> list[Any]:
    """Read a field's closed value set from its own ``Literal`` annotation."""

    annotation = get_type_hints(cls)[field]
    if get_origin(annotation) is not Literal:
        raise TypeError(f"{cls.__name__}.{field} is not a Literal field")
    return list(get_args(annotation))


def _field(
    path: str,
    *,
    type_: str,
    description: str,
    enum: list[Any] | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
    nullable: bool = False,
    required: bool = False,
    agent_editable: bool = True,
) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "path": path,
        "type": type_,
        "nullable": nullable,
        "required": required,
        "agent_editable": agent_editable,
        "description": description,
    }
    if enum is not None:
        spec["enum"] = enum
    if minimum is not None:
        spec["minimum"] = minimum
    if maximum is not None:
        spec["maximum"] = maximum
    return spec


def _fields() -> list[dict[str, Any]]:
    return [
        _field(
            "dataset_ref",
            type_="string",
            required=True,
            agent_editable=False,
            description=(
                "Identifies the analysed dataset. Changing it would silently "
                "re-point the analysis at other data, so it is inherited."
            ),
        ),
        _field(
            "time_column",
            type_="string",
            required=True,
            description="Column supplying the time index. Must exist in the dataset.",
        ),
        _field(
            "value_column",
            type_="string",
            required=True,
            description="Column supplying the analysed series. Must exist in the dataset.",
        ),
        _field(
            "time_index_semantics",
            type_="string",
            required=True,
            enum=_choices(ArmaGarchAnalysisContract, "time_index_semantics"),
            description=(
                "How one step of the index is interpreted. "
                "`business_or_trading_observations` means non-trading days are not "
                "observations, so durations stay in observation periods and are "
                "never converted to calendar days."
            ),
        ),
        _field(
            "transform",
            type_="string",
            required=True,
            enum=_choices(ArmaGarchAnalysisContract, "transform"),
            description=(
                "Series transform. `log_return_pct` is 100*diff(log(value)) and "
                "requires strictly positive values."
            ),
        ),
        _field(
            "transform_confirmed",
            type_="boolean",
            required=True,
            enum=_choices(ArmaGarchAnalysisContract, "transform_confirmed"),
            description=(
                "The transform is never chosen implicitly; execution requires an "
                "explicit true here."
            ),
        ),
        _field(
            "analysis_goal",
            type_="string",
            enum=_choices(ArmaGarchAnalysisContract, "analysis_goal"),
            description="Advisory framing of the analysis; does not change the estimator.",
        ),
        _field(
            "selection_mode",
            type_="string",
            enum=_choices(ArmaGarchAnalysisContract, "selection_mode"),
            description=(
                "`auto` searches orders under the auto caps; `manual` fixes them. "
                "The two modes require different companion fields - see "
                "cross_field_rules."
            ),
        ),
        _field(
            "arma.p",
            type_="integer",
            nullable=True,
            minimum=0,
            maximum=AR_ORDER_LIMIT,
            description="Fixed AR order. Null in auto mode, explicit in manual mode.",
        ),
        _field(
            "arma.q",
            type_="integer",
            nullable=True,
            minimum=0,
            maximum=MA_ORDER_LIMIT,
            description="Fixed MA order. Null in auto mode, explicit in manual mode.",
        ),
        _field(
            "arma.constant_mode",
            type_="string",
            enum=_choices(ArmaOptions, "constant_mode"),
            description="Whether the mean equation carries a constant.",
        ),
        _field(
            "arma.auto_max_p",
            type_="integer",
            minimum=0,
            maximum=AUTO_AR_ORDER_LIMIT,
            description="Largest AR order the auto search may try.",
        ),
        _field(
            "arma.auto_max_q",
            type_="integer",
            minimum=0,
            maximum=AUTO_MA_ORDER_LIMIT,
            description="Largest MA order the auto search may try.",
        ),
        _field(
            "arma.auto_max_total_order",
            type_="integer",
            minimum=0,
            maximum=AUTO_TOTAL_ORDER_LIMIT,
            description="Largest p+q the auto search may try; bounds the candidate count.",
        ),
        _field(
            "variance.model",
            type_="string",
            enum=_choices(VarianceOptions, "model"),
            description=(
                "Volatility family. `auto` searches; the others fix the family and "
                "require the matching order fields."
            ),
        ),
        _field(
            "variance.arch_p",
            type_="integer",
            nullable=True,
            minimum=1,
            maximum=ARCH_ORDER_LIMIT,
            description="ARCH order. Set only when variance.model is `arch`.",
        ),
        _field(
            "variance.garch_p",
            type_="integer",
            nullable=True,
            minimum=1,
            maximum=GARCH_P_ORDER_LIMIT,
            description="GARCH lag order. Set only when variance.model is `garch`.",
        ),
        _field(
            "variance.garch_q",
            type_="integer",
            nullable=True,
            minimum=1,
            maximum=GARCH_Q_ORDER_LIMIT,
            description="GARCH ARCH-term order. Set only when variance.model is `garch`.",
        ),
        _field(
            "variance.auto_arch_max_p",
            type_="integer",
            minimum=1,
            maximum=ARCH_ORDER_LIMIT,
            description="Largest ARCH order the auto volatility search may try.",
        ),
        _field(
            "variance.include_garch_1_1",
            type_="boolean",
            description="Whether the auto volatility search always includes GARCH(1,1).",
        ),
        _field(
            "estimation_strategy",
            type_="string",
            enum=_choices(ArmaGarchAnalysisContract, "estimation_strategy"),
            description=(
                "`sequential` fits the mean, then the volatility on its residuals. "
                "`joint` estimates both together but is only available when "
                "arma.q is zero."
            ),
        ),
        _field(
            "innovation_distribution",
            type_="string",
            enum=_choices(ArmaGarchAnalysisContract, "innovation_distribution"),
            description="Innovation law used by the volatility likelihood and intervals.",
        ),
        _field(
            "missing_value_policy",
            type_="string",
            enum=_choices(ArmaGarchAnalysisContract, "missing_value_policy"),
            description=(
                "`block` refuses to run when the value column has blanks. "
                "`drop_missing_confirmed` excludes those rows as non-observations. "
                "Exclusion is not interpolation, filling, or calendar padding - no "
                "value is ever invented."
            ),
        ),
        _field(
            "validation.method",
            type_="string",
            enum=_choices(ValidationOptions, "method"),
            description="Only expanding-window one-step-ahead validation exists in v1.8.",
        ),
        _field(
            "validation.validation_n",
            type_="integer",
            nullable=True,
            minimum=1,
            description=(
                "Number of held-out observations at the end of the series. The split "
                "is frozen before candidate selection, so this is an independent "
                "evaluation, not a tuning set."
            ),
        ),
        _field(
            "validation.refit_every",
            type_="integer",
            minimum=1,
            description="Refit cadence, in observations, along the rolling origin.",
        ),
        _field(
            "validation.selection_repeated_during_validation",
            type_="boolean",
            enum=[False],
            agent_editable=False,
            description=(
                "Re-selecting inside validation would leak the held-out sample; "
                "v1.8 forbids it."
            ),
        ),
        _field(
            "forecast.horizon",
            type_="integer",
            enum=list(get_args(get_type_hints(ForecastOptions)["horizon"])),
            agent_editable=False,
            description="v1.8 produces one-step-ahead forecasts only.",
        ),
        _field(
            "forecast.interval_level",
            type_="number",
            description=(
                "Coverage of the conditional predictive interval, strictly between "
                "zero and one. Intervals are plug-in and exclude parameter uncertainty."
            ),
        ),
        _field(
            "forecast.lower_quantile",
            type_="number",
            description=(
                "Lower conditional quantile reported alongside the interval, strictly "
                "between zero and one. It is a conditional quantile, not a VaR figure."
            ),
        ),
        _field(
            "random_seed",
            type_="integer",
            minimum=0,
            description="Seed for the reproducible parts of the search.",
        ),
        _field(
            "pack_id",
            type_="string",
            agent_editable=False,
            description="Server-owned pack identity; a patch may not change it.",
        ),
        _field(
            "contract_version",
            type_="string",
            agent_editable=False,
            description="Server-owned contract version; a patch may not change it.",
        ),
    ]


def _cross_field_rules() -> list[dict[str, Any]]:
    """Rules whose violation examples are executed by the vocabulary tests."""

    return [
        {
            "rule_id": "auto_mode_forbids_fixed_orders",
            "requirement": (
                "When selection_mode is `auto`, arma.p and arma.q must be null, "
                "variance.model must be `auto`, and every fixed variance order must "
                "be null."
            ),
            "violation_code": "INVALID_ORDER",
            "violation_example": {
                "selection_mode": "auto",
                "arma": {"p": 1, "q": 1},
            },
        },
        {
            "rule_id": "manual_mode_requires_explicit_orders",
            "requirement": (
                "When selection_mode is `manual`, arma.p and arma.q must be explicit "
                "integers and variance.model must not be `auto`."
            ),
            "violation_code": "INVALID_ORDER",
            "violation_example": {
                "selection_mode": "manual",
                "arma": {"p": None, "q": None},
            },
        },
        {
            "rule_id": "manual_variance_orders_match_family",
            "requirement": (
                "`constant_variance` takes no orders, `arch` takes arch_p only, and "
                "`garch` takes garch_p and garch_q only."
            ),
            "violation_code": "INVALID_ORDER",
            "violation_example": {
                "selection_mode": "manual",
                "arma": {"p": 1, "q": 0},
                "variance": {"model": "garch", "arch_p": 1, "garch_p": None, "garch_q": None},
            },
        },
        {
            "rule_id": "joint_estimation_excludes_ma_terms",
            "requirement": (
                "estimation_strategy `joint` requires arma.q to be zero. Use "
                "`sequential` to keep an MA term."
            ),
            "violation_code": "UNSUPPORTED_JOINT_ARMA_GARCH",
            "violation_example": {
                "selection_mode": "manual",
                "estimation_strategy": "joint",
                "arma": {"p": 1, "q": 1},
                "variance": {"model": "garch", "arch_p": None, "garch_p": 1, "garch_q": 1},
            },
        },
        {
            "rule_id": "transform_must_be_confirmed",
            "requirement": "transform_confirmed must be true before execution.",
            "violation_code": "INVALID_ORDER",
            "violation_example": {"transform_confirmed": False},
        },
        {
            "rule_id": "auto_search_caps_are_hard",
            "requirement": (
                "The auto-search caps are server limits, not preferences; exceeding "
                "one is rejected rather than clamped."
            ),
            "violation_code": "CANDIDATE_LIMIT_EXCEEDED",
            "violation_example": {
                "arma": {"auto_max_p": AUTO_AR_ORDER_LIMIT + 1},
            },
        },
    ]


def build_arma_garch_option_vocabulary() -> dict[str, Any]:
    """Publish the editable option surface of the frozen ARMA-GARCH contract."""

    return {
        "pack_id": ARMA_GARCH_PACK_ID,
        "contract_version": ARMA_GARCH_CONTRACT_VERSION,
        "patch_shape": (
            "model.rerun changes.model_options is a one-level patch over the node's "
            "current analysis contract. Nested sections (arma, variance, validation, "
            "forecast) are merged key-wise, so a patch may name only the keys it "
            "changes. It is never an old/new field diff."
        ),
        "fields": _fields(),
        "cross_field_rules": _cross_field_rules(),
        "unsupported_requests": [
            "Multi-step or multi-horizon forecasts; the horizon is fixed at one.",
            "Exogenous regressors, seasonal terms, or a custom likelihood.",
            "Interpolating, filling, or calendar-padding missing observations.",
            "Reporting the lower conditional quantile as a Value-at-Risk figure.",
            "Re-running candidate selection inside the validation window.",
        ],
    }


__all__ = ["build_arma_garch_option_vocabulary"]
