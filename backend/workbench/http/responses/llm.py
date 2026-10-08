"""LLM provider settings and report-writing chat."""

from __future__ import annotations

from typing import Literal, NotRequired

from typing_extensions import TypedDict

from ...llm.config import ConfigSource
from ...llm.provider_store import ModelRecord
from ...report_quality import ReportQualityStatus
from .common import view_of

ProviderModel = view_of(ModelRecord, "ProviderModel")


class LlmConfig(TypedDict):
    configured: bool
    base_url: str | None
    model: str | None
    key_present: bool
    timeout_s: float
    provider_id: str | None
    provider_name: str | None
    source: ConfigSource
    context_window_tokens: int | None
    supports_1m: bool
    supports_vision: bool


class PublicProvider(TypedDict):
    """A provider as the API shows it: never its key, only whether one is set."""

    id: str
    name: str
    icon: str
    notes: str
    website_url: str | None
    base_url: str | None
    model: str
    timeout_s: float
    models: list[ProviderModel]
    key_present: bool


class ProviderList(TypedDict):
    active_provider_id: str | None
    providers: list[PublicProvider]


class DiscoveredModels(TypedDict):
    models: list[ProviderModel]
    message: str


class ReportQualityViolation(TypedDict):
    code: str
    message: str
    subject: NotRequired[str]


class ReportQuality(TypedDict):
    status: ReportQualityStatus
    violations: list[ReportQualityViolation]
    missing_sections: list[str]
    missing_capabilities: list[str]
    missing_evidence: list[str]
    missing_abstract_elements: list[str]
    unavailable_capabilities: list[str]
    results_subsection_count: int
    cited_fact_ids: list[str]
    figure_counts: dict[str, int]


class ChatReply(TypedDict):
    text: str
    model: str
    context_fingerprint: str | None
    report_quality: NotRequired[ReportQuality]
