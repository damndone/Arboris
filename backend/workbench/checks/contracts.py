"""What a check declares and what it returns (v1.8.10 design §4.1).

A check states which traits it needs, how much of the data it looks at (its
blinding level), its thresholds with their sources, and a budget. Its result
has one of six statuses, the numbers behind it, where the judgement came from,
and at most a proposed remedy -- never an action taken.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

STATUSES = ("holds", "caution", "fails", "not_applicable", "needs_reason", "not_checked")
#: design: regressors, instruments and roles only; outcome_distribution: the
#: outcome on its own; pre_period: the outcome before treatment; post_fit: the
#: fitted relationship. Only the first three may inform the choice of a
#: specification (§4.3).
BLINDING_LEVELS = ("design", "outcome_distribution", "pre_period", "post_fit")
SOURCES = ("computed", "judgment", "user_reason")


@dataclass(frozen=True)
class Threshold:
    name: str
    value: float
    meaning: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value, "meaning": self.meaning, "source": self.source}


@dataclass(frozen=True)
class CheckOutcome:
    status: str
    summary: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    remedy: str | None = None

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown check status {self.status!r}")


@dataclass(frozen=True)
class CheckSpec:
    check_id: str
    title: str
    #: Traits (of the family or of this fit) the check needs; the only rule of
    #: applicability is requires <= traits.
    requires: frozenset[str]
    blinding: str
    thresholds: tuple[Threshold, ...]
    run: Callable[[Any, "CheckSpec"], CheckOutcome]
    #: Largest design (rows x columns) the check runs on within its time budget;
    #: beyond it the result is "not checked" with that reason.
    max_cells: int | None = None
    #: When the check fails, the fit's standard errors, tests and intervals
    #: are meaningless (a perfect fit, separated data) and are withheld.
    suppresses_inference: bool = False

    def __post_init__(self) -> None:
        if self.blinding not in BLINDING_LEVELS:
            raise ValueError(f"unknown blinding level {self.blinding!r}")

    def threshold(self, name: str) -> float:
        for item in self.thresholds:
            if item.name == name:
                return item.value
        raise KeyError(name)

    def result(self, outcome: CheckOutcome) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "title": self.title,
            "status": outcome.status,
            "summary": outcome.summary,
            "evidence": dict(outcome.evidence),
            "blinding": self.blinding,
            "source": "computed",
            "thresholds": [item.to_dict() for item in self.thresholds],
            "remedy": outcome.remedy,
            "suppresses_inference": self.suppresses_inference and outcome.status == "fails",
        }
