"""A project's data-sharing policy and the record of what was sent."""

from __future__ import annotations

from typing import Literal, NotRequired

from pydantic import ConfigDict
from typing_extensions import TypedDict

from ...egress import ContentClass, SensitivityLevel


class ProviderAllowance(TypedDict):
    allow: list[ContentClass]


class EgressPolicyDocument(TypedDict):
    version: int
    providers: dict[str, ProviderAllowance]
    columns: dict[str, SensitivityLevel]


class EgressDefaults(TypedDict):
    remote: list[ContentClass]
    local: list[ContentClass]


class ActiveProviderEgress(TypedDict):
    provider_id: str
    provider_name: str
    locality: Literal["local", "remote"]
    allowed_classes: list[ContentClass]


class EgressPolicyView(TypedDict):
    project_root: str
    policy: EgressPolicyDocument
    policy_source: str
    content_classes: list[ContentClass]
    sensitivity_levels: list[SensitivityLevel]
    defaults: EgressDefaults
    active_provider: ActiveProviderEgress | None


class EgressDecision(TypedDict):
    index: int
    role: str
    content_class: ContentClass
    decision: str
    tool_id: NotRequired[str]
    redacted_columns: NotRequired[list[str]]
    withheld_protocols: NotRequired[list[str]]


class EgressAuditRecord(TypedDict):
    """One line of the project's egress audit log (JSONL written since
    v1.8.9; read back as stored, so the record is open)."""

    __pydantic_config__ = ConfigDict(extra="allow")  # type: ignore[misc]
    at: str
    project_root: str | None
    provider_id: str
    provider_host: str
    provider_locality: Literal["local", "remote"]
    model: str
    policy_source: str
    message_count: int
    withheld_count: int
    redacted_columns: list[str]
    payload_bytes: int
    payload_sha256: str
    decisions: list[EgressDecision]


class EgressAudit(TypedDict):
    project_root: str
    records: list[EgressAuditRecord]
