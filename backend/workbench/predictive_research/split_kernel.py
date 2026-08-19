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


@dataclass(frozen=True)
class InformationIntervalV1:
    row_ref: str
    feature_available_at: Any | None
    prediction_origin: Any | None
    label_start: Any | None
    label_end: Any | None
    entity_ref: str | None
    period_ref: Any | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_ref": self.row_ref,
            "feature_available_at": self.feature_available_at,
            "prediction_origin": self.prediction_origin,
            "label_start": self.label_start,
            "label_end": self.label_end,
            "entity_ref": self.entity_ref,
            "period_ref": self.period_ref,
        }


@dataclass(frozen=True)
class ClassificationSplitManifestV1:
    profile: str
    assignments: tuple[SplitAssignment, ...]
    intervals: tuple[InformationIntervalV1, ...]
    purge_windows: tuple[dict[str, Any], ...]
    purge_basis: str
    embargo: Any | None
    embargo_basis: str | None
    effective_parameters: dict[str, Any]
    training_row_refs_by_fold: tuple[tuple[str, ...], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "payload_schema": "workbench.prediction.classification-split-manifest",
            "schema_version": 1,
            "profile": self.profile,
            "assignments": [item.to_dict() for item in self.assignments],
            "intervals": [item.to_dict() for item in self.intervals],
            "purge_windows": list(self.purge_windows),
            "purge_basis": self.purge_basis,
            "embargo": self.embargo,
            "embargo_basis": self.embargo_basis,
            "effective_parameters": self.effective_parameters,
            "training_row_refs_by_fold": [list(rows) for rows in self.training_row_refs_by_fold],
        }

    @property
    def content_hash(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def rows(self, *, partition: str, fold: int | None = None) -> tuple[str, ...]:
        return tuple(
            item.row_ref
            for item in self.assignments
            if item.partition == partition and (fold is None or item.cv_fold == fold)
        )

    def training_rows_for_fold(self, fold: int) -> tuple[str, ...]:
        if not isinstance(fold, int) or isinstance(fold, bool) or fold < 0:
            raise ContractError("CLASSIFICATION_SPLIT_FOLD_INVALID", "fold must be a non-negative integer")
        if fold >= len(self.training_row_refs_by_fold):
            raise ContractError("CLASSIFICATION_SPLIT_FOLD_INVALID", "fold is outside the split manifest")
        return self.training_row_refs_by_fold[fold]


def _ordered_before(left: Any, right: Any) -> bool:
    try:
        return bool(left <= right)
    except (TypeError, ValueError) as exc:
        raise ContractError("CLASSIFICATION_TIME_ORDER_INVALID", "ordered period values must share a comparable type") from exc


def _strictly_after(left: Any, right: Any) -> bool:
    try:
        return bool(left > right)
    except (TypeError, ValueError) as exc:
        raise ContractError("CLASSIFICATION_TIME_ORDER_INVALID", "ordered period values must share a comparable type") from exc


def _interval_overlaps(left: tuple[Any, Any], right: tuple[Any, Any], gap: Any | None) -> bool:
    left_start, left_end = left
    right_start, right_end = right
    if not _ordered_before(left_start, left_end) or not _ordered_before(right_start, right_end):
        raise ContractError("CLASSIFICATION_LABEL_WINDOW_INVALID", "label windows must be ordered intervals")
    try:
        boundary = left_end + (gap or 0)
        return not _strictly_after(right_start, boundary) and not _strictly_after(left_start, right_end + (gap or 0))
    except TypeError as exc:
        raise ContractError(
            "CLASSIFICATION_PURGE_GAP_INVALID",
            "purge_gap must be executable with the declared label-window type",
        ) from exc


def _holdout_indices_for_periods(periods: Sequence[Any], fraction: float) -> tuple[set[int], list[Any], list[Any]]:
    try:
        unique = list(dict.fromkeys(sorted(periods)))
    except (TypeError, ValueError) as exc:
        raise ContractError("CLASSIFICATION_TIME_ORDER_INVALID", "period values must share a comparable type") from exc
    count = max(1, math.ceil(len(unique) * fraction))
    holdout_periods = unique[-count:]
    return {index for index, period in enumerate(periods) if period in holdout_periods}, unique[:-count], holdout_periods


def build_classification_split_manifest(
    *,
    row_refs: Sequence[str],
    labels: Sequence[Any],
    profile: str,
    final_holdout_fraction: float,
    cv_folds: int,
    random_seed: int,
    feature_available_at: Sequence[Any] | None = None,
    prediction_origins: Sequence[Any] | None = None,
    label_windows: Sequence[tuple[Any, Any]] | None = None,
    entities: Sequence[str] | None = None,
    periods: Sequence[Any] | None = None,
    purge_gap: Any | None = None,
    embargo: Any | None = None,
    embargo_basis: str | None = None,
) -> ClassificationSplitManifestV1:
    """Build a classification split manifest with executable safety predicates."""

    allowed = {"iid_stratified", "group_holdout", "temporal_rolling", "panel_known_entity_future", "panel_new_entity"}
    if profile not in allowed:
        raise ContractError("CLASSIFICATION_SPLIT_PROFILE_INVALID", f"unknown classification profile {profile!r}")
    n = len(row_refs)
    if n < 4 or len(set(row_refs)) != n or len(labels) != n:
        raise ContractError("CLASSIFICATION_ROW_IDENTITY_INVALID", "row_refs and labels must align and contain unique rows")
    if not 0 < final_holdout_fraction < 1 or not isinstance(cv_folds, int) or cv_folds < 2:
        raise ContractError("CLASSIFICATION_SPLIT_PARAMETERS_INVALID", "holdout fraction and cv_folds are invalid")
    if embargo is not None and (not isinstance(embargo_basis, str) or not embargo_basis.strip()):
        raise ContractError("CLASSIFICATION_EMBARGO_BASIS_REQUIRED", "embargo requires an explicit serial-dependence basis")
    if embargo is not None and profile not in {"temporal_rolling", "panel_known_entity_future", "panel_new_entity"}:
        raise ContractError("CLASSIFICATION_EMBARGO_PROFILE_INVALID", "embargo is only valid for ordered temporal or panel profiles")
    if profile in {"group_holdout", "panel_known_entity_future", "panel_new_entity"} and entities is None:
        raise ContractError("CLASSIFICATION_ENTITY_REQUIRED", "this split profile requires entity refs")
    if profile in {"temporal_rolling", "panel_known_entity_future", "panel_new_entity"} and periods is None:
        raise ContractError("CLASSIFICATION_PERIOD_REQUIRED", "this split profile requires ordered periods")
    for values, label in ((feature_available_at, "feature_available_at"), (prediction_origins, "prediction_origins"), (entities, "entities"), (periods, "periods")):
        if values is not None and len(values) != n:
            raise ContractError("CLASSIFICATION_SPLIT_ALIGNMENT_INVALID", f"{label} must align with row_refs")
    if label_windows is not None and len(label_windows) != n:
        raise ContractError("CLASSIFICATION_LABEL_WINDOW_INVALID", "label_windows must align with row_refs")
    if feature_available_at is not None and prediction_origins is not None:
        for row_ref, available, origin in zip(row_refs, feature_available_at, prediction_origins):
            if available is None or origin is None or not _ordered_before(available, origin):
                raise ContractError("CLASSIFICATION_INFORMATION_SET_VIOLATION", f"feature availability is unsafe for {row_ref}")

    assignments: list[SplitAssignment] = []
    holdout: set[int] = set()
    fold_by_index: dict[int, int] = {}
    if profile == "iid_stratified":
        rng = random.Random(random_seed)
        by_label: dict[Any, list[int]] = {}
        for index, label in enumerate(labels):
            by_label.setdefault(label, []).append(index)
        for label_indices in by_label.values():
            randomized = list(label_indices)
            rng.shuffle(randomized)
            holdout.update(randomized[:max(1, math.ceil(len(randomized) * final_holdout_fraction))])
        development = [index for index in range(n) if index not in holdout]
        for label, label_indices in by_label.items():
            development_for_label = [index for index in label_indices if index not in holdout]
            if len(development_for_label) < cv_folds:
                raise ContractError("CLASSIFICATION_SPLIT_CLASS_SUPPORT", f"class {label!r} lacks development rows for cv_folds")
            for position, index in enumerate(development_for_label):
                fold_by_index[index] = position % cv_folds
    elif profile == "group_holdout":
        assert entities is not None
        unique_entities = list(dict.fromkeys(entities))
        if len(unique_entities) < cv_folds + 1:
            raise ContractError("CLASSIFICATION_SPLIT_GROUP_SUPPORT", "not enough entities for holdout and folds")
        count = max(1, math.ceil(len(unique_entities) * final_holdout_fraction))
        randomized_entities = list(unique_entities)
        random.Random(random_seed).shuffle(randomized_entities)
        holdout_entities = set(randomized_entities[:count])
        holdout = {index for index, entity in enumerate(entities) if entity in holdout_entities}
        development = [index for index in range(n) if index not in holdout]
        development_entities = list(dict.fromkeys(entities[index] for index in development))
        if len(development_entities) < cv_folds:
            raise ContractError("CLASSIFICATION_SPLIT_GROUP_SUPPORT", "development entities are fewer than cv_folds")
        fold_by_entity = {
            entity: position % cv_folds
            for position, entity in enumerate(development_entities)
        }
        for index in development:
            fold_by_index[index] = fold_by_entity[entities[index]]
    else:
        assert periods is not None
        holdout, development_periods, holdout_periods = _holdout_indices_for_periods(periods, final_holdout_fraction)
        if profile == "panel_new_entity":
            assert entities is not None
            if set(entities[index] for index in range(n) if index not in holdout) & set(entities[index] for index in holdout):
                raise ContractError("CLASSIFICATION_ENTITY_OVERLAP_FORBIDDEN", "new-entity profile cannot reuse an entity in holdout")
        if len(development_periods) < cv_folds + 1:
            raise ContractError("CLASSIFICATION_SPLIT_PERIOD_SUPPORT", "not enough ordered periods for warmup and folds")
        development = [index for index in range(n) if index not in holdout]
        warmup = development_periods[0]
        validation_periods = development_periods[1:]
        for index in development:
            period = periods[index]
            if period != warmup:
                fold_by_index[index] = min(cv_folds - 1, validation_periods.index(period) * cv_folds // len(validation_periods))
        if profile == "panel_known_entity_future":
            max_development = max(periods[index] for index in development)
            if any(not _strictly_after(periods[index], max_development) for index in holdout):
                raise ContractError("CLASSIFICATION_TIME_ORDER_INVALID", "panel holdout must be a future period")

    purge_records: list[dict[str, Any]] = []
    purged_indices: set[int] = set()
    if label_windows is not None:
        for index, window in enumerate(label_windows):
            _interval_overlaps(window, window, purge_gap)
            for other in range(index):
                if not _interval_overlaps(label_windows[index], label_windows[other], purge_gap):
                    continue
                if purge_gap is None:
                    raise ContractError("CLASSIFICATION_PURGE_BASIS_REQUIRED", "overlapping label windows require purge_gap")
                if index in holdout and other not in holdout:
                    victim, protected = other, index
                elif other in holdout and index not in holdout:
                    victim, protected = index, other
                else:
                    continue
                purged_indices.add(victim)
                purge_records.append(
                    {
                        "kind": "label_window",
                        "row_ref": row_refs[victim],
                        "other_row_ref": row_refs[protected],
                        "purge_gap": purge_gap,
                    }
                )

    if embargo is not None:
        assert periods is not None
        holdout_start = min(periods[index] for index in holdout)
        try:
            boundary = holdout_start - embargo
        except TypeError as exc:
            raise ContractError("CLASSIFICATION_EMBARGO_INVALID", "embargo must be subtractable from ordered periods") from exc
        for index, period in enumerate(periods):
            if index in holdout:
                continue
            try:
                within_boundary = _ordered_before(boundary, period) and _strictly_after(holdout_start, period)
            except TypeError as exc:
                raise ContractError("CLASSIFICATION_EMBARGO_INVALID", "embargo and periods must share an ordered type") from exc
            if within_boundary:
                purged_indices.add(index)
                purge_records.append(
                    {
                        "kind": "embargo",
                        "row_ref": row_refs[index],
                        "holdout_start": holdout_start,
                        "embargo": embargo,
                        "embargo_basis": embargo_basis,
                    }
                )

    if profile == "iid_stratified":
        # Purging changes the executable development population.  Rebuild the
        # folds from the surviving rows so a removed row cannot leave a fold
        # with a misleading class assignment or an accidental holdout read.
        fold_by_index = {}
        for label in dict.fromkeys(labels):
            active_for_label = [
                index
                for index, value in enumerate(labels)
                if value == label and index not in holdout and index not in purged_indices
            ]
            if len(active_for_label) < cv_folds:
                raise ContractError("CLASSIFICATION_SPLIT_CLASS_SUPPORT", f"class {label!r} lacks active rows for cv_folds")
            for position, index in enumerate(active_for_label):
                fold_by_index[index] = position % cv_folds

    for index, row_ref in enumerate(row_refs):
        if index in holdout:
            partition = "final_holdout"
        elif index in purged_indices:
            partition = "purged"
        else:
            partition = "development"
        assignments.append(
            SplitAssignment(
                row_ref=row_ref,
                partition=partition,
                cv_fold=None if partition != "development" else fold_by_index.get(index),
            )
        )

    development_indices = [index for index, item in enumerate(assignments) if item.partition == "development"]
    if len(set(labels[index] for index in development_indices)) < 2:
        raise ContractError("CLASSIFICATION_SPLIT_CLASS_SUPPORT", "development split must retain both classes")
    if profile == "iid_stratified":
        for fold in range(cv_folds):
            fold_indices = [index for index in development_indices if assignments[index].cv_fold == fold]
            if len(set(labels[index] for index in fold_indices)) < 2:
                raise ContractError("CLASSIFICATION_SPLIT_CLASS_SUPPORT", f"development fold {fold} lacks both classes")

    intervals = tuple(
        InformationIntervalV1(
            row_ref=row_refs[index],
            feature_available_at=feature_available_at[index] if feature_available_at is not None else None,
            prediction_origin=prediction_origins[index] if prediction_origins is not None else None,
            label_start=label_windows[index][0] if label_windows is not None else None,
            label_end=label_windows[index][1] if label_windows is not None else None,
            entity_ref=entities[index] if entities is not None else None,
            period_ref=periods[index] if periods is not None else None,
        )
        for index in range(n)
    )
    training_row_refs_by_fold: list[tuple[str, ...]] = []
    for fold in range(cv_folds):
        validation_indices = [
            index
            for index, assignment in enumerate(assignments)
            if assignment.partition == "development" and assignment.cv_fold == fold
        ]
        if profile in {"temporal_rolling", "panel_known_entity_future", "panel_new_entity"}:
            if not validation_indices:
                training_indices: list[int] = []
            else:
                validation_periods = [periods[index] for index in validation_indices]  # type: ignore[index]
                earliest_validation = min(validation_periods)
                training_indices = [
                    index
                    for index, assignment in enumerate(assignments)
                    if assignment.partition == "development"
                    and periods is not None
                    and _strictly_after(earliest_validation, periods[index])
                ]
        else:
            validation_set = set(validation_indices)
            training_indices = [
                index
                for index, assignment in enumerate(assignments)
                if assignment.partition == "development" and index not in validation_set
            ]
        training_row_refs_by_fold.append(tuple(row_refs[index] for index in training_indices))
    return ClassificationSplitManifestV1(
        profile=profile,
        assignments=tuple(assignments),
        intervals=intervals,
        purge_windows=tuple(purge_records),
        purge_basis="label_window_overlap" if label_windows is not None else "not_applicable",
        embargo=embargo,
        embargo_basis=embargo_basis,
        effective_parameters={
            "final_holdout_fraction": final_holdout_fraction,
            "cv_folds": cv_folds,
            "random_seed": random_seed,
            "shuffle": profile == "iid_stratified",
        },
        training_row_refs_by_fold=tuple(training_row_refs_by_fold),
    )


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
