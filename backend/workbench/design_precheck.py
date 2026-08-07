"""Sampling-design preconditions: check them, then ask.

SPSS and Stata will run an analysis whose assumptions are plainly violated and
say nothing about it -- noticing is left to the user. That is not a gap in those
tools so much as a limit of what a command-driven interface can do. Something
that can read the data can notice on the user's behalf, and this is where the
AI-native claim in the positioning document has to pay for itself.

The red line is absolute and is what keeps this useful rather than obnoxious:

    ask     "region looks like it could be a stratum variable; if the sample was
             stratified, the standard errors here are understated"
    never   "you should declare a stratified design"
    never   "your conclusion does not hold"

Every number is computed here and stored. An Agent quotes these values; it does
not recompute them and does not paraphrase them into new ones. A figure produced
by a language model is not evidence, however plausible it reads.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

#: A stratum or PSU column is coarse relative to the sample. Beyond this share of
#: distinct values it is an identifier, not a design variable.
_MAX_DISTINCT_SHARE = 0.5
#: Below this, a column is more likely a binary covariate than a design stratum.
_MIN_LEVELS = 3
#: A design effect materially above 1 is worth mentioning; 1.05 is not.
_DEFF_THRESHOLD = 1.2
#: A weight this many times the median means a few rows dominate the estimate.
_WEIGHT_RATIO_THRESHOLD = 10.0

_DESIGN_NAME_HINTS = (
    "stratum", "strata", "psu", "cluster", "region", "district", "block",
    "segment", "ward", "county", "province", "school", "village",
)


def _looks_like_design_column(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in _DESIGN_NAME_HINTS)


def _nests_within(frame: pd.DataFrame, child: str, candidates: Sequence[str]) -> str | None:
    """The column `child` sits inside, if any -- the shape of stratum/PSU.

    A PSU nested in a stratum is the structural signature of a multistage
    design, and it is a fact about the data rather than a guess about intent.
    """
    for parent in candidates:
        if parent == child:
            continue
        grouped = frame.groupby(child, observed=True)[parent].nunique()
        if len(grouped) and bool((grouped == 1).all()):
            child_levels = int(frame[child].nunique())
            parent_levels = int(frame[parent].nunique())
            if parent_levels < child_levels:
                return parent
    return None


def collect_design_findings(
    frame: pd.DataFrame,
    *,
    declared: Mapping[str, Any] | None = None,
    survey_design: Mapping[str, Any] | None = None,
    weight_column: str | None = None,
    modelled_columns: Sequence[str] = (),
    rows_before_cleaning: int | None = None,
) -> list[dict[str, Any]]:
    """Facts worth a question, each carrying the numbers behind it."""
    declared = dict(declared or {})
    findings: list[dict[str, Any]] = []

    design_declared = bool(
        str(declared.get("survey_strata_col") or "").strip()
        or str(declared.get("survey_psu_col") or "").strip()
    )

    if not design_declared:
        findings.extend(_undeclared_design_findings(frame, modelled_columns))

    if survey_design:
        findings.extend(_design_effect_findings(survey_design))
        findings.extend(
            _filtered_data_findings(len(frame), rows_before_cleaning)
        )

    if weight_column and weight_column in frame.columns:
        findings.extend(_weight_findings(frame, weight_column))

    return findings


def _undeclared_design_findings(
    frame: pd.DataFrame, modelled_columns: Sequence[str]
) -> list[dict[str, Any]]:
    modelled = set(modelled_columns)
    n_rows = len(frame)
    candidates = [
        column
        for column in frame.columns
        # A column already in the model is being used as a covariate; raising it
        # as a possible stratum would be second-guessing a stated choice.
        if column not in modelled
        and _looks_like_design_column(str(column))
        and _MIN_LEVELS <= int(frame[column].nunique()) <= max(
            _MIN_LEVELS, int(n_rows * _MAX_DISTINCT_SHARE)
        )
    ]

    findings: list[dict[str, Any]] = []
    for column in candidates:
        counts = frame.groupby(column, observed=True).size()
        nests = _nests_within(frame, column, candidates)
        findings.append(
            {
                "kind": "possible_undeclared_design",
                "column": str(column),
                "evidence": {
                    "n_distinct": int(frame[column].nunique()),
                    "rows_per_level": {
                        "min": int(counts.min()),
                        "max": int(counts.max()),
                    },
                    "nests_within": nests,
                },
                "message": _undeclared_message(str(column), nests),
            }
        )
    return findings


def _undeclared_message(column: str, nests: str | None) -> str:
    if nests:
        return (
            f"Each value of {column} falls inside a single {nests}, the shape a "
            f"primary sampling unit takes within a stratum. This run treated the "
            f"data as a simple random sample. If it came from a multistage design, "
            f"declaring {nests} as the stratum and {column} as the PSU would change "
            "the standard errors."
        )
    return (
        f"{column} was not used in the model and takes a small number of repeated "
        "values, the shape of a stratum variable. This run treated the data as a "
        "simple random sample. If the sample was stratified on it, the standard "
        "errors here are narrower than the design implies."
    )


def _design_effect_findings(survey_design: Mapping[str, Any]) -> list[dict[str, Any]]:
    deff = survey_design.get("design_effect")
    n_eff = survey_design.get("effective_sample_size")
    n_obs = survey_design.get("n_obs")
    if deff is None or n_eff is None or float(deff) < _DEFF_THRESHOLD:
        return []
    return [
        {
            "kind": "design_effect",
            "column": None,
            "evidence": {
                # Carried verbatim so nothing downstream has to re-derive them:
                # a recomputed n_eff would disagree with the result panel.
                "design_effect": deff,
                "effective_sample_size": n_eff,
                "n_obs": n_obs,
            },
            "message": (
                f"The design effect is {float(deff):.2f}: these {int(n_obs)} "
                f"observations carry about as much information as "
                f"{int(round(float(n_eff)))} would under simple random sampling. "
                "That bears on how much weight the intervals can take."
            ),
        }
    ]


def _weight_findings(frame: pd.DataFrame, weight_column: str) -> list[dict[str, Any]]:
    weights = pd.to_numeric(frame[weight_column], errors="coerce").dropna()
    weights = weights[weights > 0]
    if weights.empty:
        return []
    median = float(weights.median())
    maximum = float(weights.max())
    if median <= 0 or maximum / median < _WEIGHT_RATIO_THRESHOLD:
        return []

    share = float(weights[weights >= median * _WEIGHT_RATIO_THRESHOLD].count()) / len(weights)
    return [
        {
            "kind": "extreme_weights",
            "column": weight_column,
            "evidence": {
                "max": maximum,
                "median": median,
                "min": float(weights.min()),
                "max_over_median": maximum / median,
                "share_at_or_above_threshold": share,
            },
            "message": (
                f"The largest weight in {weight_column} is {maximum / median:.0f} times "
                f"the median, and {share:.1%} of rows sit at that level or above. A few "
                "observations therefore carry much of the estimate. Whether that "
                "reflects the sample design or a problem in how the weights were "
                "built is worth a look."
            ),
        }
    ]


def build_precheck(findings: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "contract": "workbench.design_precheck.v1",
        "schema_version": 1,
        "findings": [dict(finding) for finding in findings],
        "note": (
            "Every figure here was computed by the engine. These are observations "
            "and questions, not conclusions; the reading of them is the user's."
        ),
    }


def _filtered_data_findings(
    rows_analysed: int, rows_before: int | None
) -> list[dict[str, Any]]:
    """A design declared over data that lost rows before it was applied.

    Not a refusal -- dropping duplicated or incomplete rows is ordinary and
    usually right. But the design names the population the *original* frame was
    drawn from, and the analysis sample no longer is that frame. Weights still
    sum to the population total, so nothing in the output shows the gap.
    """
    if rows_before is None or rows_before <= rows_analysed:
        return []
    dropped = rows_before - rows_analysed
    return [
        {
            "kind": "design_over_filtered_data",
            "column": None,
            "evidence": {
                "rows_before": int(rows_before),
                "rows_analysed": int(rows_analysed),
                "rows_dropped": int(dropped),
                "share_dropped": dropped / rows_before,
            },
            "message": (
                f"{dropped} of {rows_before} rows were removed before the model ran, "
                f"leaving {rows_analysed}. The declared design describes the sample "
                "as originally drawn, so the weights still refer to the full "
                "population while the analysis covers a subset of it. Whether that "
                "gap matters depends on why the rows went."
            ),
        }
    ]
