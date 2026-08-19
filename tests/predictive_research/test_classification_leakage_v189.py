from __future__ import annotations

import pytest

from workbench.predictive_research.split_kernel import build_classification_split_manifest
from workbench.predictive_research.preprocessing import (
    ClassificationPreprocessingStepV1,
    ClassificationFoldPreprocessingV1,
)
from workbench.predictive_research.contracts import ContractError


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


def test_temporal_manifest_requires_explicit_embargo_basis() -> None:
    with pytest.raises(ContractError) as exc_info:
        build_classification_split_manifest(
            row_refs=tuple(f"r{i}" for i in range(8)),
            labels=(0, 1, 0, 1, 0, 1, 0, 1),
            profile="temporal_rolling",
            final_holdout_fraction=0.25,
            cv_folds=2,
            random_seed=3,
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
            entities=("a", "b", "c", "d", "a", "b", "c", "d"),
            periods=(1, 1, 1, 1, 2, 2, 2, 2),
        )

    assert exc_info.value.code == "CLASSIFICATION_ENTITY_OVERLAP_FORBIDDEN"


def test_manifest_records_purge_and_embargo_basis_and_hash() -> None:
    manifest = build_classification_split_manifest(
        row_refs=tuple(f"r{i}" for i in range(10)),
        labels=(0, 1, 0, 1, 0, 1, 0, 1, 0, 1),
        profile="temporal_rolling",
        final_holdout_fraction=0.2,
        cv_folds=2,
        random_seed=5,
        periods=tuple(range(10)),
        label_windows=tuple((i, i + 2) for i in range(10)),
        purge_gap=1,
        embargo=1,
        embargo_basis="declared_serial_dependence:v1",
    )

    payload = manifest.to_dict()
    assert payload["purge_basis"] == "label_window_overlap"
    assert payload["embargo_basis"] == "declared_serial_dependence:v1"
    assert manifest.content_hash.startswith("sha256:")
    assert all(item["partition"] != "final_holdout" or item["cv_fold"] is None for item in payload["assignments"])


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


def test_iid_stratification_is_seeded_and_each_development_fold_has_class_support() -> None:
    kwargs = {
        "row_refs": tuple(f"r{i}" for i in range(12)),
        "labels": (0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1),
        "profile": "iid_stratified",
        "final_holdout_fraction": 0.25,
        "cv_folds": 3,
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
        periods=tuple(index // 2 for index in range(12)),
        embargo=1,
        embargo_basis="one-period serial-dependence buffer",
    )

    assert manifest.embargo_basis == "one-period serial-dependence buffer"
    assert any(item["kind"] == "embargo" for item in manifest.purge_windows)
    assert any(item.partition == "purged" for item in manifest.assignments)
