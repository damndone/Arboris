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


# ---------------------------------------------------------------------------
# v1.8.9 classification split kernel
#
# The legacy function above is intentionally left semantically unchanged.  A
# classification task must opt into one of the explicit profiles below; it
# never falls back to the legacy random planner.


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
            "profile_version": 1,
            "row_identity": "declared_row_ref_v1",
            "assignments": [item.to_dict() for item in self.assignments],
            "intervals": [item.to_dict() for item in self.intervals],
            "purge_windows": list(self.purge_windows),
            "purge_basis": self.purge_basis,
            "embargo": self.embargo,
            "embargo_basis": self.embargo_basis,
            "effective_parameters": self.effective_parameters,
            "training_row_refs_by_fold": [list(row_refs) for row_refs in self.training_row_refs_by_fold],
        }

    @property
    def content_hash(self) -> str:
        encoded = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def rows(self, *, partition: str, fold: int | None = None) -> tuple[str, ...]:
        return tuple(
            item.row_ref
            for item in self.assignments
            if item.partition == partition and (fold is None or item.cv_fold == fold)
        )

    def training_rows_for_fold(self, fold: int) -> tuple[str, ...]:
        """Return the immutable training role for one validation fold.

        Ordered profiles materialize a forward-only role: every returned row
        is strictly earlier than the earliest period in that fold's
        validation rows.  IID/group profiles retain the historical
        complement-of-validation-fold semantics.
        """

        if isinstance(fold, bool) or not isinstance(fold, int):
            raise ContractError("CLASSIFICATION_SPLIT_FOLD_INVALID", "fold must be an integer")
        if fold < 0 or fold >= len(self.training_row_refs_by_fold):
            raise ContractError("CLASSIFICATION_SPLIT_FOLD_INVALID", "fold is outside the manifest")
        return self.training_row_refs_by_fold[fold]


_CLASSIFICATION_PROFILES = frozenset(
    {
        "iid_stratified",
        "group_holdout",
        "temporal_rolling",
        "panel_known_entity_future",
        "panel_new_entity",
    }
)


def _classification_order(left: Any, right: Any, *, code: str = "CLASSIFICATION_TIME_ORDER_INVALID") -> int:
    if left is None or right is None:
        raise ContractError(code, "ordered values cannot be missing")
    try:
        if left < right:
            return -1
        if left > right:
            return 1
        return 0
    except (TypeError, ValueError) as error:
        raise ContractError(code, "ordered values must share a comparable type") from error


def _classification_sorted_unique(values: Sequence[Any]) -> list[Any]:
    if any(value is None for value in values):
        raise ContractError("CLASSIFICATION_PERIOD_INVALID", "period values cannot be missing")
    try:
        ordered = sorted(values)
    except (TypeError, ValueError) as error:
        raise ContractError("CLASSIFICATION_TIME_ORDER_INVALID", "period values are not orderable") from error
    unique: list[Any] = []
    for value in ordered:
        if not unique or _classification_order(unique[-1], value, code="CLASSIFICATION_PERIOD_INVALID") != 0:
            unique.append(value)
    return unique


def _classification_interval_overlaps(
    left: tuple[Any, Any],
    right: tuple[Any, Any],
    gap: Any | None,
) -> bool:
    if not isinstance(left, (tuple, list)) or not isinstance(right, (tuple, list)):
        raise ContractError("CLASSIFICATION_LABEL_WINDOW_INVALID", "label windows must be two-item intervals")
    if len(left) != 2 or len(right) != 2:
        raise ContractError("CLASSIFICATION_LABEL_WINDOW_INVALID", "label windows must be two-item intervals")
    left_start, left_end = left
    right_start, right_end = right
    if _classification_order(left_start, left_end, code="CLASSIFICATION_LABEL_WINDOW_INVALID") > 0:
        raise ContractError("CLASSIFICATION_LABEL_WINDOW_INVALID", "label windows must be ordered intervals")
    if _classification_order(right_start, right_end, code="CLASSIFICATION_LABEL_WINDOW_INVALID") > 0:
        raise ContractError("CLASSIFICATION_LABEL_WINDOW_INVALID", "label windows must be ordered intervals")
    if gap is None:
        # No declared gap means compare the original intervals.  Do not add a
        # numeric zero to datetime/date values: that would invent a type
        # requirement unrelated to the declared contract.
        left_end_with_gap = left_end
        right_end_with_gap = right_end
    else:
        try:
            if gap < 0:
                raise ContractError("CLASSIFICATION_PURGE_GAP_INVALID", "purge_gap cannot be negative")
        except TypeError as error:
            raise ContractError("CLASSIFICATION_PURGE_GAP_INVALID", "purge_gap is not comparable") from error
        try:
            left_end_with_gap = left_end + gap
            right_end_with_gap = right_end + gap
        except (TypeError, ValueError) as error:
            raise ContractError("CLASSIFICATION_PURGE_GAP_INVALID", "purge_gap cannot be applied to label windows") from error
    return not (
        _classification_order(right_start, left_end_with_gap) > 0
        or _classification_order(left_start, right_end_with_gap) > 0
    )


def _classification_require_aligned(
    values: Sequence[Any] | None,
    *,
    n: int,
    name: str,
) -> None:
    if values is not None and len(values) != n:
        raise ContractError("CLASSIFICATION_SPLIT_ALIGNMENT_INVALID", f"{name} must align with row_refs")


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
    groups: Sequence[str] | None = None,
) -> ClassificationSplitManifestV1:
    """Build an auditable classification split with explicit safety predicates."""

    if profile not in _CLASSIFICATION_PROFILES:
        raise ContractError("CLASSIFICATION_SPLIT_PROFILE_INVALID", f"unknown classification profile {profile!r}")
    if groups is not None:
        if entities is not None and tuple(entities) != tuple(groups):
            raise ContractError("CLASSIFICATION_ENTITY_IDENTITY_INVALID", "entities and groups disagree")
        entities = groups
    n = len(row_refs)
    if n < 4 or len(labels) != n or any(not isinstance(row, str) or not row.strip() for row in row_refs):
        raise ContractError("CLASSIFICATION_ROW_IDENTITY_INVALID", "row_refs and labels must align")
    if len(set(row_refs)) != n:
        raise ContractError("CLASSIFICATION_ROW_IDENTITY_INVALID", "row_refs must be unique")
    if not isinstance(cv_folds, int) or isinstance(cv_folds, bool) or cv_folds < 2:
        raise ContractError("CLASSIFICATION_SPLIT_PARAMETERS_INVALID", "cv_folds must be at least two")
    if isinstance(final_holdout_fraction, bool) or not isinstance(final_holdout_fraction, (int, float)):
        raise ContractError("CLASSIFICATION_SPLIT_PARAMETERS_INVALID", "holdout fraction must be numeric")
    if not 0 < float(final_holdout_fraction) < 1:
        raise ContractError("CLASSIFICATION_SPLIT_PARAMETERS_INVALID", "holdout fraction must be between zero and one")
    if not isinstance(random_seed, int) or isinstance(random_seed, bool) or random_seed < 0:
        raise ContractError("CLASSIFICATION_SEED_INVALID", "random_seed must be a non-negative integer")
    try:
        labels_set = set(labels)
    except TypeError as error:
        raise ContractError("CLASSIFICATION_LABEL_INVALID", "labels must be hashable scalar values") from error
    if len(labels_set) < 2:
        raise ContractError("CLASSIFICATION_SPLIT_CLASS_SUPPORT", "classification split requires at least two classes")

    if embargo is not None and (not isinstance(embargo_basis, str) or not embargo_basis.strip()):
        raise ContractError("CLASSIFICATION_EMBARGO_BASIS_REQUIRED", "embargo requires an explicit basis")
    if embargo is not None and profile not in {
        "temporal_rolling",
        "panel_known_entity_future",
        "panel_new_entity",
    }:
        raise ContractError("CLASSIFICATION_EMBARGO_PROFILE_INVALID", "embargo is only valid for ordered profiles")
    if profile in {"group_holdout", "panel_known_entity_future", "panel_new_entity"} and entities is None:
        raise ContractError("CLASSIFICATION_ENTITY_REQUIRED", "this split profile requires entity refs")
    if profile in {"temporal_rolling", "panel_known_entity_future", "panel_new_entity"} and periods is None:
        raise ContractError("CLASSIFICATION_PERIOD_REQUIRED", "this split profile requires ordered periods")
    if profile in {"temporal_rolling", "panel_known_entity_future", "panel_new_entity"} and (
        feature_available_at is None or prediction_origins is None
    ):
        raise ContractError(
            "CLASSIFICATION_INFORMATION_SET_INCOMPLETE",
            "ordered profiles require feature availability and prediction origins",
        )
    if profile in {"temporal_rolling", "panel_known_entity_future", "panel_new_entity"} and label_windows is None:
        raise ContractError(
            "CLASSIFICATION_LABEL_WINDOW_REQUIRED",
            "ordered profiles require row-level label start/end intervals",
        )
    if (feature_available_at is None) != (prediction_origins is None):
        raise ContractError("CLASSIFICATION_INFORMATION_SET_INCOMPLETE", "availability and origin must be declared together")

    for values, name in (
        (feature_available_at, "feature_available_at"),
        (prediction_origins, "prediction_origins"),
        (entities, "entities"),
        (periods, "periods"),
    ):
        _classification_require_aligned(values, n=n, name=name)
    _classification_require_aligned(label_windows, n=n, name="label_windows")
    if entities is not None and any(not isinstance(entity, str) or not entity.strip() for entity in entities):
        raise ContractError("CLASSIFICATION_ENTITY_IDENTITY_INVALID", "entity refs must be non-empty text")

    if feature_available_at is not None and prediction_origins is not None:
        for row_ref, available, origin in zip(row_refs, feature_available_at, prediction_origins, strict=True):
            if _classification_order(available, origin, code="CLASSIFICATION_INFORMATION_SET_VIOLATION") > 0:
                raise ContractError(
                    "CLASSIFICATION_INFORMATION_SET_VIOLATION",
                    f"feature availability is after prediction origin for {row_ref}",
                )

    ordered_periods: list[Any] | None = None
    if periods is not None:
        ordered_periods = _classification_sorted_unique(periods)

    holdout: set[int] = set()
    fold_by_index: dict[int, int] = {}
    if profile == "iid_stratified":
        rng = random.Random(random_seed)
        by_label: dict[Any, list[int]] = {}
        for index, label in enumerate(labels):
            by_label.setdefault(label, []).append(index)
        for label_indices in by_label.values():
            candidates = list(label_indices)
            rng.shuffle(candidates)
            holdout.update(candidates[: max(1, math.ceil(len(candidates) * float(final_holdout_fraction)))])
        for label in by_label:
            active = [index for index in by_label[label] if index not in holdout]
            if len(active) < cv_folds:
                raise ContractError("CLASSIFICATION_SPLIT_CLASS_SUPPORT", "class lacks development rows for cv_folds")
            for position, index in enumerate(active):
                fold_by_index[index] = position % cv_folds
    elif profile == "group_holdout":
        assert entities is not None
        unique_entities = list(dict.fromkeys(entities))
        if len(unique_entities) < cv_folds + 1:
            raise ContractError("CLASSIFICATION_SPLIT_GROUP_SUPPORT", "not enough entities for holdout and folds")
        randomized_entities = list(unique_entities)
        random.Random(random_seed).shuffle(randomized_entities)
        holdout_entities = set(
            randomized_entities[: max(1, math.ceil(len(unique_entities) * float(final_holdout_fraction)))]
        )
        holdout = {index for index, entity in enumerate(entities) if entity in holdout_entities}
        development_entities = [entity for entity in unique_entities if entity not in holdout_entities]
        if len(development_entities) < cv_folds:
            raise ContractError("CLASSIFICATION_SPLIT_GROUP_SUPPORT", "development entities are fewer than cv_folds")
        fold_by_entity = {entity: position % cv_folds for position, entity in enumerate(development_entities)}
        fold_by_index = {
            index: fold_by_entity[entities[index]]
            for index in range(n)
            if index not in holdout
        }
    else:
        assert periods is not None and ordered_periods is not None
        holdout_period_count = max(1, math.ceil(len(ordered_periods) * float(final_holdout_fraction)))
        holdout_periods = set(ordered_periods[-holdout_period_count:])
        development_periods = ordered_periods[:-holdout_period_count]
        holdout = {index for index, period in enumerate(periods) if period in holdout_periods}
        warmup = development_periods[0]
        validation_periods = development_periods[1:]
        if profile == "panel_new_entity":
            assert entities is not None
            development_entities = {entities[index] for index in range(n) if index not in holdout}
            holdout_entities = {entities[index] for index in holdout}
            if development_entities & holdout_entities:
                raise ContractError(
                    "CLASSIFICATION_ENTITY_OVERLAP_FORBIDDEN",
                    "new-entity profile cannot reuse an entity in holdout",
                )
        if len(development_periods) < cv_folds + 1:
            raise ContractError(
                "CLASSIFICATION_SPLIT_PERIOD_SUPPORT",
                "ordered development data needs one warmup period and cv_folds validation periods",
            )
        fold_by_period = {
            period: min(cv_folds - 1, position * cv_folds // len(validation_periods))
            for position, period in enumerate(validation_periods)
        }
        for index, period in enumerate(periods):
            if index not in holdout and period != warmup:
                fold_by_index[index] = fold_by_period[period]
        if profile == "panel_known_entity_future":
            development_entities = {entities[index] for index in range(n) if index not in holdout}
            holdout_entities = {entities[index] for index in holdout}
            if not holdout_entities.issubset(development_entities):
                raise ContractError(
                    "CLASSIFICATION_KNOWN_ENTITY_VIOLATION",
                    "known-entity future holdout contains an entity absent from development",
                )
            max_development = max(development_periods)
            if any(_classification_order(periods[index], max_development) <= 0 for index in holdout):
                raise ContractError("CLASSIFICATION_TIME_ORDER_INVALID", "panel holdout must be a future period")

    preliminary_partition = {
        index: ("final_holdout" if index in holdout else "development")
        for index in range(n)
    }
    preliminary_assignment = {
        index: SplitAssignment(
            row_ref=row_refs[index],
            partition=preliminary_partition[index],
            cv_fold=None if index in holdout else fold_by_index.get(index),
        )
        for index in range(n)
    }

    purge_records: list[dict[str, Any]] = []
    purged_indices: set[int] = set()
    if label_windows is not None:
        for window in label_windows:
            _classification_interval_overlaps(window, window, purge_gap)
        for left_index in range(n):
            for right_index in range(left_index):
                if not _classification_interval_overlaps(label_windows[left_index], label_windows[right_index], purge_gap):
                    continue
                left_assignment = preliminary_assignment[left_index]
                right_assignment = preliminary_assignment[right_index]
                left_role = (left_assignment.partition, left_assignment.cv_fold)
                right_role = (right_assignment.partition, right_assignment.cv_fold)
                if left_role == right_role:
                    continue
                if purge_gap is None:
                    raise ContractError(
                        "CLASSIFICATION_PURGE_BASIS_REQUIRED",
                        "cross-partition overlapping label windows require purge_gap",
                    )
                if left_index in holdout and right_index not in holdout:
                    victim, protected = right_index, left_index
                elif right_index in holdout and left_index not in holdout:
                    victim, protected = left_index, right_index
                elif periods is not None and _classification_order(periods[left_index], periods[right_index]) > 0:
                    victim, protected = right_index, left_index
                else:
                    victim, protected = right_index, left_index
                if victim in holdout:
                    continue
                purged_indices.add(victim)
                purge_records.append(
                    {
                        "kind": "label_window",
                        "row_ref": row_refs[victim],
                        "other_row_ref": row_refs[protected],
                        "purge_gap": purge_gap,
                        "basis": "label_window_overlap",
                    }
                )

    if embargo is not None:
        assert periods is not None
        try:
            if embargo < 0:
                raise ContractError("CLASSIFICATION_EMBARGO_INVALID", "embargo cannot be negative")
            holdout_start = min(periods[index] for index in holdout)
            boundary = holdout_start - embargo
        except ContractError:
            raise
        except (TypeError, ValueError) as error:
            raise ContractError("CLASSIFICATION_EMBARGO_INVALID", "embargo and periods must share an ordered type") from error
        for index, period in enumerate(periods):
            if index in holdout:
                continue
            if _classification_order(period, boundary) >= 0 and _classification_order(period, holdout_start) < 0:
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

    # A group purge is entity-level: a single surviving row cannot keep a
    # group-derived feature visible after another row of the same entity is
    # removed.  This never changes the legacy split planner.
    if profile == "group_holdout" and entities is not None and purged_indices:
        purged_entities = {entities[index] for index in purged_indices if index not in holdout}
        purged_indices.update(
            index for index, entity in enumerate(entities) if entity in purged_entities and index not in holdout
        )

    if profile == "iid_stratified":
        fold_by_index = {}
        for label in dict.fromkeys(labels):
            active = [
                index
                for index, value in enumerate(labels)
                if value == label and index not in holdout and index not in purged_indices
            ]
            if len(active) < cv_folds:
                raise ContractError("CLASSIFICATION_SPLIT_CLASS_SUPPORT", "class lacks active rows for cv_folds")
            for position, index in enumerate(active):
                fold_by_index[index] = position % cv_folds

    assignments: list[SplitAssignment] = []
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
    elif profile == "group_holdout":
        if any(not any(assignments[index].cv_fold == fold for index in development_indices) for fold in range(cv_folds)):
            raise ContractError("CLASSIFICATION_SPLIT_GROUP_SUPPORT", "a development fold has no group support")

    training_row_refs_by_fold: list[tuple[str, ...]] = []
    for fold in range(cv_folds):
        validation_indices = [
            index
            for index in development_indices
            if assignments[index].cv_fold == fold
        ]
        if not validation_indices:
            # Purge/embargo may remove every row from a planned fold.  Keep
            # the historical manifest-construction semantics and expose an
            # empty role; the execution layer can then report the missing
            # validation evidence instead of making the split builder reject
            # an otherwise auditable purge receipt.
            training_row_refs_by_fold.append(())
            continue
        if profile in {"temporal_rolling", "panel_known_entity_future", "panel_new_entity"}:
            assert periods is not None
            validation_start = min(periods[index] for index in validation_indices)
            training_indices = [
                index
                for index in development_indices
                if _classification_order(periods[index], validation_start) < 0
            ]
        else:
            training_indices = [
                index
                for index in development_indices
                if assignments[index].cv_fold != fold
            ]
        if not training_indices:
            raise ContractError("CLASSIFICATION_SPLIT_SUPPORT", f"development fold {fold} has no training rows")
        training_row_refs_by_fold.append(tuple(row_refs[index] for index in training_indices))

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
    return ClassificationSplitManifestV1(
        profile=profile,
        assignments=tuple(assignments),
        intervals=intervals,
        purge_windows=tuple(purge_records),
        purge_basis="label_window_overlap" if label_windows is not None else "not_applicable",
        embargo=embargo,
        embargo_basis=embargo_basis,
        effective_parameters={
            "final_holdout_fraction": float(final_holdout_fraction),
            "cv_folds": cv_folds,
            "random_seed": random_seed,
            "shuffle": profile == "iid_stratified",
            "profile_version": 1,
            "purge_gap": purge_gap,
            "feature_availability_binding": feature_available_at is not None,
        },
        training_row_refs_by_fold=tuple(training_row_refs_by_fold),
    )
