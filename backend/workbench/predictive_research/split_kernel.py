"""Deterministic split planning with explicit final-holdout isolation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import random
from typing import Any, Sequence

from .contracts import ContractError


@dataclass(frozen=True)
class SplitAssignment:
    row_ref: str
    partition: str
    cv_fold: int | None

    def to_dict(self) -> dict[str, Any]:
        return {"row_ref": self.row_ref, "partition": self.partition, "cv_fold": self.cv_fold}


@dataclass(frozen=True)
class SplitPlanReceipt:
    strategy: str
    effective_parameters: dict[str, Any]
    assignments: tuple[SplitAssignment, ...]

    def to_dict(self) -> dict[str, Any]:
        profile_id = {
            "iid": "iid_holdout_kfold",
            "random": "iid_holdout_kfold",
            "grouped": "grouped_holdout_groupkfold",
            "temporal": "temporal_holdout_rolling",
            "panel": "panel_holdout_grouped_time",
        }[self.strategy]
        return {
            "payload_schema": "workbench.prediction.split-plan",
            "schema_version": 1,
            "strategy": self.strategy,
            "profile_id": profile_id,
            "profile_version": 1,
            "effective_parameters": self.effective_parameters,
            "assignments": [assignment.to_dict() for assignment in self.assignments],
        }

    @property
    def content_hash(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


def build_split_plan(
    *,
    row_refs: Sequence[str],
    strategy: str,
    final_holdout_fraction: float,
    cv_folds: int,
    shuffle: bool,
    random_seed: int,
    groups: Sequence[str] | None = None,
    time_values: Sequence[Any] | None = None,
) -> SplitPlanReceipt:
    """Build one immutable assignment for baseline, candidates, and controls."""

    if strategy == "panel":
        raise ContractError(
            "PREDICTION_SPLIT_PROFILE_NOT_SUPPORTED",
            "panel split execution is reserved for a later profile",
        )
    if strategy not in {"iid", "random", "grouped", "temporal"}:
        raise ContractError("PREDICTION_SPLIT_STRATEGY_INVALID", "unknown executable split strategy")
    if len(row_refs) < 2 or len(set(row_refs)) != len(row_refs):
        raise ContractError("PREDICTION_ROW_IDENTITY_INVALID", "row_refs must be unique and contain at least two rows")
    if not 0 < final_holdout_fraction < 1:
        raise ContractError("PREDICTION_SPLIT_PARAMETERS_INVALID", "final holdout fraction must be between zero and one")
    if not isinstance(cv_folds, int) or cv_folds < 2:
        raise ContractError("PREDICTION_SPLIT_PARAMETERS_INVALID", "cv_folds must be at least two")
    if strategy == "grouped" and (groups is None or len(groups) != len(row_refs)):
        raise ContractError("PREDICTION_GROUP_COLUMN_REQUIRED", "grouped split requires one group per row")
    if strategy == "temporal" and (time_values is None or len(time_values) != len(row_refs)):
        raise ContractError("PREDICTION_TIME_COLUMN_REQUIRED", "temporal split requires one time value per row")
    if time_values is not None and len(time_values) != len(row_refs):
        raise ContractError("PREDICTION_TIME_COLUMN_INVALID", "time_values must align with row_refs")

    if strategy == "temporal":
        assert time_values is not None
        if any(value is None for value in time_values):
            raise ContractError("PREDICTION_TIME_COLUMN_INVALID", "temporal split cannot order missing time values")
        try:
            ordered_indices = sorted(range(len(row_refs)), key=lambda index: time_values[index])
        except TypeError:
            ordered_indices = sorted(range(len(row_refs)), key=lambda index: str(time_values[index]))
        period_keys: list[str] = []
        rows_by_period: dict[str, list[int]] = {}
        for index in ordered_indices:
            period_key = str(time_values[index])
            if period_key not in rows_by_period:
                period_keys.append(period_key)
                rows_by_period[period_key] = []
            rows_by_period[period_key].append(index)
        holdout_period_count = max(1, math.ceil(len(period_keys) * final_holdout_fraction))
        development_periods = period_keys[:-holdout_period_count]
        holdout_periods = set(period_keys[-holdout_period_count:])
        if len(development_periods) < cv_folds + 1:
            raise ContractError(
                "PREDICTION_SPLIT_PARAMETERS_INVALID",
                "temporal development periods must include a warmup period and at least cv_folds validation periods",
            )
        validation_periods = development_periods[1:]
        fold_by_period = {
            period: min(cv_folds - 1, position * cv_folds // len(validation_periods))
            for position, period in enumerate(validation_periods)
        }
        assignments_by_index: dict[int, SplitAssignment] = {}
        for index, row_ref in enumerate(row_refs):
            period = str(time_values[index])
            if period in holdout_periods:
                assignments_by_index[index] = SplitAssignment(row_ref, "final_holdout", None)
            elif period == development_periods[0]:
                assignments_by_index[index] = SplitAssignment(row_ref, "development", None)
            else:
                assignments_by_index[index] = SplitAssignment(
                    row_ref, "development", fold_by_period[period]
                )
        assignments = tuple(assignments_by_index[index] for index in range(len(row_refs)))
        parameters = {
            "final_holdout_fraction": final_holdout_fraction,
            "cv_folds": cv_folds,
            "shuffle": False,
            "random_seed": random_seed,
            "time_binding": "declared",
            "time_order": "ascending",
            "holdout_period_count": holdout_period_count,
            "cv_warmup_periods": 1,
        }
        return SplitPlanReceipt(strategy=strategy, effective_parameters=parameters, assignments=assignments)

    order = list(range(len(row_refs)))
    rng = random.Random(random_seed)
    if shuffle:
        rng.shuffle(order)

    if strategy == "grouped":
        assert groups is not None
        unique_groups = list(dict.fromkeys(groups))
        if len(unique_groups) < cv_folds + 1:
            raise ContractError("PREDICTION_SPLIT_PARAMETERS_INVALID", "group count is too small for holdout and CV folds")
        if shuffle:
            rng.shuffle(unique_groups)
        holdout_group_count = max(1, math.ceil(len(unique_groups) * final_holdout_fraction))
        holdout_groups = set(unique_groups[-holdout_group_count:])
        development_groups = [group for group in unique_groups if group not in holdout_groups]
        if len(development_groups) < cv_folds:
            raise ContractError("PREDICTION_SPLIT_PARAMETERS_INVALID", "development groups are fewer than cv_folds")
        fold_by_group = {group: index % cv_folds for index, group in enumerate(development_groups)}
        assignments_by_index: dict[int, SplitAssignment] = {}
        for index, row_ref in enumerate(row_refs):
            group = groups[index]
            assignments_by_index[index] = SplitAssignment(
                row_ref=row_ref,
                partition="final_holdout" if group in holdout_groups else "development",
                cv_fold=None if group in holdout_groups else fold_by_group[group],
            )
    else:
        holdout_count = max(1, math.ceil(len(row_refs) * final_holdout_fraction))
        holdout_indices = set(order[-holdout_count:])
        development_order = [index for index in order if index not in holdout_indices]
        if len(development_order) < cv_folds:
            raise ContractError("PREDICTION_SPLIT_PARAMETERS_INVALID", "development rows are fewer than cv_folds")
        assignments_by_index = {
            index: SplitAssignment(
                row_ref=row_refs[index],
                partition="final_holdout" if index in holdout_indices else "development",
                cv_fold=None,
            )
            for index in range(len(row_refs))
        }
        for fold_index, index in enumerate(development_order):
            assignments_by_index[index] = SplitAssignment(
                row_ref=row_refs[index],
                partition="development",
                cv_fold=fold_index % cv_folds,
            )

    assignments = tuple(assignments_by_index[index] for index in range(len(row_refs)))
    parameters: dict[str, Any] = {
        "final_holdout_fraction": final_holdout_fraction,
        "cv_folds": cv_folds,
        "shuffle": shuffle,
        "random_seed": random_seed,
    }
    if groups is not None:
        parameters["group_binding"] = "declared"
    if time_values is not None:
        parameters["time_binding"] = "declared"
    return SplitPlanReceipt(strategy=strategy, effective_parameters=parameters, assignments=assignments)
