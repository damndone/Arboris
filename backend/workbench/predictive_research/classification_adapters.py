"""Typed Logistic Regression and Random Forest adapters.

Adapters own estimator construction only.  Split selection, preprocessing,
calibration and policy decisions remain in the classification protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Callable
import math
import re
import time
import warnings
import weakref

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


# The registry object, not a caller-controlled digest or a copied set of
# declaration strings, is the authority marker for this production join. A
# weak map avoids putting a mutable marker on the registry itself, while still
# allowing the entrypoint to verify the exact contribution installed by this
# factory before it dispatches.
_CLASSIFICATION_TRUSTED_REGISTRIES: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


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


_CLASSIFICATION_SERVER_OWNED_ISSUER = object()
_CLASSIFICATION_SERVER_OWNED_CAPABILITY = object()
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def _classification_text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _classification_sha256_digest(value: object, name: str) -> str:
    if type(value) is not str or _SHA256_HEX_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True)
class ClassificationInputV1:
    """Opaque, server-issued identity for one classification snapshot."""

    input_ref: str
    catalog_digest: str
    actor_ref: str
    project_ref: str
    session_ref: str
    snapshot_ref: str
    model_id: str
    expires_at: float
    _capability: object | None = dataclass_field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        for name in (
            "input_ref",
            "actor_ref",
            "project_ref",
            "session_ref",
            "snapshot_ref",
            "model_id",
        ):
            _classification_text(getattr(self, name), name)
        _classification_sha256_digest(self.catalog_digest, "classification input catalog_digest")
        if type(self.expires_at) is not float or not math.isfinite(self.expires_at):
            raise ValueError("classification input expires_at must be finite")
        if self._capability is not _CLASSIFICATION_SERVER_OWNED_CAPABILITY:
            raise TypeError("classification input can only be created by the server-owned issuer")
        if self.model_id not in _ADAPTERS:
            raise ValueError("classification input model_id is unsupported")

    @classmethod
    def from_server(
        cls,
        *,
        input_ref: str,
        catalog_digest: str,
        actor_ref: str,
        project_ref: str,
        session_ref: str,
        snapshot_ref: str,
        model_id: str,
        expires_at: float,
        _issuer: object | None = None,
    ) -> "ClassificationInputV1":
        if _issuer is not _CLASSIFICATION_SERVER_OWNED_ISSUER:
            raise TypeError("classification input requires the server-owned issuer")
        return cls(
            input_ref=input_ref,
            catalog_digest=catalog_digest,
            actor_ref=actor_ref,
            project_ref=project_ref,
            session_ref=session_ref,
            snapshot_ref=snapshot_ref,
            model_id=model_id,
            expires_at=expires_at,
            _capability=_CLASSIFICATION_SERVER_OWNED_CAPABILITY,
        )


@dataclass(frozen=True)
class ClassificationOutputV1:
    """Bounded server output; raw feature material never crosses this type."""

    model_id: str
    sample_count: int
    feature_count: int
    class_count: int
    metrics: Mapping[str, float]
    result_digest: str
    catalog_digest: str
    project_ref: str
    session_ref: str
    snapshot_ref: str
    _capability: object | None = dataclass_field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _classification_text(self.model_id, "model_id")
        for name in ("sample_count", "feature_count", "class_count"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if type(self.metrics) is not dict or set(self.metrics) != {"accuracy"}:
            raise ValueError("classification output metrics are not bounded")
        if type(self.metrics["accuracy"]) is not float or not math.isfinite(self.metrics["accuracy"]):
            raise ValueError("classification output accuracy must be finite")
        for name in ("catalog_digest", "project_ref", "session_ref", "snapshot_ref", "result_digest"):
            _classification_text(getattr(self, name), name)
        _classification_sha256_digest(self.catalog_digest, "classification output catalog_digest")
        _classification_sha256_digest(self.result_digest, "classification output result_digest")
        if not 0.0 <= self.metrics["accuracy"] <= 1.0:
            raise ValueError("classification output accuracy must be between zero and one")
        if self._capability is not _CLASSIFICATION_SERVER_OWNED_CAPABILITY:
            raise TypeError("classification output can only be created by the server-owned issuer")
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))

    def to_dict(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "sample_count": self.sample_count,
            "feature_count": self.feature_count,
            "class_count": self.class_count,
            "metrics": dict(self.metrics),
            "result_digest": self.result_digest,
            "catalog_digest": self.catalog_digest,
            "project_ref": self.project_ref,
            "session_ref": self.session_ref,
            "snapshot_ref": self.snapshot_ref,
        }

    @classmethod
    def from_server(cls, **kwargs: object) -> "ClassificationOutputV1":
        if kwargs.pop("_issuer", None) is not _CLASSIFICATION_SERVER_OWNED_ISSUER:
            raise TypeError("classification output requires the server-owned issuer")
        return cls(**kwargs, _capability=_CLASSIFICATION_SERVER_OWNED_CAPABILITY)


@dataclass(frozen=True)
class ClassificationExecutionPortV1:
    """Server-issued host boundary that resolves and fits one typed input."""

    input: ClassificationInputV1
    catalog_digest: str
    _resolver: Callable[[ClassificationInputV1], tuple[pd.DataFrame, Any]]
    _capability: object | None = dataclass_field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.input) is not ClassificationInputV1:
            raise TypeError("classification execution port requires typed server input")
        if self.catalog_digest != self.input.catalog_digest:
            raise ValueError("classification execution port catalog digest does not match input")
        if not callable(self._resolver):
            raise TypeError("classification execution port requires a host resolver")
        if self._capability is not _CLASSIFICATION_SERVER_OWNED_CAPABILITY:
            raise TypeError("classification execution port can only be created by the server-owned issuer")

    @classmethod
    def from_server(
        cls,
        input: ClassificationInputV1,
        *,
        catalog_digest: str,
        resolver: Callable[[ClassificationInputV1], tuple[pd.DataFrame, Any]],
        _issuer: object | None = None,
    ) -> "ClassificationExecutionPortV1":
        if _issuer is not _CLASSIFICATION_SERVER_OWNED_ISSUER:
            raise TypeError("classification execution port requires the server-owned issuer")
        return cls(
            input=input,
            catalog_digest=catalog_digest,
            _resolver=resolver,
            _capability=_CLASSIFICATION_SERVER_OWNED_CAPABILITY,
        )

    def execute(self, context: Any, request: Mapping[str, Any]) -> dict[str, object]:
        from workbench.agent.trusted_executor_registry import ProviderRuntimeContextV1

        if type(context) is not ProviderRuntimeContextV1:
            raise ValueError("classification execution port requires a server runtime context")
        if set(request) != {"input_ref", "model_id"}:
            raise ValueError("classification execution request is not typed")
        if request["input_ref"] != self.input.input_ref or request["model_id"] != self.input.model_id:
            raise ValueError("classification execution input identity mismatch")
        if (
            context.actor_ref != self.input.actor_ref
            or context.project_ref != self.input.project_ref
            or context.session_ref != self.input.session_ref
        ):
            raise ValueError("classification execution actor/scope mismatch")
        if context.effect not in {"read", "read_only"}:
            raise ValueError("classification execution requires a read-only effect")
        if context.evidence_required is not True:
            raise ValueError("classification execution requires evidence")
        if self.input.expires_at <= time.time():
            raise ValueError("classification execution input is expired")
        features, target = self._resolver(self.input)
        adapter = get_classification_adapter(self.input.model_id)
        adapter.fit(features, target)
        predicted = adapter.estimator.predict(_numeric_matrix(features))
        accuracy = float(np.mean(predicted == np.asarray(target)))
        summary = {
            "model_id": self.input.model_id,
            "sample_count": len(features),
            "feature_count": len(features.columns),
            "class_count": len(adapter.metadata["class_order"]),
            "metrics": {"accuracy": accuracy},
            "catalog_digest": self.catalog_digest,
            "project_ref": self.input.project_ref,
            "session_ref": self.input.session_ref,
            "snapshot_ref": self.input.snapshot_ref,
        }
        output = ClassificationOutputV1.from_server(
            **summary,
            result_digest=sha256_canonical(summary),
            _issuer=_CLASSIFICATION_SERVER_OWNED_ISSUER,
        )
        return output.to_dict()


def _classification_provider_declaration(catalog: Any) -> tuple[Any, Any]:
    from workbench.agent.trusted_executor_registry import TrustedExecutorRegistryError
    from workbench.providers.catalog import ProviderCatalogV1, is_server_owned_catalog

    if type(catalog) is not ProviderCatalogV1:
        raise TrustedExecutorRegistryError(
            "CLASSIFICATION_PROVIDER_CATALOG_REQUIRED",
            "classification runtime requires the server-loaded ProviderCatalogV1",
        )
    if not is_server_owned_catalog(catalog):
        raise TrustedExecutorRegistryError(
            "CLASSIFICATION_PROVIDER_CATALOG_INVALID",
            "classification provider catalog is not the exact server-issued catalog",
        )

    providers = catalog.providers
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
        raise TrustedExecutorRegistryError(
            "RUNTIME_REQUEST_INVALID",
            "classification runtime request must be a mapping",
        )
    allowed = {
        "capability_id",
        "target_ref",
        "data_snapshot_ref",
        "source_text_digest",
        "options",
        "input_ref",
        "model_id",
    }
    unknown = sorted(set(request) - allowed)
    if unknown:
        raise TrustedExecutorRegistryError(
            "RUNTIME_REQUEST_INVALID",
            f"classification runtime request has unsupported field(s): {', '.join(unknown)}",
        )
    options = request.get("options")
    if options is not None and not isinstance(options, Mapping):
        raise TrustedExecutorRegistryError("RUNTIME_REQUEST_INVALID", "classification options must be a mapping")
    model_id = request.get("model_id")
    if model_id is None and isinstance(options, Mapping):
        model_id = options.get("model_id")
    if type(model_id) is not str or model_id not in _ADAPTERS:
        raise TrustedExecutorRegistryError("RUNTIME_REQUEST_INVALID", "classification runtime request has an unsupported model_id")
    input_ref = request.get("input_ref")
    if input_ref is None and isinstance(options, Mapping):
        input_ref = options.get("input_ref")
    if input_ref is None:
        input_ref = request.get("data_snapshot_ref")
    if type(input_ref) is not str or not input_ref:
        raise TrustedExecutorRegistryError("RUNTIME_REQUEST_INVALID", "classification input_ref is required")
    return {"input_ref": input_ref, "model_id": model_id}


def _validate_legacy_classification_runtime_request(request: Mapping[str, Any]) -> Mapping[str, Any]:
    from workbench.agent.trusted_executor_registry import TrustedExecutorRegistryError

    if not isinstance(request, Mapping) or set(request) != {"model_id"}:
        raise TrustedExecutorRegistryError("RUNTIME_REQUEST_INVALID", "legacy classification runtime request is invalid")
    model_id = request.get("model_id")
    if type(model_id) is not str or model_id not in _ADAPTERS:
        raise TrustedExecutorRegistryError("RUNTIME_REQUEST_INVALID", "classification runtime request has an unsupported model_id")
    return {"model_id": model_id}


def _blocked_classification_executor(_context: Any, _request: Mapping[str, Any]) -> Mapping[str, Any]:
    from workbench.agent.trusted_executor_registry import TrustedExecutorRegistryError

    raise TrustedExecutorRegistryError("RUNTIME_EXECUTION_BLOCKED", "classification execution port is unavailable")


def _execute_classification_host(
    context: Any,
    request: Mapping[str, Any],
    execution_port: ClassificationExecutionPortV1,
) -> Mapping[str, Any]:
    return execution_port.execute(context, request)


def _validate_classification_host_result(result: Mapping[str, Any]) -> None:
    from workbench.agent.trusted_executor_registry import TrustedExecutorRegistryError

    expected = {
        "model_id",
        "sample_count",
        "feature_count",
        "class_count",
        "metrics",
        "result_digest",
        "catalog_digest",
        "project_ref",
        "session_ref",
        "snapshot_ref",
    }
    if not isinstance(result, Mapping) or set(result) != expected:
        raise TrustedExecutorRegistryError("RUNTIME_RESULT_INVALID", "classification result is not bounded")
    if any(key in result for key in ("frame", "rows", "path", "features", "target")):
        raise TrustedExecutorRegistryError("RUNTIME_RESULT_INVALID", "classification result contains raw data")
    try:
        ClassificationOutputV1.from_server(**dict(result), _issuer=_CLASSIFICATION_SERVER_OWNED_ISSUER)
    except (TypeError, ValueError) as exc:
        raise TrustedExecutorRegistryError("RUNTIME_RESULT_INVALID", str(exc)) from exc
    summary = dict(result)
    supplied_digest = summary.pop("result_digest")
    expected_digest = sha256_canonical(summary)
    if supplied_digest != expected_digest:
        raise TrustedExecutorRegistryError(
            "RUNTIME_RESULT_INVALID",
            "classification result_digest does not match the bounded result summary",
        )


@dataclass(frozen=True)
class _ClassificationHostResultValidatorV1:
    """Bind a bounded result to the exact input issued for one host port."""

    input: ClassificationInputV1

    def __call__(self, result: Mapping[str, Any]) -> None:
        from workbench.agent.trusted_executor_registry import TrustedExecutorRegistryError

        _validate_classification_host_result(result)
        expected = {
            "model_id": self.input.model_id,
            "catalog_digest": self.input.catalog_digest,
            "project_ref": self.input.project_ref,
            "session_ref": self.input.session_ref,
            "snapshot_ref": self.input.snapshot_ref,
        }
        if any(result.get(key) != value for key, value in expected.items()):
            raise TrustedExecutorRegistryError(
                "RUNTIME_RESULT_INVALID",
                "classification result identity does not match the issued input",
            )


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


def build_classification_runtime_contribution(
    catalog: Any,
    execution_port: ClassificationExecutionPortV1 | None = None,
) -> ProviderRuntimeContributionV1:
    """Build the server-owned classification contribution for *catalog*.

    The returned contribution is intentionally unbound.  A bootstrapper may
    compose it with contributions from the complete provider catalog and let
    ``TrustedExecutorRegistry.bind_catalog`` perform the one-to-one join.
    """

    from workbench.agent.trusted_executor_registry import (
        ProviderRuntimeContributionV1,
        TrustedExecutorRegistryError,
    )

    provider, declaration = _classification_provider_declaration(catalog)
    if execution_port is not None:
        if type(execution_port) is not ClassificationExecutionPortV1:
            raise TrustedExecutorRegistryError("CLASSIFICATION_EXECUTION_PORT_REQUIRED")
        if execution_port.catalog_digest != catalog.catalog_digest:
            raise TrustedExecutorRegistryError("CLASSIFICATION_EXECUTION_PORT_CATALOG_MISMATCH")
        executor = lambda context, request: _execute_classification_host(context, request, execution_port)
        execution_allowed = True
        result_validator = _ClassificationHostResultValidatorV1(execution_port.input)
        metadata = {
            "status": "available",
            "production_entrypoint": CLASSIFICATION_PRODUCTION_ENTRYPOINT,
            "provider_id": CLASSIFICATION_PROVIDER_ID,
            "adapter_id": CLASSIFICATION_RUNTIME_ADAPTER_ID,
        }
    else:
        executor = _blocked_classification_executor
        execution_allowed = False
        result_validator = _validate_classification_host_result
        metadata = {
            "status": "unavailable",
            "reason_code": "CLASSIFICATION_EXECUTION_PORT_UNAVAILABLE",
            "production_entrypoint": CLASSIFICATION_PRODUCTION_ENTRYPOINT,
            "provider_id": CLASSIFICATION_PROVIDER_ID,
            "adapter_id": CLASSIFICATION_RUNTIME_ADAPTER_ID,
        }
    return ProviderRuntimeContributionV1(
        provider_id=provider.provider_id,
        adapter_id=declaration.adapter_id,
        executor_ref=declaration.executor_ref,
        owner="workbench.server.classification",
        signature="workbench.classification_ml.runtime.v1",
        effect="read_only",
        request_contract_ref=declaration.request_schema_ref,
        result_contract_refs=declaration.output_refs,
        executor=executor,
        request_validator=_validate_classification_runtime_request,
        result_validator=result_validator,
        execution_allowed=execution_allowed,
        metadata=metadata,
    )


def classification_runtime_registry(catalog: Any | None = None) -> TrustedExecutorRegistry:
    """Build the server-owned classification runtime join.

    The JSON manifest contributes only opaque contract identities.  This
    factory supplies the trusted callable and binds it to the fixed builtin
    catalog before a production entrypoint may accept the registry.
    """

    from workbench.agent.trusted_executor_registry import TrustedExecutorRegistry, TrustedExecutorRegistryError

    source_catalog = load_builtin_catalog() if catalog is None else catalog
    contribution = build_classification_runtime_contribution(source_catalog)
    contribution = replace(
        contribution,
        executor=_execute_classification_runtime_binding,
        request_validator=_validate_legacy_classification_runtime_request,
        result_validator=_validate_classification_runtime_result,
        execution_allowed=True,
        metadata={
            "production_entrypoint": CLASSIFICATION_PRODUCTION_ENTRYPOINT,
            "provider_id": CLASSIFICATION_PROVIDER_ID,
            "adapter_id": CLASSIFICATION_RUNTIME_ADAPTER_ID,
        },
    )
    provider, _declaration = _classification_provider_declaration(source_catalog)
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
    bound_digest = getattr(registry, "_bound_catalog_digest", None)
    if type(bound_digest) is not str or not bound_digest:
        raise TrustedExecutorRegistryError(
            "CLASSIFICATION_PROVIDER_DECLARATION_INVALID",
            "classification runtime catalog did not produce a bound digest",
        )
    _CLASSIFICATION_TRUSTED_REGISTRIES[registry] = (contribution, bound_digest)
    return registry


def server_owned_classification_runtime_registry() -> TrustedExecutorRegistry:
    """Return the only registry seam used by the production entrypoint."""

    return classification_runtime_registry()


def dispatch_classification_runtime_binding(
    runtime_registry: Any,
    *,
    task_hash: str,
) -> dict[str, Any]:
    """Validate and dispatch the server-owned classification runtime join."""

    from workbench.agent.trusted_executor_registry import (
        ProviderRuntimeContextV1,
        TrustedExecutorRegistry,
        TrustedExecutorRegistryError,
    )

    if type(runtime_registry) is not TrustedExecutorRegistry:
        raise TrustedExecutorRegistryError(
            "CLASSIFICATION_PROVIDER_RUNTIME_JOIN_REQUIRED",
            "production classification requires the factory-created TrustedExecutorRegistry",
        )
    trusted_binding = _CLASSIFICATION_TRUSTED_REGISTRIES.get(runtime_registry)
    try:
        contribution = runtime_registry.require(CLASSIFICATION_EXECUTOR_REF)
    except TrustedExecutorRegistryError as exc:
        raise TrustedExecutorRegistryError(
            "CLASSIFICATION_PROVIDER_RUNTIME_JOIN_REQUIRED",
            str(exc),
        ) from exc
    bound_digest = getattr(runtime_registry, "_bound_catalog_digest", None)
    if (
        trusted_binding is None
        or contribution is not trusted_binding[0]
        or bound_digest != trusted_binding[1]
        or contribution.provider_id != CLASSIFICATION_PROVIDER_ID
        or contribution.adapter_id != CLASSIFICATION_RUNTIME_ADAPTER_ID
        or contribution.executor_ref != CLASSIFICATION_EXECUTOR_REF
        or contribution.owner != "workbench.server.classification"
        or contribution.signature != "workbench.classification_ml.runtime.v1"
        or contribution.effect != "read_only"
        or contribution.executor is not _execute_classification_runtime_binding
            or contribution.request_validator not in {
                _validate_classification_runtime_request,
                _validate_legacy_classification_runtime_request,
            }
        or contribution.result_validator is not _validate_classification_runtime_result
        or dict(contribution.metadata) != {
            "production_entrypoint": CLASSIFICATION_PRODUCTION_ENTRYPOINT,
            "provider_id": CLASSIFICATION_PROVIDER_ID,
            "adapter_id": CLASSIFICATION_RUNTIME_ADAPTER_ID,
        }
    ):
        raise TrustedExecutorRegistryError(
            "CLASSIFICATION_PROVIDER_RUNTIME_JOIN_MISMATCH",
            "catalog declaration, trusted contribution, registry identity, and executor implementation disagree",
        )

    context = ProviderRuntimeContextV1(
        compilation_record_id=f"classification-production:{task_hash}",
        execution_instance_hash=f"classification-runtime:{task_hash}",
        actor_ref="workbench.server.classification",
        session_ref=CLASSIFICATION_PRODUCTION_ENTRYPOINT,
        project_ref=f"classification-project:{task_hash}",
        effect="read_only",
        evidence_required=True,
    )
    try:
        result = runtime_registry.dispatch(
            CLASSIFICATION_EXECUTOR_REF,
            context,
            {"model_id": "logistic_regression"},
            catalog_digest=bound_digest,
        )
    except TrustedExecutorRegistryError:
        raise
    if (
        result.get("provider_id") != CLASSIFICATION_PROVIDER_ID
        or result.get("adapter_id") != CLASSIFICATION_RUNTIME_ADAPTER_ID
        or result.get("executor_ref") != CLASSIFICATION_EXECUTOR_REF
        or result.get("production_entrypoint") != CLASSIFICATION_PRODUCTION_ENTRYPOINT
        or result.get("execution_instance_hash") != context.execution_instance_hash
    ):
        raise TrustedExecutorRegistryError(
            "CLASSIFICATION_PROVIDER_RUNTIME_JOIN_MISMATCH",
            "classification runtime dispatch returned an inconsistent identity",
        )
    return result


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
    "ClassificationExecutionPortV1",
    "ClassificationInputV1",
    "ClassificationOutputV1",
    "LogisticRegressionAdapterV1",
    "RandomForestAdapterV1",
    "adapter_registry",
    "build_classification_runtime_contribution",
    "classification_runtime_registry",
    "dispatch_classification_runtime_binding",
    "get_classification_adapter",
    "server_owned_classification_runtime_registry",
]
