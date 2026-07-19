from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from workbench.engine.packs.linear_mixed_effects.input import (
    LmmInputError,
    build_lmm_formula,
    prepare_lmm_input,
)


ROOT = Path(__file__).parents[2] / "fixtures" / "models" / "linear_mixed_effects"


def test_formula_uses_quoted_columns_and_the_locked_group_time_interaction() -> None:
    assert build_lmm_formula(
        outcome="score",
        group="arm",
        time="week",
        reference_group="control",
        controls=["baseline_score"],
    ) == (
        "Q('score') ~ C(Q('arm'), Treatment(reference='control')) * Q('week') "
        "+ Q('baseline_score')"
    )


def test_complete_case_filter_keeps_subject_identity_and_counts_exclusions() -> None:
    frame = pd.read_csv(ROOT / "known_truth.csv")
    frame.loc[0, "baseline_score"] = None

    prepared = prepare_lmm_input(
        frame,
        outcome="score",
        controls=["baseline_score"],
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": True,
        },
    )

    assert len(prepared.frame) == 479
    assert prepared.exclusion_counts == {"baseline_score": 1}
    assert prepared.reference_group == "control"
    assert prepared.primary_result_id == "group_time_interaction"


def test_prepared_input_exposes_locked_fixed_and_random_effects_facts() -> None:
    frame = pd.read_csv(ROOT / "known_truth.csv")

    prepared = prepare_lmm_input(
        frame,
        outcome="score",
        controls=["baseline_score"],
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": True,
        },
    )

    assert prepared.formula == (
        "Q('score') ~ C(Q('arm'), Treatment(reference='control')) * Q('week') "
        "+ Q('baseline_score')"
    )
    assert prepared.fixed_effects == (
        "intercept",
        "group",
        "time",
        "group_time_interaction",
        "baseline_score",
    )
    assert prepared.random_effects == ("random_intercept", "random_time_slope")


def test_controls_are_sorted_before_formula_and_identity_facts() -> None:
    frame = pd.read_csv(ROOT / "known_truth.csv")
    frame["a_control"] = frame["baseline_score"] * 0.5
    frame["z_control"] = frame["baseline_score"] * 2

    prepared = prepare_lmm_input(
        frame,
        outcome="score",
        controls=["z_control", "a_control"],
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": False,
        },
    )

    assert prepared.formula.endswith("+ Q('a_control') + Q('z_control')")
    assert prepared.fixed_effects[-2:] == ("a_control", "z_control")


def test_binary_numeric_group_uses_numeric_reference_in_the_formula() -> None:
    frame = pd.read_csv(ROOT / "known_truth.csv")
    frame["arm"] = frame["arm"].map({"control": 0, "treated": 1})

    prepared = prepare_lmm_input(
        frame,
        outcome="score",
        controls=[],
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": False,
        },
    )

    assert prepared.reference_group == "0"
    assert prepared.comparison_group == "1"
    assert "Treatment(reference=0)" in prepared.formula


def test_null_subject_blocks_before_complete_case_filter() -> None:
    frame = pd.read_csv(ROOT / "known_truth.csv")
    frame.loc[0, "participant_id"] = None

    with pytest.raises(LmmInputError, match="LMM_SUBJECT_ID_MISSING") as error:
        prepare_lmm_input(
            frame,
            outcome="score",
            controls=[],
            options={
                "subject_id": "participant_id",
                "time": "week",
                "group": "arm",
                "fit_method": "reml",
                "random_slope": False,
            },
        )

    assert error.value.code == "LMM_SUBJECT_ID_MISSING"


def test_non_numeric_time_blocks_before_fit() -> None:
    frame = pd.read_csv(ROOT / "known_truth.csv")
    frame["week"] = frame["week"].astype(object)
    frame.loc[0, "week"] = "not-a-number"

    with pytest.raises(LmmInputError, match="LMM_TIME_NOT_NUMERIC") as error:
        prepare_lmm_input(
            frame,
            outcome="score",
            controls=[],
            options={
                "subject_id": "participant_id",
                "time": "week",
                "group": "arm",
                "fit_method": "reml",
                "random_slope": False,
            },
        )

    assert error.value.code == "LMM_TIME_NOT_NUMERIC"


def test_non_binary_group_blocks_before_fit() -> None:
    frame = pd.read_csv(ROOT / "known_truth.csv")
    frame.loc[0, "arm"] = "third"

    with pytest.raises(LmmInputError, match="LMM_GROUP_NOT_BINARY") as error:
        prepare_lmm_input(
            frame,
            outcome="score",
            controls=[],
            options={
                "subject_id": "participant_id",
                "time": "week",
                "group": "arm",
                "fit_method": "reml",
                "random_slope": False,
            },
        )

    assert error.value.code == "LMM_GROUP_NOT_BINARY"


def test_group_that_varies_within_subject_blocks_before_fit() -> None:
    frame = pd.read_csv(ROOT / "known_truth.csv")
    frame.loc[1, "arm"] = "treated"

    with pytest.raises(LmmInputError, match="LMM_GROUP_VARIES_WITHIN_SUBJECT") as error:
        prepare_lmm_input(
            frame,
            outcome="score",
            controls=[],
            options={
                "subject_id": "participant_id",
                "time": "week",
                "group": "arm",
                "fit_method": "reml",
                "random_slope": False,
            },
        )

    assert error.value.code == "LMM_GROUP_VARIES_WITHIN_SUBJECT"


def test_fewer_than_four_retained_subjects_blocks_before_fit() -> None:
    frame = pd.read_csv(ROOT / "known_truth.csv")
    frame = frame[frame["participant_id"].isin(["C001", "C002", "T001"])]

    with pytest.raises(
        LmmInputError, match="LMM_INSUFFICIENT_REPEATED_OBSERVATIONS"
    ) as error:
        prepare_lmm_input(
            frame,
            outcome="score",
            controls=[],
            options={
                "subject_id": "participant_id",
                "time": "week",
                "group": "arm",
                "fit_method": "reml",
                "random_slope": False,
            },
        )

    assert error.value.code == "LMM_INSUFFICIENT_REPEATED_OBSERVATIONS"


def test_single_observation_per_subject_blocks_before_fit() -> None:
    frame = pd.read_csv(ROOT / "single_observation_per_subject.csv")

    with pytest.raises(
        LmmInputError, match="LMM_INSUFFICIENT_REPEATED_OBSERVATIONS"
    ) as error:
        prepare_lmm_input(
            frame,
            outcome="score",
            controls=[],
            options={
                "subject_id": "participant_id",
                "time": "week",
                "group": "arm",
                "fit_method": "reml",
                "random_slope": False,
            },
        )

    assert error.value.code == "LMM_INSUFFICIENT_REPEATED_OBSERVATIONS"


def test_random_slope_requires_time_to_vary_within_every_subject() -> None:
    frame = pd.read_csv(ROOT / "singular_random_slope.csv")

    with pytest.raises(
        LmmInputError, match="LMM_INVALID_RANDOM_SLOPE_CONFIGURATION"
    ) as error:
        prepare_lmm_input(
            frame,
            outcome="score",
            controls=["baseline_score"],
            options={
                "subject_id": "participant_id",
                "time": "week",
                "group": "arm",
                "fit_method": "reml",
                "random_slope": True,
            },
        )

    assert error.value.code == "LMM_INVALID_RANDOM_SLOPE_CONFIGURATION"


def test_invalid_locked_option_configuration_fails_with_an_lmm_code() -> None:
    frame = pd.read_csv(ROOT / "known_truth.csv")

    with pytest.raises(LmmInputError, match="LMM_INVALID_CONFIGURATION") as error:
        prepare_lmm_input(
            frame,
            outcome="score",
            controls=[],
            options={
                "subject_id": "participant_id",
                "time": "week",
                "group": "arm",
                "fit_method": "reml",
                "random_slope": 1,
            },
        )

    assert error.value.code == "LMM_INVALID_CONFIGURATION"


def test_non_numeric_outcome_fails_closed_before_formula_construction() -> None:
    frame = pd.read_csv(ROOT / "known_truth.csv")
    frame["score"] = frame["score"].astype(object)
    frame.loc[0, "score"] = "not-a-number"

    with pytest.raises(LmmInputError, match="LMM_INVALID_CONFIGURATION") as error:
        prepare_lmm_input(
            frame,
            outcome="score",
            controls=[],
            options={
                "subject_id": "participant_id",
                "time": "week",
                "group": "arm",
                "fit_method": "reml",
                "random_slope": False,
            },
        )

    assert error.value.code == "LMM_INVALID_CONFIGURATION"


def test_non_numeric_control_fails_closed_before_formula_construction() -> None:
    frame = pd.read_csv(ROOT / "known_truth.csv")
    frame["site"] = "one"

    with pytest.raises(LmmInputError, match="LMM_INVALID_CONFIGURATION") as error:
        prepare_lmm_input(
            frame,
            outcome="score",
            controls=["site"],
            options={
                "subject_id": "participant_id",
                "time": "week",
                "group": "arm",
                "fit_method": "reml",
                "random_slope": False,
            },
        )

    assert error.value.code == "LMM_INVALID_CONFIGURATION"


@pytest.mark.parametrize("controls", (["week"], ["baseline_score", "baseline_score"]))
def test_controls_cannot_duplicate_structural_or_each_other(controls: list[str]) -> None:
    frame = pd.read_csv(ROOT / "known_truth.csv")

    with pytest.raises(LmmInputError, match="LMM_INVALID_CONFIGURATION") as error:
        prepare_lmm_input(
            frame,
            outcome="score",
            controls=controls,
            options={
                "subject_id": "participant_id",
                "time": "week",
                "group": "arm",
                "fit_method": "reml",
                "random_slope": False,
            },
        )

    assert error.value.code == "LMM_INVALID_CONFIGURATION"


def test_missing_subject_column_blocks_instead_of_filtering() -> None:
    frame = pd.read_csv(ROOT / "missing_subject_id.csv")

    with pytest.raises(LmmInputError, match="LMM_SUBJECT_ID_MISSING"):
        prepare_lmm_input(
            frame,
            outcome="score",
            controls=[],
            options={
                "subject_id": "participant_id",
                "time": "week",
                "group": "arm",
                "fit_method": "reml",
                "random_slope": False,
            },
        )
