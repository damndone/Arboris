"""Input validation for the locked linear mixed-effects recipe."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pandas as pd

from workbench.contracts.model.linear_mixed_effects import (
    LMM_PRIMARY_RESULT_ID,
    LmmModelInput,
)
from workbench.contracts.common.envelope import ContractError


class LmmInputError(ValueError):
    """A fail-closed LMM design validation error."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        evidence: Mapping[str, object] | None = None,
    ) -> None:
        self.code = code
        self.evidence = dict(evidence or {})
        super().__init__(f"{code}: {message}")


def build_lmm_formula(
    *,
    outcome: str,
    group: str,
    time: str,
    reference_group: object,
    controls: Sequence[str],
) -> str:
    """Build the v1 fixed-effects formula with quoted column names."""

    terms = [
        f"C(Q({group!r}), Treatment(reference={reference_group!r})) * Q({time!r})"
    ]
    terms.extend(f"Q({control!r})" for control in controls)
    return f"Q({outcome!r}) ~ " + " + ".join(terms)


@dataclass(frozen=True)
class PreparedLmmInput:
    """The retained analysis rows and locked facts needed by the estimator."""

    frame: pd.DataFrame
    input: LmmModelInput
    reference_group: str
    comparison_group: str
    reference_group_value: object
    comparison_group_value: object
    exclusion_counts: Mapping[str, int]
    formula: str
    fixed_effects: tuple[str, ...]
    random_effects: tuple[str, ...]
    primary_result_id: str = LMM_PRIMARY_RESULT_ID


def prepare_lmm_input(
    frame: pd.DataFrame,
    *,
    outcome: str,
    controls: Sequence[str],
    options: Mapping[str, object],
) -> PreparedLmmInput:
    """Retain complete analysis rows while preserving subject identity."""

    try:
        model_input = LmmModelInput.from_dict(options)
    except ContractError as exc:
        raise LmmInputError(
            "LMM_INVALID_CONFIGURATION",
            str(exc),
        ) from exc
    if model_input.subject_id not in frame.columns:
        raise LmmInputError(
            "LMM_SUBJECT_ID_MISSING",
            f"column {model_input.subject_id!r} is absent",
            evidence={"column": model_input.subject_id},
        )
    if frame[model_input.subject_id].isna().any():
        raise LmmInputError(
            "LMM_SUBJECT_ID_MISSING",
            f"column {model_input.subject_id!r} contains null values",
            evidence={"column": model_input.subject_id},
        )

    raw_controls = tuple(controls)
    if any(type(control) is not str or not control for control in raw_controls):
        raise LmmInputError(
            "LMM_INVALID_CONFIGURATION",
            "controls must be non-empty column names",
        )
    if len(set(raw_controls)) != len(raw_controls):
        raise LmmInputError(
            "LMM_INVALID_CONFIGURATION",
            "controls must not contain duplicate columns",
        )
    ordered_controls = tuple(sorted(raw_controls))
    structural_columns = {
        outcome,
        model_input.subject_id,
        model_input.time,
        model_input.group,
    }
    overlapping_controls = [
        control for control in ordered_controls if control in structural_columns
    ]
    if overlapping_controls:
        raise LmmInputError(
            "LMM_INVALID_CONFIGURATION",
            f"control column {overlapping_controls[0]!r} duplicates a structural field",
            evidence={"column": overlapping_controls[0]},
        )
    required_columns = (outcome, model_input.time, model_input.group, *ordered_controls)
    absent = [column for column in required_columns if column not in frame.columns]
    if absent:
        raise LmmInputError(
            "LMM_INPUT_COLUMN_MISSING",
            f"column {absent[0]!r} is absent",
            evidence={"column": absent[0]},
        )
    if not pd.api.types.is_numeric_dtype(frame[outcome]):
        raise LmmInputError(
            "LMM_INVALID_CONFIGURATION",
            f"outcome column {outcome!r} must be numeric",
            evidence={"column": outcome},
        )
    non_numeric_controls = [
        column
        for column in ordered_controls
        if not pd.api.types.is_numeric_dtype(frame[column])
    ]
    if non_numeric_controls:
        raise LmmInputError(
            "LMM_INVALID_CONFIGURATION",
            f"control column {non_numeric_controls[0]!r} must be numeric",
            evidence={"column": non_numeric_controls[0]},
        )
    if not pd.api.types.is_numeric_dtype(frame[model_input.time]):
        raise LmmInputError(
            "LMM_TIME_NOT_NUMERIC",
            f"column {model_input.time!r} must be numeric",
            evidence={"column": model_input.time},
        )

    exclusion_counts = {
        column: int(frame[column].isna().sum())
        for column in required_columns
        if int(frame[column].isna().sum())
    }
    retained = frame.dropna(subset=list(required_columns)).copy()
    group_values = [
        value.item() if hasattr(value, "item") else value
        for value in retained[model_input.group].unique()
    ]
    ordered_group_values = sorted(group_values, key=str)
    groups = [str(value) for value in ordered_group_values]
    if len(groups) != 2:
        raise LmmInputError(
            "LMM_GROUP_NOT_BINARY",
            "retained rows must contain exactly two groups",
            evidence={"groups": groups},
        )
    group_counts = retained.groupby(model_input.subject_id, sort=False)[
        model_input.group
    ].nunique(dropna=True)
    varying_subjects = [
        str(subject) for subject, count in group_counts.items() if int(count) != 1
    ]
    if varying_subjects:
        raise LmmInputError(
            "LMM_GROUP_VARIES_WITHIN_SUBJECT",
            "group must remain constant within every subject",
            evidence={"subjects": sorted(varying_subjects)},
        )
    if len(group_counts) < 4:
        raise LmmInputError(
            "LMM_INSUFFICIENT_REPEATED_OBSERVATIONS",
            "at least four retained subjects are required",
            evidence={"n_subjects": int(len(group_counts))},
        )
    row_counts = retained.groupby(model_input.subject_id, sort=False).size()
    insufficient_subjects = [
        str(subject) for subject, count in row_counts.items() if int(count) < 2
    ]
    if insufficient_subjects:
        raise LmmInputError(
            "LMM_INSUFFICIENT_REPEATED_OBSERVATIONS",
            "each retained subject must have at least two rows",
            evidence={"subjects": sorted(insufficient_subjects)},
        )
    if model_input.random_slope:
        time_counts = retained.groupby(model_input.subject_id, sort=False)[
            model_input.time
        ].nunique(dropna=True)
        static_time_subjects = [
            str(subject)
            for subject, count in time_counts.items()
            if int(count) < 2
        ]
        if static_time_subjects:
            raise LmmInputError(
                "LMM_INVALID_RANDOM_SLOPE_CONFIGURATION",
                "a random time slope requires time to vary within every subject",
                evidence={
                    "time": model_input.time,
                    "subjects": sorted(static_time_subjects),
                },
            )

    return PreparedLmmInput(
        frame=retained,
        input=model_input,
        reference_group=groups[0],
        comparison_group=groups[1],
        reference_group_value=ordered_group_values[0],
        comparison_group_value=ordered_group_values[1],
        exclusion_counts=exclusion_counts,
        formula=build_lmm_formula(
            outcome=outcome,
            group=model_input.group,
            time=model_input.time,
            reference_group=ordered_group_values[0],
            controls=ordered_controls,
        ),
        fixed_effects=(
            "intercept",
            "group",
            "time",
            "group_time_interaction",
            *ordered_controls,
        ),
        random_effects=(
            ("random_intercept", "random_time_slope")
            if model_input.random_slope
            else ("random_intercept",)
        ),
    )
