"""Structured diagnostics and failures for the v1.8.1 ETS Model Pack."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from workbench.contracts.common.envelope import ContractError, freeze_json, thaw_json


Severity = Literal["blocking", "warning", "information"]


@dataclass(frozen=True)
class ETSDiagnostic:
    """One normalized, JSON-safe statement about an ETS estimation attempt."""

    severity: Severity
    code: str
    message: str
    evidence: Mapping[str, object]
    impact: str
    recommended_actions: tuple[Mapping[str, object], ...] = ()

    def __post_init__(self) -> None:
        if self.severity not in {"blocking", "warning", "information"}:
            raise ContractError("diagnostic severity is not declared")
        for field_name in ("code", "message", "impact"):
            value = getattr(self, field_name)
            if type(value) is not str or not value:
                raise ContractError(f"diagnostic {field_name} must be a non-empty string")
        evidence = freeze_json(self.evidence, "diagnostic.evidence")
        actions = freeze_json(self.recommended_actions, "diagnostic.recommended_actions")
        assert isinstance(evidence, Mapping)
        assert isinstance(actions, tuple)
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(self, "recommended_actions", actions)

    def to_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "evidence": thaw_json(self.evidence),
            "impact": self.impact,
            "recommended_actions": thaw_json(self.recommended_actions),
        }


class ETSInputError(ValueError):
    """Raised when a blocking diagnostic prevents an ETS estimation."""

    def __init__(self, diagnostic_: ETSDiagnostic) -> None:
        if diagnostic_.severity != "blocking":
            raise ValueError("ETSInputError requires a blocking diagnostic")
        self.diagnostic = diagnostic_
        self.code = diagnostic_.code
        self.evidence = diagnostic_.evidence
        self.impact = diagnostic_.impact
        self.recommended_actions = diagnostic_.recommended_actions
        super().__init__(f"{diagnostic_.code}: {diagnostic_.message}")

    def to_dict(self) -> dict[str, object]:
        return self.diagnostic.to_dict()


class ETSEstimationError(ETSInputError):
    """Raised when the optimizer result is not safe to report as numbers."""


def diagnostic(
    code: str,
    message: str,
    *,
    evidence: Mapping[str, object],
    impact: str,
    severity: Severity = "blocking",
    recommended_actions: Sequence[Mapping[str, object]] = (),
) -> ETSDiagnostic:
    return ETSDiagnostic(
        severity=severity,
        code=code,
        message=message,
        evidence=evidence,
        impact=impact,
        recommended_actions=tuple(recommended_actions),
    )


__all__ = [
    "ETSDiagnostic",
    "ETSEstimationError",
    "ETSInputError",
    "diagnostic",
]
