"""Typed Logistic Regression and Random Forest adapters.

Adapters own estimator construction only.  Split selection, preprocessing,
calibration and policy decisions remain in the classification protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any, Callable
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression

from workbench.providers.catalog import load_builtin_catalog
from workbench.canonical import sha256_canonical

from .contracts import ContractError


CLASSIFICATION_PROVIDER_ID = "workbench.classification_ml"
CLASSIFICATION_RUNTIME_ADAPTER_ID = "workbench.classification_ml.adapter"
CLASSIFICATION_EXECUTOR_REF = "executor:workbench.classification_ml.adapter"
CLASSIFICATION_PRODUCTION_ENTRYPOINT = "workbench.prediction.run_classification_model_v189"


def _numeric_matrix(frame: pd.DataFrame) -> np.ndarray:
    if not isinstance(frame, pd.DataFrame) or not frame.columns.tolist():
        raise ContractError("CLASSIFICATION_FEATURES_REQUIRED", "adapter features must be a non-empty DataFrame")
    unsupported = [
        str(column)
        for column in frame.columns
        if not pd.api.types.is_numeric_dtype(frame[column])
    ]
    if unsupported:
        raise ContractError(
            "CLASSIFICATION_FEATURE_TYPE_BLOCKED",
            f"non-numeric feature columns require an explicit typed preprocessing recipe: {unsupported}",
        )
    try:
        matrix = frame.to_numpy(dtype=float, copy=True)
    except (TypeError, ValueError) as exc:
        raise ContractError("CLASSIFICATION_FEATURE_TYPE_BLOCKED", "features must be numeric") from exc
    if not np.isfinite(matrix).all():
        raise ContractError("CLASSIFICATION_FEATURE_TYPE_BLOCKED", "missing or non-finite features require a fold-local recipe")
    return matrix


@dataclass(frozen=True)
class AdapterDeclarationV1:
    model_id: str
    version: str
    parameter_schema: dict[str, Any]
    explanation_kinds: tuple[str, ...]
    resource_class: str
    supports_weight: bool
    build_estimator: Callable[[int, dict[str, Any]], Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": self.version,
            "parameter_schema": self.parameter_schema,
            "explanation_kinds": list(self.explanation_kinds),
            "resource_class": self.resource_class,
            "supports_weight": self.supports_weight,
        }


class ClassificationAdapterV1:
    declaration: AdapterDeclarationV1

    def __init__(self, *, seed: int = 0, parameters: dict[str, Any] | None = None):
        self.seed = seed
        self.parameters = dict(parameters or {})
        self.estimator: Any | None = None
        self._feature_names: tuple[str, ...] = ()
        self._classes: tuple[Any, ...] = ()
        self._warnings: tuple[str, ...] = ()

    @property
    def supports_weight(self) -> bool:
        return self.declaration.supports_weight

    @property
    def feature_names(self) -> tuple[str, ...]:
        if not self._feature_names:
            raise ContractError("CLASSIFICATION_ADAPTER_NOT_FIT", "feature names are unavailable before fit")
        return self._feature_names

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "model_id": self.declaration.model_id,
            "version": self.declaration.version,
            "random_seed": self.seed,
            "actual_parameters": dict(self.parameters),
            "warnings": list(self._warnings),
            "class_order": list(self._classes),
            "supports_weight": self.supports_weight,
        }

    @property
    def resource_estimate(self) -> dict[str, Any]:
        return {"resource_class": self.declaration.resource_class, "max_cpu_seconds": self.parameters.get("max_cpu_seconds", 30)}

    @property
    def explanation_capabilities(self) -> tuple[str, ...]:
        return self.declaration.explanation_kinds

    def fit(self, features: pd.DataFrame, target: Any, *, sample_weight: Any | None = None) -> "ClassificationAdapterV1":
        matrix = _numeric_matrix(features)
        labels = np.asarray(target)
        if labels.ndim != 1 or len(labels) != len(matrix):
            raise ContractError("CLASSIFICATION_TARGET_ALIGNMENT", "target must align with feature rows")
        classes = tuple(dict.fromkeys(labels.tolist()))
        if len(classes) < 2:
            raise ContractError("CLASSIFICATION_SINGLE_CLASS", "classification fit requires at least two classes")
        if sample_weight is not None:
            weights = np.asarray(sample_weight, dtype=float)
            if (
                len(weights) != len(labels)
                or not np.isfinite(weights).all()
                or (weights < 0).any()
                or float(weights.sum()) <= 0
            ):
                raise ContractError("CLASSIFICATION_WEIGHT_INVALID", "sample_weight must be finite, non-negative, positive and aligned")
        else:
            weights = None
        try:
            estimator = self.declaration.build_estimator(self.seed, self.parameters)
            with warnings.catch_warnings(record=True) as captured:
                warnings.simplefilter("always")
                if weights is None:
                    estimator.fit(matrix, labels)
                else:
                    estimator.fit(matrix, labels, sample_weight=weights)
            convergence = [item for item in captured if issubclass(item.category, ConvergenceWarning)]
            if convergence:
                raise ContractError("CLASSIFICATION_NONCONVERGENCE", str(convergence[0].message))
            observed_classes = tuple(estimator.classes_.tolist())
        except ContractError:
            raise
        except (TypeError, ValueError, RuntimeError) as exc:
            raise ContractError("CLASSIFICATION_ADAPTER_FIT_FAILED", "typed estimator fit failed") from exc
        if set(observed_classes) != set(classes) or len(observed_classes) != len(classes):
            raise ContractError("CLASSIFICATION_CLASS_ORDER_MISMATCH", "estimator class order does not match target classes")
        self.estimator = estimator
        self._feature_names = tuple(str(column) for column in features.columns)
        self._classes = observed_classes
        self._warnings = tuple(str(item.message) for item in captured)
        return self

    def _require_fit(self) -> Any:
        if self.estimator is None:
            raise ContractError("CLASSIFICATION_ADAPTER_NOT_FIT", "adapter must be fit before prediction")
        return self.estimator

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        estimator = self._require_fit()
        matrix = _numeric_matrix(features)
        probabilities = np.asarray(estimator.predict_proba(matrix), dtype=float)
        if probabilities.ndim != 2 or probabilities.shape[1] != len(self._classes) or not np.isfinite(probabilities).all():
            raise ContractError("CLASSIFICATION_PROBABILITY_INVALID", "adapter did not return finite class probabilities")
        if not np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-8):
            raise ContractError("CLASSIFICATION_PROBABILITY_INVALID", "class probabilities must sum to one")
        if tuple(estimator.classes_.tolist()) != self._classes:
            raise ContractError("CLASSIFICATION_CLASS_ORDER_MISMATCH", "prediction class order changed after fit")
        return probabilities

    def predict_at_threshold(
        self,
        features: pd.DataFrame,
        *,
        threshold: float,
        positive_class: Any | None = None,
    ) -> np.ndarray:
        if not 0 <= threshold <= 1:
            raise ContractError("CLASSIFICATION_THRESHOLD_INVALID", "threshold must be between zero and one")
        probabilities = self.predict_proba(features)
        if len(self._classes) != 2:
            raise ContractError("CLASSIFICATION_THRESHOLD_BINARY_ONLY", "threshold prediction requires a binary adapter")
        positive_index = 1 if positive_class is None else next(
            (index for index, value in enumerate(self._classes) if value == positive_class),
            None,
        )
        if positive_index is None:
            raise ContractError("CLASSIFICATION_POSITIVE_CLASS_INVALID", "positive class is not in adapter class order")
        negative_index = 1 - positive_index
        return np.where(probabilities[:, positive_index] >= threshold, self._classes[positive_index], self._classes[negative_index])


class LogisticRegressionAdapterV1(ClassificationAdapterV1):
    declaration = AdapterDeclarationV1(
        model_id="logistic_regression",
        version="1.0",
        parameter_schema={"C": {"type": "number", "minimum": 0.0001, "maximum": 1000.0}},
        explanation_kinds=("permutation_importance", "coefficient_direction"),
        resource_class="small",
        supports_weight=True,
        build_estimator=lambda seed, params: LogisticRegression(
            C=float(params.get("C", 1.0)),
            solver="lbfgs",
            penalty="l2",
            max_iter=int(params.get("max_iter", 200)),
            class_weight=None,
            random_state=seed,
        ),
    )


class RandomForestAdapterV1(ClassificationAdapterV1):
    declaration = AdapterDeclarationV1(
        model_id="random_forest",
        version="1.0",
        parameter_schema={
            "n_estimators": {"type": "integer", "minimum": 10, "maximum": 500},
            "max_depth": {"type": "integer", "minimum": 1, "maximum": 32},
        },
        explanation_kinds=("permutation_importance", "native_feature_importance"),
        resource_class="bounded",
        supports_weight=True,
        build_estimator=lambda seed, params: RandomForestClassifier(
            n_estimators=int(params.get("n_estimators", 100)),
            max_depth=int(params.get("max_depth", 8)),
            min_samples_leaf=int(params.get("min_samples_leaf", 1)),
            max_features=params.get("max_features", "sqrt"),
            n_jobs=1,
            random_state=seed,
            class_weight=None,
        ),
    )


_ADAPTERS = {
    "logistic_regression": LogisticRegressionAdapterV1,
    "random_forest": RandomForestAdapterV1,
}


def _classification_provider_declaration(catalog: Any) -> tuple[Any, Any]:
    from workbench.agent.trusted_executor_registry import TrustedExecutorRegistryError

    providers = tuple(getattr(catalog, "providers", ()))
    matches = [provider for provider in providers if provider.provider_id == CLASSIFICATION_PROVIDER_ID]
    if len(matches) != 1:
        raise TrustedExecutorRegistryError(
            "CLASSIFICATION_PROVIDER_DECLARATION_INVALID",
            "classification provider declaration must be unique",
        )
    declarations = tuple(matches[0].adapter_declarations)
    matching = [declaration for declaration in declarations if declaration.adapter_id == CLASSIFICATION_RUNTIME_ADAPTER_ID]
    if len(matching) != 1 or matching[0].executor_ref != CLASSIFICATION_EXECUTOR_REF:
        raise TrustedExecutorRegistryError(
            "CLASSIFICATION_PROVIDER_DECLARATION_INVALID",
            "classification adapter declaration identity is not the production runtime identity",
        )
    return matches[0], matching[0]


def _validate_classification_runtime_request(request: Mapping[str, Any]) -> Mapping[str, Any]:
    from workbench.agent.trusted_executor_registry import TrustedExecutorRegistryError

    if not isinstance(request, Mapping):
        raise TrustedExecutorRegistryError("RUNTIME_REQUEST_INVALID", "classification runtime request must be a mapping")
    model_id = request.get("model_id")
    if type(model_id) is not str or model_id not in _ADAPTERS:
        raise TrustedExecutorRegistryError("RUNTIME_REQUEST_INVALID", "classification runtime request has an unsupported model_id")
    return {"model_id": model_id}


def _execute_classification_runtime_binding(context: Any, request: Mapping[str, Any]) -> Mapping[str, Any]:
    model_id = request["model_id"]
    declaration = _ADAPTERS[model_id].declaration
    return {
        "provider_id": CLASSIFICATION_PROVIDER_ID,
        "adapter_id": CLASSIFICATION_RUNTIME_ADAPTER_ID,
        "executor_ref": CLASSIFICATION_EXECUTOR_REF,
        "production_entrypoint": CLASSIFICATION_PRODUCTION_ENTRYPOINT,
        "model_id": model_id,
        "adapter_version": declaration.version,
        "execution_instance_hash": context.execution_instance_hash,
    }


def _validate_classification_runtime_result(result: Mapping[str, Any]) -> None:
    from workbench.agent.trusted_executor_registry import TrustedExecutorRegistryError

    expected = {
        "provider_id": CLASSIFICATION_PROVIDER_ID,
        "adapter_id": CLASSIFICATION_RUNTIME_ADAPTER_ID,
        "executor_ref": CLASSIFICATION_EXECUTOR_REF,
        "production_entrypoint": CLASSIFICATION_PRODUCTION_ENTRYPOINT,
    }
    if not isinstance(result, Mapping) or any(result.get(key) != value for key, value in expected.items()):
        raise TrustedExecutorRegistryError("RUNTIME_RESULT_INVALID", "classification runtime result identity is inconsistent")
    if type(result.get("model_id")) is not str or result["model_id"] not in _ADAPTERS:
        raise TrustedExecutorRegistryError("RUNTIME_RESULT_INVALID", "classification runtime result model_id is invalid")


def classification_runtime_registry(catalog: Any | None = None) -> TrustedExecutorRegistry:
    """Build the server-owned classification runtime join.

    The JSON manifest contributes only opaque contract identities.  This
    factory supplies the trusted callable and binds it to the fixed builtin
    catalog before a production entrypoint may accept the registry.
    """

    from workbench.agent.trusted_executor_registry import (
        ProviderRuntimeContributionV1,
        TrustedExecutorRegistry,
    )

    source_catalog = load_builtin_catalog() if catalog is None else catalog
    provider, declaration = _classification_provider_declaration(source_catalog)
    contribution = ProviderRuntimeContributionV1(
        provider_id=provider.provider_id,
        adapter_id=declaration.adapter_id,
        executor_ref=declaration.executor_ref,
        owner="workbench.server.classification",
        signature="workbench.classification_ml.runtime.v1",
        effect="read_only",
        request_contract_ref=declaration.request_schema_ref,
        result_contract_refs=declaration.output_refs,
        executor=_execute_classification_runtime_binding,
        request_validator=_validate_classification_runtime_request,
        result_validator=_validate_classification_runtime_result,
        metadata={
            "production_entrypoint": CLASSIFICATION_PRODUCTION_ENTRYPOINT,
            "provider_id": CLASSIFICATION_PROVIDER_ID,
            "adapter_id": CLASSIFICATION_RUNTIME_ADAPTER_ID,
        },
    )
    if len(tuple(source_catalog.providers)) == 1:
        bind_catalog = source_catalog
    else:
        from workbench.contracts.common.contract_ref import ContractRefResolverV1
        from workbench.providers.catalog import ProviderCatalogV1

        bind_catalog = ProviderCatalogV1(
            providers=(provider,),
            source_filenames=("classification_ml.json",),
            contract_resolver=ContractRefResolverV1(provider.contract_refs),
            catalog_digest=sha256_canonical([{"filename": "classification_ml.json", "contribution": provider.to_dict()}]),
        )
    registry = TrustedExecutorRegistry((contribution,))
    registry.bind_catalog(bind_catalog)
    return registry


def adapter_registry() -> dict[str, AdapterDeclarationV1]:
    return {model_id: adapter.declaration for model_id, adapter in _ADAPTERS.items()}


def get_classification_adapter(
    model_id: str,
    *,
    seed: int = 0,
    parameters: dict[str, Any] | None = None,
) -> ClassificationAdapterV1:
    adapter_type = _ADAPTERS.get(model_id)
    if adapter_type is None:
        raise ContractError("CLASSIFICATION_ADAPTER_UNKNOWN", f"unknown classification adapter {model_id!r}")
    return adapter_type(seed=seed, parameters=parameters)


__all__ = [
    "AdapterDeclarationV1",
    "CLASSIFICATION_EXECUTOR_REF",
    "CLASSIFICATION_PRODUCTION_ENTRYPOINT",
    "CLASSIFICATION_PROVIDER_ID",
    "CLASSIFICATION_RUNTIME_ADAPTER_ID",
    "ClassificationAdapterV1",
    "LogisticRegressionAdapterV1",
    "RandomForestAdapterV1",
    "adapter_registry",
    "classification_runtime_registry",
    "get_classification_adapter",
]
