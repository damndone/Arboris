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


# These constrain how results may be DESCRIBED, so they travel with the results
# as well as with the contract. A live turn proved why: asked for a VaR figure,
# the model never fetched the operation contract -- a question is not a proposal
# -- so a prohibition living only there was never read, and it duly reported the
# 5% conditional quantile as 95% VaR.
LABELLING_INVARIANTS: tuple[str, ...] = (
    "Never call the lower conditional quantile a Value-at-Risk figure, and "
    "never state that the two are equivalent. It is a plug-in conditional "
    "quantile of the modelled series; VaR is a loss figure over a stated "
    "horizon and exposure that this pack does not compute.",
    "Never present the predictive interval as accounting for parameter "
    "uncertainty; it is plug-in and conditional.",
    "Never report a composite information criterion across the mean and "
    "variance stages of a sequential fit.",
    "Never describe a sequential two-stage fit as a joint likelihood.",
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
    spec: dict[str, Any] = {"path": path, "type": type_, "description": description}
    # Only the distinguishing flags are emitted. Spelling out three booleans on
    # every one of thirty-three fields is noise the model has to read past, and
    # it is what pushed this payload over the tool-output budget.
    if nullable:
        spec["nullable"] = True
    if required:
        spec["required"] = True
    if not agent_editable:
        spec["agent_editable"] = False
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
            description="Inherited; re-pointing the analysis at other data is not a rerun.",
        ),
        _field(
            "time_column",
            type_="string",
            required=True,
            description="Time index column; must exist in the dataset.",
        ),
        _field(
            "value_column",
            type_="string",
            required=True,
            description="Analysed series column; must exist in the dataset.",
        ),
        _field(
            "time_index_semantics",
            type_="string",
            required=True,
            enum=_choices(ArmaGarchAnalysisContract, "time_index_semantics"),
            description=(
                "What one step means. business_or_trading_observations: non-trading "
                "days are not observations, so durations stay in observation "
                "periods and are never converted to calendar days."
            ),
        ),
        _field(
            "transform",
            type_="string",
            required=True,
            enum=_choices(ArmaGarchAnalysisContract, "transform"),
            description="log_return_pct = 100*diff(log(value)); log forms need positive values.",
        ),
        _field(
            "transform_confirmed",
            type_="boolean",
            required=True,
            enum=_choices(ArmaGarchAnalysisContract, "transform_confirmed"),
            description="Must be true to execute; the transform is never implicit.",
        ),
        _field(
            "analysis_goal",
            type_="string",
            enum=_choices(ArmaGarchAnalysisContract, "analysis_goal"),
            description="Advisory only; does not change the estimator.",
        ),
        _field(
            "selection_mode",
            type_="string",
            enum=_choices(ArmaGarchAnalysisContract, "selection_mode"),
            description="auto searches orders; manual fixes them. See cross_field_rules.",
        ),
        _field(
            "arma.p",
            type_="integer",
            nullable=True,
            minimum=0,
            maximum=AR_ORDER_LIMIT,
            description="AR order. Null in auto mode, explicit in manual mode.",
        ),
        _field(
            "arma.q",
            type_="integer",
            nullable=True,
            minimum=0,
            maximum=MA_ORDER_LIMIT,
            description="MA order. Null in auto mode, explicit in manual mode.",
        ),
        _field(
            "arma.constant_mode",
            type_="string",
            enum=_choices(ArmaOptions, "constant_mode"),
            description="Constant in the mean equation.",
        ),
        _field(
            "arma.auto_max_p",
            type_="integer",
            minimum=0,
            maximum=AUTO_AR_ORDER_LIMIT,
            description="Auto-search AR cap.",
        ),
        _field(
            "arma.auto_max_q",
            type_="integer",
            minimum=0,
            maximum=AUTO_MA_ORDER_LIMIT,
            description="Auto-search MA cap.",
        ),
        _field(
            "arma.auto_max_total_order",
            type_="integer",
            minimum=0,
            maximum=AUTO_TOTAL_ORDER_LIMIT,
            description="Auto-search cap on p+q; bounds the candidate count.",
        ),
        _field(
            "variance.model",
            type_="string",
            enum=_choices(VarianceOptions, "model"),
            description="Volatility family. auto searches; others need matching orders.",
        ),
        _field(
            "variance.arch_p",
            type_="integer",
            nullable=True,
            minimum=1,
            maximum=ARCH_ORDER_LIMIT,
            description="Set only when variance.model is arch.",
        ),
        _field(
            "variance.garch_p",
            type_="integer",
            nullable=True,
            minimum=1,
            maximum=GARCH_P_ORDER_LIMIT,
            description="Set only when variance.model is garch.",
        ),
        _field(
            "variance.garch_q",
            type_="integer",
            nullable=True,
            minimum=1,
            maximum=GARCH_Q_ORDER_LIMIT,
            description="Set only when variance.model is garch.",
        ),
        _field(
            "variance.auto_arch_max_p",
            type_="integer",
            minimum=1,
            maximum=ARCH_ORDER_LIMIT,
            description="Auto volatility-search ARCH cap.",
        ),
        _field(
            "variance.include_garch_1_1",
            type_="boolean",
            description="Always include GARCH(1,1) in the auto volatility search.",
        ),
        _field(
            "estimation_strategy",
            type_="string",
            enum=_choices(ArmaGarchAnalysisContract, "estimation_strategy"),
            description=(
                "sequential fits the mean then volatility on its residuals; joint "
                "fits both together but requires arma.q = 0."
            ),
        ),
        _field(
            "innovation_distribution",
            type_="string",
            enum=_choices(ArmaGarchAnalysisContract, "innovation_distribution"),
            description="Innovation law for the volatility likelihood and intervals.",
        ),
        _field(
            "missing_value_policy",
            type_="string",
            enum=_choices(ArmaGarchAnalysisContract, "missing_value_policy"),
            description=(
                "block refuses to run on blanks; drop_missing_confirmed excludes "
                "those rows as non-observations. Exclusion is not interpolation, "
                "filling, or calendar padding - no value is ever invented."
            ),
        ),
        _field(
            "validation.method",
            type_="string",
            enum=_choices(ValidationOptions, "method"),
            description="Expanding-window one-step-ahead only.",
        ),
        _field(
            "validation.validation_n",
            type_="integer",
            nullable=True,
            minimum=1,
            description=(
                "Held-out observations at the end of the series. Frozen before "
                "candidate selection: an independent evaluation, not a tuning set."
            ),
        ),
        _field(
            "validation.refit_every",
            type_="integer",
            minimum=1,
            description="Refit cadence in observations along the rolling origin.",
        ),
        _field(
            "validation.selection_repeated_during_validation",
            type_="boolean",
            enum=[False],
            agent_editable=False,
            description="Forbidden: re-selecting inside validation leaks the held-out sample.",
        ),
        _field(
            "forecast.horizon",
            type_="integer",
            enum=list(get_args(get_type_hints(ForecastOptions)["horizon"])),
            agent_editable=False,
            description="One-step-ahead only.",
        ),
        _field(
            "forecast.interval_level",
            type_="number",
            description=(
                "Interval coverage, strictly in (0,1). Intervals are plug-in and "
                "exclude parameter uncertainty."
            ),
        ),
        _field(
            "forecast.lower_quantile",
            type_="number",
            description=(
                "Lower conditional quantile, strictly in (0,1). A conditional "
                "quantile, not a VaR figure."
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
            description="Server-owned; a patch may not change it.",
        ),
        _field(
            "contract_version",
            type_="string",
            agent_editable=False,
            description="Server-owned; a patch may not change it.",
        ),
    ]


def _cross_field_rules() -> list[dict[str, Any]]:
    """Rules whose violation examples are executed by the vocabulary tests."""

    return [
        {
            "rule_id": "auto_mode_forbids_fixed_orders",
            "requirement": (
                "selection_mode auto: arma.p/q null, variance.model auto, all "
                "fixed variance orders null."
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
                "selection_mode manual: arma.p/q explicit integers, variance.model "
                "not auto."
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
                "constant_variance takes no orders; arch takes arch_p only; garch "
                "takes garch_p and garch_q only."
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
                "joint requires arma.q = 0; use sequential to keep an MA term."
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
                "Auto-search caps are server limits: exceeding one is rejected, "
                "not clamped."
            ),
            "violation_code": "CANDIDATE_LIMIT_EXCEEDED",
            "violation_example": {
                "arma": {"auto_max_p": AUTO_AR_ORDER_LIMIT + 1},
            },
        },
    ]


def build_arma_garch_option_vocabulary() -> dict[str, Any]:
    """Publish the editable option surface of the frozen ARMA-GARCH contract.

    Deliberately lean: this travels inside a bounded tool response, and a
    vocabulary that overruns that budget is worth less than no vocabulary at
    all -- the Agent receives an error instead of the contract.
    """

    fields = _fields()
    return {
        "pack_id": ARMA_GARCH_PACK_ID,
        "contract_version": ARMA_GARCH_CONTRACT_VERSION,
        "patch_shape": (
            "changes.model_options is a one-level patch over the node's current "
            "contract; nested sections merge key-wise, so name only the keys you "
            "change. Never an old/new field diff. Field paths below are written "
            "in dotted form for reading, but a patch must nest them as objects: "
            "the dotted path is not a key. See patch_shape_example."
        ),
        # `fields[].path` advertises dotted paths such as `arma.p`, and a live
        # turn echoed that form straight back as a flat key. The first
        # propose_operation call failed, the model diagnosed it and recovered on
        # the retry -- but it paid a round trip every time. Showing the wrong
        # and right shape side by side costs a few bytes and removes the guess.
        "patch_shape_example": {
            "goal": "Set a manual ARMA(1,1) with no constant and a GARCH(1,1).",
            "wrong_flat_dotted_keys": {
                "arma.p": 1,
                "arma.q": 1,
                "arma.constant_mode": "exclude",
                "variance.model": "garch",
            },
            "correct_nested_objects": {
                "selection_mode": "manual",
                "arma": {"p": 1, "q": 1, "constant_mode": "exclude"},
                "variance": {"model": "garch", "garch_p": 1, "garch_q": 1},
            },
            "note": (
                "Sibling keys you do not name are preserved: patching "
                "{'arma': {'q': 2}} keeps the existing arma.p."
            ),
        },
        "fields": [item for item in fields if item.get("agent_editable") is not False],
        # Named, not described: the Agent only needs to know not to patch them.
        "server_owned_fields": [
            item["path"] for item in fields if item.get("agent_editable") is False
        ],
        "cross_field_rules": [
            {key: value for key, value in rule.items() if key != "violation_example"}
            for rule in _cross_field_rules()
        ],
        # Two different kinds of rule, kept apart on purpose. A live turn read
        # "Calling the lower conditional quantile a Value-at-Risk figure" as a
        # capability limit -- "we cannot compute VaR" -- and then helpfully
        # explained that the two are the same number, which is the claim the
        # pack exists to refuse. A thing you must not *say* is not a thing the
        # pack cannot *do*.
        "unsupported_requests": [
            "Multi-step forecasts (horizon is fixed at 1).",
            "Exogenous regressors, seasonal terms, custom likelihoods.",
            "Interpolating, filling, or calendar-padding missing observations.",
            "Re-selecting candidates inside the validation window.",
        ],
        "prohibited_claims": list(LABELLING_INVARIANTS),
    }


__all__ = ["LABELLING_INVARIANTS", "build_arma_garch_option_vocabulary"]
