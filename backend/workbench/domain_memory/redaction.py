"""Create non-expandable, bounded summary metadata for memory provenance."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from ..custom_capability.canonical import domain_digest
from .contracts import DomainMemoryContractError, _digest, _identifier, _text


class DomainMemoryRedactionError(DomainMemoryContractError):
    """A summary cannot be safely admitted to a memory provenance snapshot."""


_SENSITIVE = re.compile(
    r"(?:/Users/|/private/|/tmp/|[A-Za-z]:\\|\\\\|\b(?:row[_ -]?id|artifact[_ -]?ref|trace[_ -]?payload|api[_ -]?key|secret|token)\b|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b|\b\d{9,}\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class RedactedSummarySnapshot:
    summary_snapshot_ref: str
    summary_snapshot_hash: str
    summary_schema_version: str
    redaction_assessment_ref: str
    redaction_subject_hash: str
    source_ref: str
    source_kind: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "summary_snapshot_ref", _identifier(self.summary_snapshot_ref, "summary_snapshot_ref"))
        object.__setattr__(self, "summary_snapshot_hash", _digest(self.summary_snapshot_hash, "summary_snapshot_hash"))
        object.__setattr__(self, "summary_schema_version", _identifier(self.summary_schema_version, "summary_schema_version"))
        object.__setattr__(self, "redaction_assessment_ref", _identifier(self.redaction_assessment_ref, "redaction_assessment_ref"))
        object.__setattr__(self, "redaction_subject_hash", _digest(self.redaction_subject_hash, "redaction_subject_hash"))
        object.__setattr__(self, "source_ref", _identifier(self.source_ref, "source_ref"))
        object.__setattr__(self, "source_kind", _identifier(self.source_kind, "source_kind"))


def build_redacted_summary_snapshot(
    *, summary_text: str, source_ref: str, source_kind: str, redaction_subject: str, schema_version: str = "redacted-summary-v1"
) -> RedactedSummarySnapshot:
    try:
        text = _text(summary_text, "summary_text", maximum=1024, unsafe=True)
    except DomainMemoryContractError as error:
        raise DomainMemoryRedactionError(str(error)) from error
    if _SENSITIVE.search(text):
        raise DomainMemoryRedactionError("summary contains a raw, identifying, or secret-like reference")
    source = _identifier(source_ref, "source_ref")
    kind = _identifier(source_kind, "source_kind")
    subject = _text(redaction_subject, "redaction_subject", maximum=256, unsafe=True)
    summary_hash = domain_digest("workbench.domain-memory.redacted-summary/v1", {"schema": schema_version, "summary": text})
    subject_hash = domain_digest("workbench.domain-memory.redaction-subject/v1", subject)
    assessment_ref = "redaction-" + domain_digest("workbench.domain-memory.redaction-assessment/v1", {"summary_hash": summary_hash, "subject_hash": subject_hash})[:40]
    snapshot_ref = "snapshot-" + summary_hash[:40]
    return RedactedSummarySnapshot(
        summary_snapshot_ref=snapshot_ref,
        summary_snapshot_hash=summary_hash,
        summary_schema_version=schema_version,
        redaction_assessment_ref=assessment_ref,
        redaction_subject_hash=subject_hash,
        source_ref=source,
        source_kind=kind,
    )


__all__ = ["DomainMemoryRedactionError", "RedactedSummarySnapshot", "build_redacted_summary_snapshot"]
