"""Server status, capabilities and host appearance."""

from __future__ import annotations

from typing import Any, Literal, NotRequired

from typing_extensions import TypedDict

from .common import JsonSchema


class CapabilityFactoryStatus(TypedDict):
    configured: bool
    catalog_configured: bool
    execution_gateway_configured: bool
    dependency_gate_configured: bool
    authority_id: NotRequired[str]


class Health(TypedDict):
    status: Literal["ok"]
    control_plane_mode: str
    workers: int
    execution_profile: str
    lmm_admitted: bool
    high_risk_code_admitted: bool
    canary_status: str
    capability_factory: CapabilityFactoryStatus


ModelGroup = Literal[
    "auto", "Linear", "Binary", "Count", "Panel", "GLM", "IV", "DID", "ANOVA",
    "Time Series", "Ordinal", "Nominal", "Survival", "Quantile",
]


class ControlOption(TypedDict):
    value: Any
    label: str


ControlKind = Literal[
    "select", "multiselect", "column", "columns", "text", "integer", "number", "toggle", "object", "json",
]
"""Every control kind the backend emits. Producers (capabilities, operation
contracts, draft materialization, the Genesis selector) do not share one
definition yet; the strict response contracts make this the registry: a new
kind fails the suite until it is declared here."""


class EditableControlSpec(TypedDict):
    key: str
    kind: ControlKind
    label: str
    role: NotRequired[str]
    required: NotRequired[bool]
    value: NotRequired[Any]
    options: NotRequired[list[str | ControlOption]]
    evaluation_modes: NotRequired[list[str]]
    schema: NotRequired[JsonSchema]


class ModelTypeEntry(TypedDict):
    key: str
    label: str
    group: ModelGroup
    description: str
    schema_id: NotRequired[str]
    params: NotRequired[list[EditableControlSpec]]
    requires: NotRequired[list[str]]


class KeyedEntry(TypedDict):
    key: str
    label: str
    description: str


class SamplingMethodEntry(TypedDict):
    key: str
    label: str


class CovarianceOption(TypedDict):
    key: str
    label: str
    default: NotRequired[bool]


class SurveyDesignCapability(TypedDict):
    variance_methods: list[str]
    variance_method_requirements: dict[str, list[str]]
    replicate_types: list[str]
    lonely_psu_policies: list[str]
    df_conventions: list[str]
    design_fields: list[str]
    sampling_weight_families: list[str]


class Capabilities(TypedDict):
    schema_version: int
    editable_stages: list[str]
    model_types: list[ModelTypeEntry]
    imputation_methods: list[KeyedEntry]
    prediction_models: list[KeyedEntry]
    sampling_methods: list[SamplingMethodEntry]
    covariance_options: list[CovarianceOption]
    survey_design: SurveyDesignCapability


class SystemAppearance(TypedDict):
    theme: Literal["dark", "light"] | None
    source: Literal["darwin-native", "browser"]
