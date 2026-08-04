"""Seeded, bounded negative-control inputs for predictive evidence."""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any

import pandas as pd

from .contracts import ContractError


@dataclass(frozen=True)
class PermutationControlResult:
    values: pd.Series
    receipt: dict[str, Any]


@dataclass(frozen=True)
class NoiseFeatureControlResult:
    frame: pd.DataFrame
    receipt: dict[str, Any]


def permute_target(target: pd.Series, *, seed: int) -> PermutationControlResult:
    if not isinstance(target, pd.Series) or target.empty:
        raise ContractError("PREDICTION_CONTROL_TARGET_INVALID", "permutation target must be a non-empty series")
    values = list(target.tolist())
    random.Random(seed).shuffle(values)
    permuted = pd.Series(values, index=target.index, name=target.name)
    return PermutationControlResult(
        values=permuted,
        receipt={
            "control": "permuted_target",
            "seed": seed,
            "row_identity": [str(value) for value in target.index],
        },
    )


def add_seeded_noise_feature(frame: pd.DataFrame, *, seed: int, column_name: str) -> NoiseFeatureControlResult:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ContractError("PREDICTION_CONTROL_FRAME_INVALID", "noise feature requires a non-empty frame")
    if not column_name or column_name in frame.columns:
        raise ContractError("PREDICTION_CONTROL_COLUMN_INVALID", "noise feature column must be new and non-empty")
    rng = random.Random(seed)
    result = frame.copy()
    result[column_name] = [rng.gauss(0.0, 1.0) for _ in range(len(frame))]
    return NoiseFeatureControlResult(
        frame=result,
        receipt={
            "control": "seeded_noise_features",
            "seed": seed,
            "column_name": column_name,
            "row_identity": [str(value) for value in frame.index],
        },
    )
