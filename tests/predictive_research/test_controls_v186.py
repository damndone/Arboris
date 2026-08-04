from __future__ import annotations

import pandas as pd

from workbench.predictive_research.controls import add_seeded_noise_feature, permute_target


def test_permutation_control_is_seeded_and_does_not_mutate_target() -> None:
    target = pd.Series([1.0, 2.0, 3.0, 4.0], index=["r1", "r2", "r3", "r4"], name="y")

    first = permute_target(target, seed=13)
    second = permute_target(target, seed=13)

    assert first.receipt["control"] == "permuted_target"
    assert first.receipt["seed"] == 13
    assert first.receipt["row_identity"] == ["r1", "r2", "r3", "r4"]
    assert first.values.equals(second.values)
    assert target.tolist() == [1.0, 2.0, 3.0, 4.0]
    assert first.values.index.tolist() == target.index.tolist()


def test_noise_feature_is_seeded_and_keeps_user_frame_immutable() -> None:
    frame = pd.DataFrame({"x": [1.0, 2.0, 3.0]}, index=["r1", "r2", "r3"])

    first = add_seeded_noise_feature(frame, seed=29, column_name="noise_v1")
    second = add_seeded_noise_feature(frame, seed=29, column_name="noise_v1")

    assert "noise_v1" not in frame.columns
    assert first.frame["noise_v1"].equals(second.frame["noise_v1"])
    assert first.receipt == {
        "control": "seeded_noise_features",
        "seed": 29,
        "column_name": "noise_v1",
        "row_identity": ["r1", "r2", "r3"],
    }
