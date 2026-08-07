"""Measurement level: what a column's numbers mean, and what was assumed.

`detect_y_kind` routes a non-negative integer column with few levels to Poisson.
A Likert 1-4 lands there exactly, and the run succeeds -- rate ratios, standard
errors, a report -- with nothing saying the outcome was treated as a count of
events. The user cannot see it, because there is nothing to see.

The routing is not changed here, and that is deliberate. `1,2,3,4` may be a
satisfaction rating, a visit count, an encoded region or a 4-point GPA; they are
numerically identical, and which one it is lives in how the variable was
measured, not in the data. Guessing would relocate the silent failure rather
than remove it -- the tools this is measured against do not guess either
(a Stata command *is* the declaration; SPSS's Measure column is a user-owned
variable property).

So: obey a declaration when there is one, and when there is not, say what was
assumed and show the evidence. Every field here is computed from the data. None
of it may come from a language model -- an advisory a model wrote is an
assertion wearing evidence's clothes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

#: Declarable levels. The first three mirror SPSS's Measure column.
MEASUREMENT_LEVELS = ("nominal", "ordinal", "scale", "count", "unspecified")
UNSPECIFIED = "unspecified"

#: How a declared level routes. A declaration is executed, not weighed against
#: the detector -- `scale` deliberately maps to the continuous route even for
#: integer data, because that is what declaring it means.
LEVEL_TO_MODEL_TYPE = {
    "ordinal": "ordinal_logit",
    "nominal": "multinomial_logit",
    "count": "poisson",
    "scale": "ols",
}

#: A rating scale is short. Beyond this many levels the count reading is at
#: least as plausible and an advisory would be noise.
_MAX_SCALE_LEVELS = 10


@dataclass(frozen=True)
class MeasurementEvidence:
    """Facts about a column, all read off the data."""

    column: str
    n_levels: int
    distinct_values: list[Any]
    includes_zero: bool
    is_integer: bool
    has_value_labels: bool
    value_labels: dict[str, str] = field(default_factory=dict)
    variable_label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "n_levels": self.n_levels,
            "distinct_values": list(self.distinct_values),
            "includes_zero": self.includes_zero,
            "is_integer": self.is_integer,
            "has_value_labels": self.has_value_labels,
            "value_labels": dict(self.value_labels),
            "variable_label": self.variable_label,
        }


def collect_evidence(
    frame: pd.DataFrame,
    column: str,
    *,
    value_labels: Mapping[str, Mapping[str, str]] | None = None,
    variable_labels: Mapping[str, str] | None = None,
) -> MeasurementEvidence | None:
    """Read the facts. Returns None for a column with no numeric reading."""
    if column not in frame.columns:
        return None
    series = frame[column].dropna()
    if series.empty or not pd.api.types.is_numeric_dtype(series):
        return None

    distinct = sorted(series.unique().tolist())
    is_integer = all(float(v).is_integer() for v in distinct)
    labels = dict((value_labels or {}).get(column) or {})

    return MeasurementEvidence(
        column=column,
        n_levels=len(distinct),
        distinct_values=[int(v) if is_integer else float(v) for v in distinct],
        includes_zero=any(float(v) == 0.0 for v in distinct),
        is_integer=is_integer,
        has_value_labels=bool(labels),
        value_labels=labels,
        variable_label=(variable_labels or {}).get(column),
    )


def assess(evidence: MeasurementEvidence, *, routed_as: str) -> dict[str, Any] | None:
    """Whether this column deserves an advisory, and on what grounds.

    Returns None when the evidence gives no reason to ask. Flagging everything
    would train users to dismiss the notice, which costs more than staying quiet.
    """
    if not evidence.is_integer or evidence.n_levels < 3:
        return None
    if evidence.n_levels > _MAX_SCALE_LEVELS:
        return None
    # A zero-inclusive column is a plausible count on its face; without labels
    # saying otherwise there is nothing to raise.
    if evidence.includes_zero and not evidence.has_value_labels:
        return None
    if routed_as not in {"count", "continuous"}:
        return None

    if evidence.has_value_labels:
        # Value labels are a statement that the numbers stand for categories --
        # nobody labels a visit count `1 = very dissatisfied`. The data has
        # carried this all along and nothing read it.
        confidence = "high"
        reason = (
            f"{evidence.column} carries value labels "
            f"({_sample_labels(evidence.value_labels)}), which normally means the "
            "numbers stand for categories rather than counts."
        )
    else:
        confidence = "low"
        reason = (
            f"{evidence.column} takes {evidence.n_levels} whole-number values "
            f"({_sample_values(evidence.distinct_values)}) and no zero, a shape "
            "shared by rating scales and by counts."
        )

    return {
        "column": evidence.column,
        "declared": UNSPECIFIED,
        "routed_as": routed_as,
        "suggested": "ordinal",
        "confidence": confidence,
        "evidence": evidence.to_dict(),
        # Phrased as a question throughout. The system presents facts; the
        # judgement is the user's.
        "message": (
            f"{reason} It was analysed as {routed_as}. If it is a rating scale, "
            f"declaring {evidence.column} as ordinal will change how it is modelled."
        ),
    }


def build_advisory(
    frame: pd.DataFrame,
    columns: Sequence[str],
    *,
    declared: Mapping[str, str] | None = None,
    routed_as: Mapping[str, str] | None = None,
    value_labels: Mapping[str, Mapping[str, str]] | None = None,
    variable_labels: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """One advisory packet for a run. Declared columns are left alone."""
    declared = dict(declared or {})
    routed = dict(routed_as or {})
    entries: list[dict[str, Any]] = []

    for column in columns:
        # Having answered, the user is not asked again.
        if declared.get(column, UNSPECIFIED) != UNSPECIFIED:
            continue
        evidence = collect_evidence(
            frame, column, value_labels=value_labels, variable_labels=variable_labels
        )
        if evidence is None:
            continue
        entry = assess(evidence, routed_as=routed.get(column, "unknown"))
        if entry is not None:
            entries.append(entry)

    return {
        "contract": "workbench.measurement_advisory.v1",
        "schema_version": 1,
        "entries": entries,
        # Stated in the artifact so a consumer cannot mistake it for a verdict,
        # and so an Agent quoting it has the boundary in front of it.
        "note": (
            "Evidence is extracted from the data; the reading of it is the user's. "
            "Nothing here was inferred by a language model."
        ),
    }


def _sample_labels(labels: Mapping[str, str], limit: int = 3) -> str:
    items = list(labels.items())[:limit]
    rendered = ", ".join(f"{key}={value}" for key, value in items)
    return rendered + (", ..." if len(labels) > limit else "")


def _sample_values(values: Sequence[Any], limit: int = 6) -> str:
    rendered = ", ".join(str(v) for v in values[:limit])
    return rendered + (", ..." if len(values) > limit else "")


def split_proposable(
    entries: Sequence[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Separate what the evidence supports declaring from what it does not.

    An Agent may batch the first group into one proposal. The second must be
    reported and left out of it: a column with three integer levels and no value
    labels has the shape of a rating and equally the shape of a count, and
    declaring it on that basis is a guess wearing the same clothes as the
    well-evidenced ones. Fifty columns declared in one click is the feature; one
    wrong declaration hidden among them, silent from then on, is the cost.
    """
    proposable: list[dict[str, Any]] = []
    uncertain: list[dict[str, Any]] = []
    for entry in entries:
        target = proposable if entry.get("confidence") == "high" else uncertain
        target.append(dict(entry))
    return proposable, uncertain
