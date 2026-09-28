from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from workbench.predictive_research.classification_contracts import (
    ClassificationPreprocessingStepV1,
)
from workbench.predictive_research.contracts import ContractError
from workbench.predictive_research.preprocessing import ClassificationFoldPreprocessingV1
from workbench.predictive_research.split_kernel import build_classification_split_manifest


def test_temporal_manifest_rejects_feature_available_after_prediction_origin() -> None:
    with pytest.raises(ContractError) as exc_info:
        build_classification_split_manifest(
            row_refs=("r1", "r2", "r3", "r4", "r5", "r6"),
            labels=(0, 1, 0, 1, 0, 1),
            profile="temporal_rolling",
            final_holdout_fraction=1 / 3,
            cv_folds=2,
            random_seed=3,
            feature_available_at=(1, 2, 3, 4, 9, 6),
            prediction_origins=(1, 2, 3, 4, 5, 6),
            label_windows=((1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7)),
            periods=(1, 2, 3, 4, 5, 6),
        )

    assert exc_info.value.code == "CLASSIFICATION_INFORMATION_SET_VIOLATION"


def test_temporal_manifest_requires_feature_information_intervals() -> None:
    with pytest.raises(ContractError) as exc_info:
        build_classification_split_manifest(
            row_refs=tuple(f"r{i}" for i in range(8)),
            labels=(0, 1) * 4,
            profile="temporal_rolling",
            final_holdout_fraction=0.25,
            cv_folds=2,
            random_seed=3,
            periods=tuple(range(8)),
        )

    assert exc_info.value.code == "CLASSIFICATION_INFORMATION_SET_INCOMPLETE"


def test_temporal_manifest_requires_label_intervals_for_safe_boundary_proof() -> None:
    with pytest.raises(ContractError) as exc_info:
        build_classification_split_manifest(
            row_refs=tuple(f"r{i}" for i in range(8)),
            labels=(0, 1) * 4,
            profile="temporal_rolling",
            final_holdout_fraction=0.25,
            cv_folds=2,
            random_seed=3,
            feature_available_at=tuple(range(8)),
            prediction_origins=tuple(range(8)),
            periods=tuple(range(8)),
        )

    assert exc_info.value.code == "CLASSIFICATION_LABEL_WINDOW_REQUIRED"


def test_temporal_manifest_requires_explicit_embargo_basis() -> None:
    with pytest.raises(ContractError) as exc_info:
        build_classification_split_manifest(
            row_refs=tuple(f"r{i}" for i in range(8)),
            labels=(0, 1, 0, 1, 0, 1, 0, 1),
            profile="temporal_rolling",
            final_holdout_fraction=0.25,
            cv_folds=2,
            random_seed=3,
            feature_available_at=tuple(range(8)),
            prediction_origins=tuple(range(8)),
            periods=tuple(range(8)),
            embargo=1,
            embargo_basis=None,
        )

    assert exc_info.value.code == "CLASSIFICATION_EMBARGO_BASIS_REQUIRED"


def test_panel_new_entity_profile_rejects_entity_overlap_between_development_and_holdout() -> None:
    with pytest.raises(ContractError) as exc_info:
        build_classification_split_manifest(
            row_refs=tuple(f"r{i}" for i in range(8)),
            labels=(0, 1, 0, 1, 0, 1, 0, 1),
            profile="panel_new_entity",
            final_holdout_fraction=0.25,
            cv_folds=2,
            random_seed=4,
            feature_available_at=tuple(range(8)),
            prediction_origins=tuple(range(8)),
            entities=("a", "b", "c", "d", "a", "b", "c", "d"),
            periods=(1, 1, 1, 1, 2, 2, 2, 2),
            label_windows=tuple((index, index) for index in range(8)),
        )

    assert exc_info.value.code == "CLASSIFICATION_ENTITY_OVERLAP_FORBIDDEN"


def test_group_holdout_keeps_entities_whole_and_keeps_identity_receipt() -> None:
    manifest = build_classification_split_manifest(
        row_refs=tuple(f"r{i}" for i in range(12)),
        labels=(0, 1) * 6,
        profile="group_holdout",
        final_holdout_fraction=0.25,
        cv_folds=3,
        random_seed=4,
        entities=tuple(f"entity-{i // 2}" for i in range(12)),
        feature_available_at=tuple(range(12)),
        prediction_origins=tuple(range(12)),
    )

    by_entity: dict[str, set[str]] = {}
    for assignment, interval in zip(manifest.assignments, manifest.intervals, strict=True):
        by_entity.setdefault(interval.entity_ref or "", set()).add(assignment.partition)

    assert all(len(partitions) == 1 for partitions in by_entity.values())
    assert manifest.to_dict()["row_identity"] == "declared_row_ref_v1"
    assert manifest.content_hash.startswith("sha256:")


def test_unknown_profile_is_not_silently_treated_as_legacy_random_split() -> None:
    with pytest.raises(ContractError) as exc_info:
        build_classification_split_manifest(
            row_refs=tuple(f"r{i}" for i in range(8)),
            labels=(0, 1) * 4,
            profile="random",
            final_holdout_fraction=0.25,
            cv_folds=2,
            random_seed=1,
            feature_available_at=tuple(range(8)),
            prediction_origins=tuple(range(8)),
        )

    assert exc_info.value.code == "CLASSIFICATION_SPLIT_PROFILE_INVALID"


def test_temporal_rolling_is_ordered_and_keeps_latest_periods_in_holdout() -> None:
    manifest = build_classification_split_manifest(
        row_refs=tuple(f"r{i}" for i in range(10)),
        labels=(0, 1) * 5,
        profile="temporal_rolling",
        final_holdout_fraction=0.2,
        cv_folds=2,
        random_seed=9,
        feature_available_at=tuple(range(10)),
        prediction_origins=tuple(range(10)),
        periods=tuple(range(10)),
        label_windows=tuple((index, index) for index in range(10)),
    )

    holdout = {item.row_ref for item in manifest.assignments if item.partition == "final_holdout"}
    assert holdout == {"r8", "r9"}
    assert all(
        interval.period_ref < 8
        for assignment, interval in zip(manifest.assignments, manifest.intervals, strict=True)
        if assignment.partition != "final_holdout"
    )


def test_temporal_rolling_exposes_warmup_only_past_training_rows_per_validation_fold() -> None:
    periods = tuple(range(8))
    manifest = build_classification_split_manifest(
        row_refs=tuple(f"r{i}" for i in range(8)),
        labels=(0, 1) * 4,
        profile="temporal_rolling",
        final_holdout_fraction=0.25,
        cv_folds=3,
        random_seed=9,
        feature_available_at=periods,
        prediction_origins=periods,
        periods=periods,
        label_windows=tuple((period, period) for period in periods),
    )

    period_by_ref = {f"r{period}": period for period in periods}
    for fold in range(3):
        validation_refs = manifest.rows(partition="development", fold=fold)
        training_refs = manifest.training_rows_for_fold(fold)

        assert validation_refs
        assert training_refs
        assert "r0" in training_refs
        assert max(period_by_ref[ref] for ref in training_refs) < min(
            period_by_ref[ref] for ref in validation_refs
        )
        assert all(
            period_by_ref[ref] < min(period_by_ref[item] for item in validation_refs)
            for ref in training_refs
        )


def test_panel_known_entity_future_rejects_new_holdout_entity() -> None:
    entities = ("a", "b", "a", "b", "a", "b", "a", "b", "new")
    periods = (0, 0, 1, 1, 2, 2, 3, 3, 3)

    with pytest.raises(ContractError) as exc_info:
        build_classification_split_manifest(
            row_refs=tuple(f"r{i}" for i in range(len(periods))),
            labels=(0, 1, 0, 1, 0, 1, 0, 1, 0),
            profile="panel_known_entity_future",
            final_holdout_fraction=0.25,
            cv_folds=2,
            random_seed=2,
            feature_available_at=periods,
            prediction_origins=periods,
            entities=entities,
            periods=periods,
            label_windows=tuple((period, period) for period in periods),
        )

    assert exc_info.value.code == "CLASSIFICATION_KNOWN_ENTITY_VIOLATION"


def test_panel_new_entity_accepts_entities_seen_only_in_future_holdout() -> None:
    entities = ("a", "b", "a", "b", "a", "b", "new", "new")
    periods = (0, 0, 1, 1, 2, 2, 3, 3)
    manifest = build_classification_split_manifest(
        row_refs=tuple(f"r{i}" for i in range(len(periods))),
        labels=(0, 1) * 4,
        profile="panel_new_entity",
        final_holdout_fraction=0.25,
        cv_folds=2,
        random_seed=2,
        feature_available_at=periods,
        prediction_origins=periods,
        entities=entities,
        periods=periods,
        label_windows=tuple((period, period) for period in periods),
    )

    development_entities = {
        interval.entity_ref
        for assignment, interval in zip(manifest.assignments, manifest.intervals, strict=True)
        if assignment.partition == "development"
    }
    holdout_entities = {
        interval.entity_ref
        for assignment, interval in zip(manifest.assignments, manifest.intervals, strict=True)
        if assignment.partition == "final_holdout"
    }
    assert development_entities == {"a", "b"}
    assert holdout_entities == {"new"}


def test_panel_known_entity_future_allows_known_entities_only_in_future_holdout() -> None:
    entities = tuple(entity for period in range(6) for entity in ("a", "b"))
    periods = tuple(period for period in range(6) for _ in ("a", "b"))
    manifest = build_classification_split_manifest(
        row_refs=tuple(f"r{i}" for i in range(12)),
        labels=(0, 1) * 6,
        profile="panel_known_entity_future",
        final_holdout_fraction=1 / 3,
        cv_folds=2,
        random_seed=2,
        feature_available_at=tuple(range(12)),
        prediction_origins=tuple(range(12)),
        entities=entities,
        periods=periods,
        label_windows=tuple((index, index) for index in range(12)),
    )

    development_entities = {
        interval.entity_ref
        for assignment, interval in zip(manifest.assignments, manifest.intervals, strict=True)
        if assignment.partition == "development"
    }
    holdout_entities = {
        interval.entity_ref
        for assignment, interval in zip(manifest.assignments, manifest.intervals, strict=True)
        if assignment.partition == "final_holdout"
    }
    assert development_entities == holdout_entities == {"a", "b"}
    assert all(
        interval.period_ref > 3
        for assignment, interval in zip(manifest.assignments, manifest.intervals, strict=True)
        if assignment.partition == "final_holdout"
    )


def test_manifest_records_purge_and_embargo_basis_and_hash() -> None:
    manifest = build_classification_split_manifest(
        row_refs=tuple(f"r{i}" for i in range(10)),
        labels=(0, 1, 0, 1, 0, 1, 0, 1, 0, 1),
        profile="temporal_rolling",
        final_holdout_fraction=0.2,
        cv_folds=2,
        random_seed=5,
        feature_available_at=tuple(range(10)),
        prediction_origins=tuple(range(10)),
        periods=tuple(range(10)),
        label_windows=tuple((i * 10, i * 10 + 1) for i in range(10)),
        purge_gap=1,
        embargo=1,
        embargo_basis="declared_serial_dependence:v1",
    )

    payload = manifest.to_dict()
    assert payload["purge_basis"] == "label_window_overlap"
    assert payload["embargo_basis"] == "declared_serial_dependence:v1"
    assert manifest.content_hash.startswith("sha256:")
    assert all(item["partition"] != "final_holdout" or item["cv_fold"] is None for item in payload["assignments"])
    assert all(item["feature_available_at"] <= item["prediction_origin"] for item in payload["intervals"])


def test_iid_stratification_is_seeded_and_each_development_fold_has_class_support() -> None:
    kwargs = {
        "row_refs": tuple(f"r{i}" for i in range(12)),
        "labels": (0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1),
        "profile": "iid_stratified",
        "final_holdout_fraction": 0.25,
        "cv_folds": 3,
        "feature_available_at": tuple(range(12)),
        "prediction_origins": tuple(range(12)),
    }
    first = build_classification_split_manifest(**kwargs, random_seed=7)
    same = build_classification_split_manifest(**kwargs, random_seed=7)
    changed = build_classification_split_manifest(**kwargs, random_seed=8)

    assert first.content_hash == same.content_hash
    assert first.content_hash != changed.content_hash
    labels_by_ref = dict(zip(kwargs["row_refs"], kwargs["labels"], strict=True))
    for fold in range(3):
        fold_labels = {
            labels_by_ref[item.row_ref]
            for item in first.assignments
            if item.partition == "development" and item.cv_fold == fold
        }
        assert fold_labels == {0, 1}


def test_label_window_overlap_purges_development_row_instead_of_only_recording_it() -> None:
    manifest = build_classification_split_manifest(
        row_refs=tuple(f"r{i}" for i in range(8)),
        labels=(0, 1, 0, 1, 0, 1, 0, 1),
        profile="iid_stratified",
        final_holdout_fraction=0.25,
        cv_folds=2,
        random_seed=4,
        feature_available_at=tuple(range(8)),
        prediction_origins=tuple(range(8)),
        label_windows=((0, 2), (1, 1), (10, 11), (12, 13), (1, 3), (14, 15), (16, 17), (18, 19)),
        purge_gap=0,
    )

    assert any(item["row_ref"] == "r0" and item["other_row_ref"] == "r4" for item in manifest.purge_windows)
    assert next(item for item in manifest.assignments if item.row_ref == "r0").partition == "purged"


def test_temporal_embargo_purges_rows_at_the_holdout_boundary() -> None:
    manifest = build_classification_split_manifest(
        row_refs=tuple(f"r{i}" for i in range(12)),
        labels=(0, 1) * 6,
        profile="temporal_rolling",
        final_holdout_fraction=0.25,
        cv_folds=2,
        random_seed=4,
        feature_available_at=tuple(range(12)),
        prediction_origins=tuple(range(12)),
        periods=tuple(index // 2 for index in range(12)),
        label_windows=tuple((index, index) for index in range(12)),
        embargo=1,
        embargo_basis="one-period serial-dependence buffer",
    )

    assert manifest.embargo_basis == "one-period serial-dependence buffer"
    assert any(item["kind"] == "embargo" for item in manifest.purge_windows)
    assert any(item.partition == "purged" for item in manifest.assignments)


def test_temporal_datetime_label_windows_are_supported_without_fake_zero_gap() -> None:
    origin = tuple(dt.datetime(2026, 1, index + 1) for index in range(8))
    manifest = build_classification_split_manifest(
        row_refs=tuple(f"r{i}" for i in range(8)),
        labels=(0, 1) * 4,
        profile="temporal_rolling",
        final_holdout_fraction=0.25,
        cv_folds=2,
        random_seed=1,
        feature_available_at=origin,
        prediction_origins=origin,
        periods=origin,
        label_windows=tuple((value, value) for value in origin),
    )

    assert manifest.purge_basis == "label_window_overlap"


def test_fold_local_preprocessing_records_only_training_row_refs() -> None:
    kernel = ClassificationFoldPreprocessingV1(
        steps=(
            ClassificationPreprocessingStepV1(
                step_id="numeric_scale",
                kind="standard_scale",
                columns=("x",),
                supports_weight=True,
            ),
        )
    )

    fitted = kernel.fit(
        {"x": [1.0, 2.0, 1000.0]},
        fit_row_refs=("train-1", "train-2"),
        fit_rows={"train-1": {"x": 1.0}, "train-2": {"x": 2.0}},
        weight_name="analysis_weight",
    )

    assert fitted.fit_row_refs == ("train-1", "train-2")
    assert "holdout-1" not in fitted.fit_row_refs
    assert fitted.receipt["fit_scope"] == "training_fold_only"
    assert fitted.receipt["fit_row_refs"] == ["train-1", "train-2"]
    assert len(fitted.receipt["recipe_hash"]) == 64
    assert fitted.receipt["output_schema"] == ["x"]


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("a long sentence", "CLASSIFICATION_PREPROCESSING_FREE_TEXT_UNSUPPORTED"),
        ({"nested": True}, "CLASSIFICATION_PREPROCESSING_NESTED_UNSUPPORTED"),
        (dt.datetime(2026, 1, 1), "CLASSIFICATION_PREPROCESSING_DATETIME_RECIPE_REQUIRED"),
    ],
)
def test_fold_local_preprocessing_rejects_unsafe_feature_kinds(value: object, code: str) -> None:
    kernel = ClassificationFoldPreprocessingV1(
        steps=(
            ClassificationPreprocessingStepV1(
                step_id="numeric_scale",
                kind="standard_scale",
                columns=("x",),
                supports_weight=True,
            ),
        )
    )

    with pytest.raises(ContractError) as exc_info:
        kernel.fit(
            pd.DataFrame({"x": [value]}),
            fit_row_refs=("train-1",),
            fit_rows={"train-1": {"x": value}},
        )

    assert exc_info.value.code == code


def test_fold_local_preprocessing_rejects_all_missing_and_unsupported_weight() -> None:
    all_missing = ClassificationFoldPreprocessingV1(
        steps=(ClassificationPreprocessingStepV1("impute", "mean_impute", ("x",), True),)
    )
    with pytest.raises(ContractError) as missing:
        all_missing.fit(
            {"x": [None]},
            fit_row_refs=("r1",),
            fit_rows={"r1": {"x": None}},
        )
    assert missing.value.code == "CLASSIFICATION_PREPROCESSING_ALL_MISSING"

    unsupported_weight = ClassificationFoldPreprocessingV1(
        steps=(ClassificationPreprocessingStepV1("scale", "standard_scale", ("x",), False),)
    )
    with pytest.raises(ContractError) as weight:
        unsupported_weight.fit(
            {"x": [1.0]},
            fit_row_refs=("r1",),
            fit_rows={"r1": {"x": 1.0}},
            weight_name="frequency_weight",
        )
    assert weight.value.code == "CLASSIFICATION_WEIGHT_UNSUPPORTED"


def test_fold_local_preprocessing_reports_missing_column_before_all_missing() -> None:
    kernel = ClassificationFoldPreprocessingV1(
        steps=(ClassificationPreprocessingStepV1("scale", "standard_scale", ("missing",), True),)
    )

    with pytest.raises(ContractError) as exc_info:
        kernel.fit(
            {"x": [1.0]},
            fit_row_refs=("r1",),
            fit_rows={"r1": {"x": 1.0}},
        )

    assert exc_info.value.code == "CLASSIFICATION_PREPROCESSING_COLUMN_MISSING"


def test_fold_local_preprocessing_transform_requires_matching_row_identity() -> None:
    kernel = ClassificationFoldPreprocessingV1(
        steps=(ClassificationPreprocessingStepV1("scale", "standard_scale", ("x",), True),)
    )
    fitted = kernel.fit(
        {"x": [1.0, 2.0]},
        fit_row_refs=("r1", "r2"),
        fit_rows={"r1": {"x": 1.0}, "r2": {"x": 2.0}},
    )

    with pytest.raises(ContractError) as exc_info:
        fitted.transform(pd.DataFrame({"x": [3.0]}), row_refs=("r3", "r4"))

    assert exc_info.value.code == "CLASSIFICATION_PREPROCESSING_ALIGNMENT"


def test_fold_local_preprocessing_requires_a_declared_recipe_for_datetime() -> None:
    kernel = ClassificationFoldPreprocessingV1(
        steps=(
            ClassificationPreprocessingStepV1(
                step_id="date_year",
                kind="datetime_extract",
                columns=("as_of",),
                supports_weight=True,
                recipe={"component": "year"},
            ),
        )
    )
    fitted = kernel.fit(
        {"as_of": ["2025-01-01"]},
        fit_row_refs=("r1",),
        fit_rows={"r1": {"as_of": "2025-01-01"}},
    )

    transformed = fitted.transform(pd.DataFrame({"as_of": ["2026-02-03"]}), row_refs=("r2",))

    assert transformed["as_of__year"].tolist() == [2026]
