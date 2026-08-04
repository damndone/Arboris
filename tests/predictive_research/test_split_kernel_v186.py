from __future__ import annotations

import pandas as pd
import pytest

from workbench.predictive_research.contracts import ContractError
from workbench.predictive_research.preprocessing import FoldPreprocessingKernel, PreprocessingStepV1
from workbench.predictive_research.split_kernel import build_split_plan


def test_iid_split_is_reproducible_and_final_holdout_isolated_from_cv() -> None:
    row_refs = tuple(f"row-{index}" for index in range(20))
    first = build_split_plan(
        row_refs=row_refs,
        strategy="iid",
        final_holdout_fraction=0.2,
        cv_folds=4,
        shuffle=True,
        random_seed=11,
    )
    second = build_split_plan(
        row_refs=row_refs,
        strategy="iid",
        final_holdout_fraction=0.2,
        cv_folds=4,
        shuffle=True,
        random_seed=11,
    )

    assert first.content_hash == second.content_hash
    assert first.assignments == second.assignments
    assert all(
        assignment.partition == "final_holdout" or assignment.cv_fold is not None
        for assignment in first.assignments
    )
    assert all(
        assignment.cv_fold is None
        for assignment in first.assignments
        if assignment.partition == "final_holdout"
    )


def test_grouped_split_never_places_one_group_in_two_partitions_or_folds() -> None:
    row_refs = tuple(f"row-{index}" for index in range(12))
    groups = tuple(f"group-{index // 2}" for index in range(12))

    plan = build_split_plan(
        row_refs=row_refs,
        groups=groups,
        strategy="grouped",
        final_holdout_fraction=0.25,
        cv_folds=3,
        shuffle=True,
        random_seed=5,
    )

    by_group: dict[str, set[tuple[str, int | None]]] = {}
    for assignment, group in zip(plan.assignments, groups, strict=True):
        by_group.setdefault(group, set()).add((assignment.partition, assignment.cv_fold))
    assert all(len(locations) == 1 for locations in by_group.values())


def test_temporal_split_keeps_latest_periods_in_final_holdout() -> None:
    row_refs = tuple(f"row-{index}" for index in range(12))
    periods = tuple(f"2024-01-{index + 1:02d}" for index in range(12))
    plan = build_split_plan(
        row_refs=row_refs,
        strategy="temporal",
        time_values=periods,
        final_holdout_fraction=0.25,
        cv_folds=2,
        shuffle=True,
        random_seed=5,
    )

    holdout = {
        assignment.row_ref
        for assignment in plan.assignments
        if assignment.partition == "final_holdout"
    }
    assert holdout == {"row-9", "row-10", "row-11"}
    assert plan.effective_parameters["time_order"] == "ascending"
    assert plan.effective_parameters["shuffle"] is False


def test_period_fitted_preprocessing_uses_training_fold_only() -> None:
    train = pd.DataFrame({"x": [1.0, 3.0], "z": [10.0, 14.0]})
    validation = pd.DataFrame({"x": [100.0, 101.0], "z": [18.0, 20.0]})
    kernel = FoldPreprocessingKernel(
        steps=(
            PreprocessingStepV1(
                transform_id="mean_impute",
                transform_version=1,
                fit_semantics="period_fitted",
                columns=("x",),
            ),
            PreprocessingStepV1(
                transform_id="standard_scale",
                transform_version=1,
                fit_semantics="period_fitted",
                columns=("z",),
            ),
        )
    )

    fitted = kernel.fit(train, fit_scope="development_fold_1")
    transformed = fitted.apply(validation)

    assert fitted.fit_scope == "development_fold_1"
    assert transformed["x"].tolist() == [100.0, 101.0]
    assert transformed["z"].round(6).tolist() == [3.0, 4.0]
    assert fitted.state["standard_scale:z"]["mean"] == 12.0


def test_period_fitted_preprocessing_rejects_final_holdout_as_fit_scope() -> None:
    kernel = FoldPreprocessingKernel(
        steps=(
            PreprocessingStepV1(
                transform_id="mean_impute",
                transform_version=1,
                fit_semantics="period_fitted",
                columns=("x",),
            ),
        )
    )

    with pytest.raises(ContractError) as error:
        kernel.fit(pd.DataFrame({"x": [1.0]}), fit_scope="final_holdout")

    assert error.value.code == "PREDICTION_PREPROCESSING_FIT_SCOPE_INVALID"
