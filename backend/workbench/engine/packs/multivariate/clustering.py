"""Deterministic, policy-explicit clustering kernels."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage as scipy_linkage
from scipy.spatial.distance import cdist

from workbench.contracts.model.multivariate import make_result_envelope

from .common import MultivariatePackError, json_native, prepare_numeric_frame


CLUSTERING_ALGORITHMS = frozenset({"kmeans", "hierarchical"})
CLUSTERING_STANDARDIZATIONS = frozenset({"none", "zscore_sample"})
CLUSTERING_SELECTIONS = frozenset({"fixed", "silhouette_candidates"})
CLUSTERING_LINKAGES = frozenset({"single", "complete", "average", "ward"})
CLUSTERING_METRICS = frozenset({"euclidean", "cityblock", "cosine"})
MAX_CLUSTER_CANDIDATES = 12
MAX_SILHOUETTE_OBSERVATIONS = 2_000


def _validate_choice(value: object, allowed: frozenset[str], name: str) -> str:
    if type(value) is not str or value not in allowed:
        raise MultivariatePackError(
            "MULTIVARIATE_UNSUPPORTED_OPTION",
            f"{name} must be one of {sorted(allowed)}",
        )
    return value


def _normalize_columns(columns: Sequence[str]) -> list[str]:
    if isinstance(columns, (str, bytes)):
        raise MultivariatePackError(
            "MULTIVARIATE_BAD_INPUT", "columns must be an array of column names"
        )
    try:
        return list(columns)
    except TypeError as exc:
        raise MultivariatePackError(
            "MULTIVARIATE_BAD_INPUT", "columns must be an array of column names"
        ) from exc


def _validate_selection(
    *,
    selection: str,
    n_clusters: int | None,
    candidate_ks: Sequence[int] | None,
    n_observations: int,
) -> list[int]:
    if selection == "fixed":
        if (
            type(n_clusters) is not int
            or not 2 <= n_clusters < n_observations
            or candidate_ks is not None
        ):
            raise MultivariatePackError(
                "MULTIVARIATE_INVALID_OPTION",
                "fixed selection requires one n_clusters and no candidate_ks",
            )
        return [n_clusters]
    if n_clusters is not None or candidate_ks is None:
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION",
            "silhouette_candidates requires candidate_ks and no n_clusters",
        )
    if isinstance(candidate_ks, (str, bytes)):
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION", "candidate_ks must be an array of integers"
        )
    values = list(candidate_ks)
    if not 1 <= len(values) <= MAX_CLUSTER_CANDIDATES:
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION",
            f"candidate_ks must contain between 1 and {MAX_CLUSTER_CANDIDATES} values",
        )
    if any(type(value) is not int or not 2 <= value < n_observations for value in values):
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION",
            "candidate_ks must contain unique integers in [2, n_observations)",
        )
    if len(set(values)) != len(values):
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION", "candidate_ks must not contain duplicates"
        )
    return values


def _prepare_values(
    frame: pd.DataFrame,
    columns: Sequence[str],
    standardization: str,
    missing_policy: str,
) -> tuple[np.ndarray, object, dict[str, object]]:
    prepared = prepare_numeric_frame(
        frame,
        _normalize_columns(columns),
        missing_policy=missing_policy,
    )
    values = prepared.frame.to_numpy(dtype=float)
    if standardization == "none":
        return values, prepared, {"method": "none"}
    means = values.mean(axis=0)
    scales = values.std(axis=0, ddof=1)
    if np.any(scales <= 0.0) or not np.isfinite(scales).all():
        raise MultivariatePackError(
            "MULTIVARIATE_NUMERIC_DEGENERACY",
            "zscore_sample requires non-constant finite columns",
        )
    return (values - means) / scales, prepared, {
        "method": "zscore_sample",
        "means": means,
        "sample_standard_deviations": scales,
    }


def _normalize_labels(labels: np.ndarray) -> np.ndarray:
    normalized: dict[int, int] = {}
    next_label = 0
    output = np.empty(labels.shape[0], dtype=int)
    for index, raw in enumerate(labels.tolist()):
        raw_int = int(raw)
        if raw_int not in normalized:
            normalized[raw_int] = next_label
            next_label += 1
        output[index] = normalized[raw_int]
    return output


def _kmeans(
    values: np.ndarray,
    n_clusters: int,
    *,
    random_state: int,
    max_iter: int,
    tol: float,
) -> tuple[np.ndarray, np.ndarray, float, int]:
    rng = np.random.default_rng(random_state)
    n_observations = values.shape[0]
    first_index = int(rng.integers(0, n_observations))
    center_indices = [first_index]
    for _ in range(1, n_clusters):
        distances = np.min(
            np.square(values[:, None, :] - values[center_indices][None, :, :]).sum(axis=2),
            axis=1,
        )
        distances[center_indices] = 0.0
        total = float(distances.sum())
        if total <= 0.0:
            unused = np.setdiff1d(np.arange(n_observations), np.asarray(center_indices))
            center_indices.append(int(rng.choice(unused)))
        else:
            center_indices.append(int(rng.choice(n_observations, p=distances / total)))
    centers = values[center_indices].copy()
    labels = np.full(n_observations, -1, dtype=int)
    iterations = 0
    for iterations in range(1, max_iter + 1):
        distances = np.square(values[:, None, :] - centers[None, :, :]).sum(axis=2)
        new_labels = np.argmin(distances, axis=1)
        new_centers = np.empty_like(centers)
        for cluster in range(n_clusters):
            members = values[new_labels == cluster]
            if len(members) == 0:
                farthest = int(np.argmax(np.min(distances, axis=1)))
                new_centers[cluster] = values[farthest]
            else:
                new_centers[cluster] = members.mean(axis=0)
        shift = float(np.max(np.linalg.norm(new_centers - centers, axis=1)))
        converged = np.array_equal(new_labels, labels) or shift <= tol
        centers = new_centers
        labels = new_labels
        if converged:
            break
    if len(np.unique(labels)) != n_clusters:
        raise MultivariatePackError(
            "MULTIVARIATE_NUMERIC_DEGENERACY",
            "k-means produced an empty cluster under the declared policy",
        )
    final_distances = np.square(values - centers[labels]).sum(axis=1)
    return labels, centers, float(final_distances.sum()), iterations


def _silhouette(values: np.ndarray, labels: np.ndarray, metric: str) -> float:
    if len(values) > MAX_SILHOUETTE_OBSERVATIONS:
        raise MultivariatePackError(
            "MULTIVARIATE_RESOURCE_BOUND",
            f"silhouette evaluation is bounded at {MAX_SILHOUETTE_OBSERVATIONS} observations",
        )
    unique_labels = np.unique(labels)
    if len(unique_labels) < 2:
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION", "silhouette requires at least two clusters"
        )
    distances = cdist(values, values, metric=metric)
    scores: list[float] = []
    for index, label in enumerate(labels):
        same = labels == label
        same[index] = False
        a = float(distances[index, same].mean()) if same.any() else 0.0
        b = min(
            float(distances[index, labels == other].mean())
            for other in unique_labels
            if other != label
        )
        denominator = max(a, b)
        scores.append((b - a) / denominator if denominator > 0.0 else 0.0)
    return float(np.mean(scores))


def _hierarchical(
    values: np.ndarray,
    *,
    n_clusters: int,
    linkage: str,
    metric: str,
) -> np.ndarray:
    matrix = scipy_linkage(values, method=linkage, metric=metric)
    labels = _normalize_labels(fcluster(matrix, t=n_clusters, criterion="maxclust"))
    if len(np.unique(labels)) != n_clusters:
        raise MultivariatePackError(
            "MULTIVARIATE_NUMERIC_DEGENERACY",
            "hierarchical clustering produced fewer clusters than requested",
        )
    return labels


def fit_clustering(
    frame: pd.DataFrame,
    columns: Sequence[str],
    *,
    algorithm: Literal["kmeans", "hierarchical"],
    standardization: Literal["none", "zscore_sample"],
    selection: Literal["fixed", "silhouette_candidates"],
    n_clusters: int | None = None,
    candidate_ks: Sequence[int] | None = None,
    random_state: int | None = None,
    linkage: Literal["single", "complete", "average", "ward"] = "ward",
    metric: Literal["euclidean", "cityblock", "cosine"] = "euclidean",
    max_iter: int = 300,
    tol: float = 1e-4,
    include_assignments: bool = False,
    max_assignment_rows: int = 500,
    missing_policy: str = "complete_case_v1",
) -> dict[str, object]:
    """Fit a declared clustering policy without hidden preprocessing or selection."""

    algorithm_name = _validate_choice(algorithm, CLUSTERING_ALGORITHMS, "algorithm")
    standardization_name = _validate_choice(
        standardization, CLUSTERING_STANDARDIZATIONS, "standardization"
    )
    selection_name = _validate_choice(selection, CLUSTERING_SELECTIONS, "selection")
    linkage_name = _validate_choice(linkage, CLUSTERING_LINKAGES, "linkage")
    metric_name = _validate_choice(metric, CLUSTERING_METRICS, "metric")
    if algorithm_name == "kmeans" and metric_name != "euclidean":
        raise MultivariatePackError(
            "MULTIVARIATE_UNSUPPORTED_OPTION",
            "kmeans uses euclidean center updates; use hierarchical clustering for another metric",
        )
    if linkage_name == "ward" and metric_name != "euclidean":
        raise MultivariatePackError(
            "MULTIVARIATE_UNSUPPORTED_OPTION", "ward linkage requires euclidean metric"
        )
    if type(include_assignments) is not bool:
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION", "include_assignments must be a boolean"
        )
    if type(max_assignment_rows) is not int or max_assignment_rows < 1:
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION", "max_assignment_rows must be positive"
        )
    if type(max_iter) is not int or not 1 <= max_iter <= 10_000:
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION", "max_iter must be in [1, 10000]"
        )
    if type(tol) not in (int, float) or not np.isfinite(tol) or tol <= 0.0:
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION", "tol must be a finite positive number"
        )
    if algorithm_name == "kmeans":
        if type(random_state) is not int or random_state < 0:
            raise MultivariatePackError(
                "MULTIVARIATE_INVALID_OPTION",
                "kmeans requires a non-negative integer random_state",
            )
    elif random_state is not None:
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION",
            "hierarchical clustering does not accept random_state",
        )
    values, prepared, standardization_parameters = _prepare_values(
        frame, columns, standardization_name, missing_policy
    )
    candidate_values = _validate_selection(
        selection=selection_name,
        n_clusters=n_clusters,
        candidate_ks=candidate_ks,
        n_observations=len(values),
    )
    candidate_metrics: list[dict[str, object]] = []
    fitted: tuple[np.ndarray, np.ndarray | None, float | None, int | None] | None = None
    for candidate in candidate_values:
        candidate_seed: int | None = None
        if algorithm_name == "kmeans":
            candidate_seed = int(random_state) + candidate
            labels, centers, inertia, iterations = _kmeans(
                values,
                candidate,
                random_state=candidate_seed,
                max_iter=max_iter,
                tol=float(tol),
            )
        else:
            labels = _hierarchical(
                values,
                n_clusters=candidate,
                linkage=linkage_name,
                metric=metric_name,
            )
            centers, inertia, iterations = None, None, None
        silhouette = _silhouette(values, labels, metric_name)
        candidate_metrics.append(
            {
                "n_clusters": candidate,
                "silhouette": silhouette,
                "inertia": inertia,
                "iterations": iterations,
                "random_state": candidate_seed,
            }
        )
        if fitted is None:
            fitted = labels, centers, inertia, iterations
    if selection_name == "silhouette_candidates":
        winner = max(
            candidate_metrics,
            key=lambda row: (float(row["silhouette"]), -int(row["n_clusters"])),
        )
        winner_k = int(winner["n_clusters"])
        if algorithm_name == "kmeans":
            labels, centers, inertia, iterations = _kmeans(
                values,
                winner_k,
                random_state=int(random_state) + winner_k,
                max_iter=max_iter,
                tol=float(tol),
            )
        else:
            labels = _hierarchical(
                values,
                n_clusters=winner_k,
                linkage=linkage_name,
                metric=metric_name,
            )
            centers, inertia, iterations = None, None, None
    else:
        labels, centers, inertia, iterations = fitted
        winner_k = candidate_values[0]
    result: dict[str, object] = {
        "algorithm": algorithm_name,
        "standardization": standardization_name,
        "standardization_parameters": standardization_parameters,
        "selection": selection_name,
        "candidate_ks": candidate_values,
        "selected_by": (
            "maximum_silhouette_tie_break_smallest_k"
            if selection_name == "silhouette_candidates"
            else "declared_fixed_k"
        ),
        "n_clusters": winner_k,
        "candidate_metrics": candidate_metrics,
        "silhouette": next(
            float(row["silhouette"])
            for row in candidate_metrics
            if int(row["n_clusters"]) == winner_k
        ),
        "inertia": inertia,
        "iterations": iterations,
        "random_state": random_state,
        "max_iter": max_iter,
        "tol": float(tol),
        "assignments_available": include_assignments,
        "missing_policy": prepared.missing_policy,
        "retained_positions": list(prepared.retained_positions),
    }
    if algorithm_name == "kmeans":
        result["centers"] = centers
    else:
        result["linkage"] = linkage_name
        result["metric"] = metric_name
    if include_assignments:
        bounded_count = min(max_assignment_rows, len(labels))
        result["assignments"] = labels[:bounded_count]
        result["assignments_row_count"] = bounded_count
        result["assignments_truncated"] = bounded_count < len(labels)
    return make_result_envelope(
        operation_id="multivariate.clustering",
        status="completed",
        reason_code="ANALYSIS_COMPLETED",
        n_observations=prepared.n_observations,
        columns=prepared.columns,
        result=json_native(result),
    )


__all__ = [
    "CLUSTERING_ALGORITHMS",
    "CLUSTERING_LINKAGES",
    "CLUSTERING_METRICS",
    "CLUSTERING_SELECTIONS",
    "CLUSTERING_STANDARDIZATIONS",
    "fit_clustering",
]
