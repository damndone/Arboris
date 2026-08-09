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
JOURNAL_FULL_REPORT_STANDARD = "journal_full_v1"


class ReportContractError(ValueError):
    """A report packet or provider response crossed a bounded contract."""

    def __init__(self, message: str, *, violations: list[str] | None = None) -> None:
        super().__init__(message)
        self.violations = tuple(violations or [message])


@dataclass(frozen=True)
class ReportPacketContract:
    fact_ids: frozenset[str]
    figure_ids: frozenset[str]
    figure_order: tuple[str, ...] = ()
    report_standard: str | None = None
    required_capabilities: tuple[str, ...] = ()
    excluded_fact_ids: frozenset[str] = frozenset()
    capability_manifest: tuple[dict[str, Any], ...] = ()


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

    report_standard = packet.get("report_standard")
    if report_standard is not None and report_standard != JOURNAL_FULL_REPORT_STANDARD:
        raise ReportContractError(
            f"unsupported report_standard {report_standard!r}; "
            f"expected {JOURNAL_FULL_REPORT_STANDARD!r}"
        )

    required_capabilities = _validate_id_list(
        packet.get("required_capabilities", []),
        field_name="required capability",
    )
    excluded_fact_ids = _validate_id_list(
        packet.get("excluded_fact_ids", []),
        field_name="excluded fact id",
    )
    capability_manifest = _validate_capability_manifest(
        packet.get("capability_manifest", []),
        required_capabilities,
    )

    return ReportPacketContract(
        fact_ids=frozenset(fact_ids),
        figure_ids=frozenset(figure_ids),
        figure_order=tuple(figure_ids),
        report_standard=report_standard,
        required_capabilities=required_capabilities,
        excluded_fact_ids=frozenset(excluded_fact_ids),
        capability_manifest=capability_manifest,
    )


def validate_report_response(
    text: str,
    contract: ReportPacketContract,
    *,
    require_figure_markers: bool = True,
) -> str:
    """Return a safe response or raise instead of silently repairing it.

    Numeric shorthand such as ``[[c:5]]`` is accepted only when the packet
    contains the unambiguous fact id ``c5``. In the normal final-response
    phase, figure markers must contain every supplied artifact exactly once.
    The provider narrative phase sets ``require_figure_markers=False``: any
    provider-emitted figure marker is then rejected, and the server can bind
    the packet-owned markers deterministically afterward.
    """

    if not isinstance(text, str) or not text.strip():
        raise ReportContractError("report response is empty")

    normalized = _normalize_numeric_citations(text, contract.fact_ids)
    violations: list[str] = []
    violations.extend(
        _citation_violations(
            normalized,
            contract.fact_ids,
            contract.excluded_fact_ids,
        )
    )
    if require_figure_markers:
        violations.extend(_figure_violations(normalized, contract.figure_ids))
    else:
        violations.extend(_provider_figure_violations(normalized))
    if violations:
        raise ReportContractError("; ".join(violations), violations=violations)
    return normalized


def validate_report_narrative_response(
    text: str,
    contract: ReportPacketContract,
) -> str:
    """Validate provider prose before Workbench binds packet-owned figures."""

    return validate_report_response(
        text,
        contract,
        require_figure_markers=False,
    )


def bind_report_figures(text: str, contract: ReportPacketContract) -> str:
    """Append packet-owned figure markers in declaration order and revalidate."""

    normalized = validate_report_narrative_response(text, contract).rstrip()
    figure_order = contract.figure_order or tuple(sorted(contract.figure_ids))
    if figure_order:
        normalized = normalized + "\n\n" + "\n".join(
            f"[[fig:{artifact_id}]]" for artifact_id in figure_order
        )
    return validate_report_response(normalized, contract)


def _normalize_numeric_citations(text: str, fact_ids: frozenset[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        raw_id = match.group(1)
        if raw_id.isdigit() and f"c{raw_id}" in fact_ids:
            return f"[[c:c{raw_id}]]"
        return match.group(0)

    return _CITE_MARKER.sub(replace, text)


def _validate_id_list(value: Any, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ReportContractError(f"{field_name}s must be a list")
    values: list[str] = []
    for item in value:
        if not isinstance(item, str) or not _SAFE_ID.fullmatch(item):
            raise ReportContractError(f"{field_name} must be a safe non-empty id")
        values.append(item)
    if len(values) != len(set(values)):
        raise ReportContractError(f"duplicate {field_name}")
    return tuple(values)


def _validate_capability_manifest(
    value: Any,
    required_capabilities: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        raise ReportContractError("capability_manifest must be a list")
    entries: list[dict[str, Any]] = []
    capability_ids: list[str] = []
    for entry in value:
        if not isinstance(entry, dict):
            raise ReportContractError("each capability manifest entry must be an object")
        unknown = set(entry) - {
            "capability_id",
            "provider_id",
            "availability",
            "validation_level",
            "report_modules",
            "limitations",
        }
        if unknown:
            raise ReportContractError(
                "unknown capability manifest fields: " + ", ".join(sorted(unknown))
            )
        capability_id = entry.get("capability_id")
        provider_id = entry.get("provider_id")
        if not isinstance(capability_id, str) or not _SAFE_ID.fullmatch(capability_id):
            raise ReportContractError("capability manifest capability_id must be a safe id")
        if not isinstance(provider_id, str) or not _SAFE_ID.fullmatch(provider_id):
            raise ReportContractError("capability manifest provider_id must be a safe id")
        availability = entry.get("availability", "available")
        if availability not in {"available", "unavailable", "not_applicable"}:
            raise ReportContractError("capability manifest availability is invalid")
        validation_level = entry.get("validation_level", "internal_only")
        if validation_level not in {"external_oracle", "internal_only", "unverified"}:
            raise ReportContractError("capability manifest validation_level is invalid")
        report_modules = entry.get("report_modules", [])
        if not isinstance(report_modules, list) or not all(
            isinstance(module, str) and _SAFE_ID.fullmatch(module)
            for module in report_modules
        ):
            raise ReportContractError("capability manifest report_modules must be safe ids")
        limitations = entry.get("limitations", [])
        if not isinstance(limitations, list) or not all(
            isinstance(limitation, str) and limitation.strip()
            for limitation in limitations
        ):
            raise ReportContractError("capability manifest limitations must be non-empty strings")
        if capability_id in capability_ids:
            raise ReportContractError("duplicate capability manifest capability_id")
        capability_ids.append(capability_id)
        entries.append(
            {
                "capability_id": capability_id,
                "provider_id": provider_id,
                "availability": availability,
                "validation_level": validation_level,
                "report_modules": list(report_modules),
                "limitations": list(limitations),
            }
        )
    missing = sorted(set(required_capabilities) - set(capability_ids))
    if value and missing:
        raise ReportContractError(
            "capability manifest is missing required capabilities: " + ", ".join(missing)
        )
    return tuple(entries)


def _citation_violations(
    text: str,
    fact_ids: frozenset[str],
    excluded_fact_ids: frozenset[str] = frozenset(),
) -> list[str]:
    violations: list[str] = []
    cited_ids = [match.group(1) for match in _CITE_MARKER.finditer(text)]
    for fact_id in cited_ids:
        if fact_id in excluded_fact_ids:
            violations.append(f"excluded fact {fact_id}")
        elif fact_id not in fact_ids:
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
    for artifact_id in sorted(figure_ids):
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


def _provider_figure_violations(text: str) -> list[str]:
    """Reject all provider figure markers before server-owned binding."""

    if "[[fig:" not in text:
        return []
    marker_ids = [match.group(1) for match in _FIGURE_MARKER.finditer(text)]
    violations = [
        f"provider figure marker {artifact_id} is not allowed"
        for artifact_id in marker_ids
    ]
    if not marker_ids:
        violations.append("malformed figure marker")
    return _unique(violations)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


__all__ = [
    "JOURNAL_FULL_REPORT_STANDARD",
    "ReportContractError",
    "ReportPacketContract",
    "bind_report_figures",
    "validate_report_packet",
    "validate_report_narrative_response",
    "validate_report_response",
]
