"""Deterministic contract for the LLM-authored report surface.

The provider may write prose, but it does not own the report's evidence
boundary. Facts and figures are supplied by Workbench and the response is
accepted only when its citation and figure markers refer to that packet.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_CITE_MARKER = re.compile(r"\[\[c:([^\]]+)\]\]")
_FIGURE_MARKER = re.compile(r"\[\[fig:([A-Za-z0-9._-]+)\]\]")


class ReportContractError(ValueError):
    """A report packet or provider response crossed a bounded contract."""

    def __init__(self, message: str, *, violations: list[str] | None = None) -> None:
        super().__init__(message)
        self.violations = tuple(violations or [message])


@dataclass(frozen=True)
class ReportPacketContract:
    fact_ids: frozenset[str]
    figure_ids: frozenset[str]


def validate_report_packet(packet: dict[str, Any]) -> ReportPacketContract:
    """Validate the IDs that the model is allowed to cite or embed."""

    if not isinstance(packet, dict):
        raise ReportContractError("report packet must be an object")

    fact_table = packet.get("fact_table")
    if not isinstance(fact_table, list):
        raise ReportContractError("fact_table must be a list")
    fact_ids: list[str] = []
    for fact in fact_table:
        if not isinstance(fact, dict):
            raise ReportContractError("each fact must be an object")
        fact_id = fact.get("id")
        if not isinstance(fact_id, str) or not _SAFE_ID.fullmatch(fact_id):
            raise ReportContractError("fact id must be a safe non-empty id")
        fact_ids.append(fact_id)
    if len(fact_ids) != len(set(fact_ids)):
        raise ReportContractError("duplicate fact id")

    figures = packet.get("figures", [])
    if not isinstance(figures, list):
        raise ReportContractError("figures must be a list")
    figure_ids: list[str] = []
    for figure in figures:
        if not isinstance(figure, dict):
            raise ReportContractError("each figure must be an object")
        artifact_id = figure.get("artifact_id")
        if not isinstance(artifact_id, str) or not _SAFE_ID.fullmatch(artifact_id):
            raise ReportContractError("figure artifact_id must be a safe non-empty id")
        figure_ids.append(artifact_id)
    if len(figure_ids) != len(set(figure_ids)):
        raise ReportContractError("duplicate figure artifact_id")

    return ReportPacketContract(
        fact_ids=frozenset(fact_ids),
        figure_ids=frozenset(figure_ids),
    )


def validate_report_response(
    text: str,
    contract: ReportPacketContract,
) -> str:
    """Return a safe response or raise instead of silently repairing it.

    Numeric shorthand such as ``[[c:5]]`` is accepted only when the packet
    contains the unambiguous fact id ``c5``. Figure markers must contain every
    supplied artifact exactly once.
    """

    if not isinstance(text, str) or not text.strip():
        raise ReportContractError("report response is empty")

    normalized = _normalize_numeric_citations(text, contract.fact_ids)
    violations: list[str] = []
    violations.extend(_citation_violations(normalized, contract.fact_ids))
    violations.extend(_figure_violations(normalized, contract.figure_ids))
    if violations:
        raise ReportContractError("; ".join(violations), violations=violations)
    return normalized


def _normalize_numeric_citations(text: str, fact_ids: frozenset[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        raw_id = match.group(1)
        if raw_id.isdigit() and f"c{raw_id}" in fact_ids:
            return f"[[c:c{raw_id}]]"
        return match.group(0)

    return _CITE_MARKER.sub(replace, text)


def _citation_violations(text: str, fact_ids: frozenset[str]) -> list[str]:
    violations: list[str] = []
    cited_ids = [match.group(1) for match in _CITE_MARKER.finditer(text)]
    for fact_id in cited_ids:
        if fact_id not in fact_ids:
            violations.append(f"unknown citation {fact_id}")
    if "[[c:" in text:
        covered = {match.span() for match in _CITE_MARKER.finditer(text)}
        cursor = 0
        while True:
            start = text.find("[[c:", cursor)
            if start < 0:
                break
            if not any(span[0] == start for span in covered):
                violations.append("malformed citation marker")
                break
            cursor = start + 4
    return _unique(violations)


def _figure_violations(text: str, figure_ids: frozenset[str]) -> list[str]:
    violations: list[str] = []
    marker_ids = [match.group(1) for match in _FIGURE_MARKER.finditer(text)]
    for artifact_id in marker_ids:
        if artifact_id not in figure_ids:
            violations.append(f"unknown figure marker {artifact_id}")
    for artifact_id in figure_ids:
        count = marker_ids.count(artifact_id)
        if count == 0:
            violations.append(f"missing figure marker {artifact_id}")
        elif count > 1:
            violations.append(f"duplicate figure marker {artifact_id}")
    if "[[fig:" in text:
        covered = {match.span() for match in _FIGURE_MARKER.finditer(text)}
        cursor = 0
        while True:
            start = text.find("[[fig:", cursor)
            if start < 0:
                break
            if not any(span[0] == start for span in covered):
                violations.append("malformed figure marker")
                break
            cursor = start + 6
    return _unique(violations)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


__all__ = [
    "ReportContractError",
    "ReportPacketContract",
    "validate_report_packet",
    "validate_report_response",
]
