from __future__ import annotations

import time

import pandas as pd
import pytest


def _frame() -> tuple[pd.DataFrame, pd.Series]:
    return (
        pd.DataFrame(
            {
                "x1": [0.0, 0.2, 1.0, 1.2, 0.1, 1.1],
                "x2": [1.0, 1.2, 0.0, 0.2, 0.8, 0.1],
            }
        ),
        pd.Series([0, 0, 1, 1, 0, 1]),
    )


def _input(
    catalog_digest: str,
    *,
    model_id: str = "logistic_regression",
    expires_at: float | None = None,
    actor_ref: str = "workbench.server.classification",
):
    import workbench.predictive_research.classification_adapters as module
    from workbench.predictive_research.classification_adapters import ClassificationInputV1

    return ClassificationInputV1.from_server(
        input_ref="classification-input:test-snapshot",
        catalog_digest=catalog_digest,
        actor_ref=actor_ref,
        project_ref="project:test",
        session_ref="session:test",
        snapshot_ref="snapshot:test",
        model_id=model_id,
        expires_at=time.time() + 60 if expires_at is None else expires_at,
        _issuer=module._CLASSIFICATION_SERVER_OWNED_ISSUER,
    )


def test_classification_input_and_port_require_the_private_server_issuer() -> None:
    import workbench.predictive_research.classification_adapters as module
    from workbench.predictive_research.classification_adapters import (
        ClassificationExecutionPortV1,
        ClassificationInputV1,
    )

    with pytest.raises(TypeError, match="server-owned issuer"):
        ClassificationInputV1.from_server(
            input_ref="classification-input:forged",
            catalog_digest="a" * 64,
            actor_ref="workbench.server.classification",
            project_ref="project:test",
            session_ref="session:test",
            snapshot_ref="snapshot:test",
            model_id="logistic_regression",
            expires_at=time.time() + 60,
            _issuer=object(),
        )

    with pytest.raises(TypeError, match="server-owned issuer"):
        ClassificationExecutionPortV1.from_server(
            _input("a" * 64),
            catalog_digest="a" * 64,
            resolver=lambda _input: _frame(),
            _issuer=object(),
        )

    assert module._CLASSIFICATION_SERVER_OWNED_ISSUER is not None


def test_classification_digest_fields_require_lowercase_sha256_hex() -> None:
    import workbench.predictive_research.classification_adapters as module
    from workbench.predictive_research.classification_adapters import ClassificationInputV1

    with pytest.raises(ValueError, match="SHA-256|digest"):
        ClassificationInputV1.from_server(
            input_ref="classification-input:bad-digest",
            catalog_digest="z" * 64,
            actor_ref="workbench.server.classification",
            project_ref="project:test",
            session_ref="session:test",
            snapshot_ref="snapshot:test",
            model_id="logistic_regression",
            expires_at=time.time() + 60,
            _issuer=module._CLASSIFICATION_SERVER_OWNED_ISSUER,
        )


def test_classification_result_validator_rejects_forged_digest_and_accuracy() -> None:
    import workbench.predictive_research.classification_adapters as module
    from workbench.agent.trusted_executor_registry import TrustedExecutorRegistryError

    result = {
        "model_id": "logistic_regression",
        "sample_count": 6,
        "feature_count": 2,
        "class_count": 2,
        "metrics": {"accuracy": 1.2},
        "result_digest": "f" * 64,
        "catalog_digest": "a" * 64,
        "project_ref": "project:test",
        "session_ref": "session:test",
        "snapshot_ref": "snapshot:test",
    }

    with pytest.raises(TrustedExecutorRegistryError, match="result|accuracy|digest"):
        module._validate_classification_host_result(result)


def test_classification_result_validator_recomputes_a_well_formed_but_forged_digest() -> None:
    import workbench.predictive_research.classification_adapters as module
    from workbench.agent.trusted_executor_registry import TrustedExecutorRegistryError

    result = {
        "model_id": "logistic_regression",
        "sample_count": 4,
        "feature_count": 2,
        "class_count": 2,
        "metrics": {"accuracy": 0.5},
        "result_digest": "f" * 64,
        "catalog_digest": "a" * 64,
        "project_ref": "project:classification",
        "session_ref": "session:classification",
        "snapshot_ref": "snapshot:classification",
    }

    with pytest.raises(TrustedExecutorRegistryError, match="result_digest|summary"):
        module._validate_classification_host_result(result)


@pytest.mark.parametrize(
    "context_overrides",
    (
        {"actor_ref": "attacker:classification"},
        {"effect": "write"},
        {"evidence_required": False},
    ),
)
def test_classification_port_binds_actor_read_only_effect_and_evidence(context_overrides) -> None:
    import workbench.predictive_research.classification_adapters as module
    from workbench.agent.trusted_executor_registry import ProviderRuntimeContextV1
    from workbench.predictive_research.classification_adapters import (
        ClassificationExecutionPortV1,
        build_classification_runtime_contribution,
    )
    from workbench.providers.catalog import load_builtin_catalog

    catalog = load_builtin_catalog()
    typed_input = _input(catalog.catalog_digest)
    port = ClassificationExecutionPortV1.from_server(
        typed_input,
        catalog_digest=catalog.catalog_digest,
        resolver=lambda _input: _frame(),
        _issuer=module._CLASSIFICATION_SERVER_OWNED_ISSUER,
    )
    contribution = build_classification_runtime_contribution(catalog, execution_port=port)
    context_values = {
        "compilation_record_id": "classification:authority",
        "execution_instance_hash": "classification-execution:authority",
        "actor_ref": "workbench.server.classification",
        "session_ref": "session:test",
        "project_ref": "project:test",
        "effect": "read_only",
        "evidence_required": True,
    }
    context_values.update(context_overrides)

    with pytest.raises(ValueError, match="actor|effect|evidence|read_only"):
        contribution.executor(
            ProviderRuntimeContextV1(**context_values),
            {"input_ref": typed_input.input_ref, "model_id": typed_input.model_id},
        )


def test_classification_result_validator_binds_result_to_the_issued_input() -> None:
    import workbench.predictive_research.classification_adapters as module
    from workbench.agent.trusted_executor_registry import ProviderRuntimeContextV1, TrustedExecutorRegistryError
    from workbench.canonical import sha256_canonical
    from workbench.predictive_research.classification_adapters import (
        ClassificationExecutionPortV1,
        build_classification_runtime_contribution,
    )
    from workbench.providers.catalog import load_builtin_catalog

    catalog = load_builtin_catalog()
    typed_input = _input(catalog.catalog_digest)
    port = ClassificationExecutionPortV1.from_server(
        typed_input,
        catalog_digest=catalog.catalog_digest,
        resolver=lambda _input: _frame(),
        _issuer=module._CLASSIFICATION_SERVER_OWNED_ISSUER,
    )
    contribution = build_classification_runtime_contribution(catalog, execution_port=port)
    result = dict(
        contribution.executor(
            ProviderRuntimeContextV1(
                compilation_record_id="classification:identity",
                execution_instance_hash="classification-execution:identity",
                actor_ref="workbench.server.classification",
                session_ref="session:test",
                project_ref="project:test",
                effect="read_only",
            ),
            {"input_ref": typed_input.input_ref, "model_id": typed_input.model_id},
        )
    )
    result["model_id"] = "random_forest"
    result["result_digest"] = sha256_canonical(
        {key: value for key, value in result.items() if key != "result_digest"}
    )

    with pytest.raises(TrustedExecutorRegistryError, match="identity|model|scope|input"):
        contribution.result_validator(result)


def test_missing_port_is_explicitly_unavailable() -> None:
    from workbench.predictive_research.classification_adapters import build_classification_runtime_contribution
    from workbench.providers.catalog import load_builtin_catalog

    contribution = build_classification_runtime_contribution(load_builtin_catalog())

    assert contribution.execution_allowed is False
    assert contribution.metadata["status"] == "unavailable"


@pytest.mark.parametrize("model_id", ("logistic_regression", "random_forest"))
def test_exact_server_port_fits_inside_host_and_returns_only_bounded_summary(model_id: str) -> None:
    import workbench.predictive_research.classification_adapters as module
    from workbench.agent.trusted_executor_registry import ProviderRuntimeContextV1
    from workbench.predictive_research.classification_adapters import (
        ClassificationExecutionPortV1,
        build_classification_runtime_contribution,
    )
    from workbench.providers.catalog import load_builtin_catalog

    catalog = load_builtin_catalog()
    features, target = _frame()
    typed_input = _input(catalog.catalog_digest, model_id=model_id)
    port = ClassificationExecutionPortV1.from_server(
        typed_input,
        catalog_digest=catalog.catalog_digest,
        resolver=lambda _input: (features, target),
        _issuer=module._CLASSIFICATION_SERVER_OWNED_ISSUER,
    )
    contribution = build_classification_runtime_contribution(catalog, execution_port=port)
    context = ProviderRuntimeContextV1(
        compilation_record_id="classification:test",
        execution_instance_hash="classification-execution:test",
        actor_ref="workbench.server.classification",
        session_ref="session:test",
        project_ref="project:test",
        effect="read_only",
    )

    result = contribution.executor(
        context,
        {"input_ref": typed_input.input_ref, "model_id": model_id},
    )

    assert contribution.execution_allowed is True
    assert set(result) == {
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
    assert result["model_id"] == model_id
    assert result["sample_count"] == len(features)
    assert result["feature_count"] == len(features.columns)
    assert "accuracy" in result["metrics"]
    assert "features" not in result
    assert "rows" not in result
    assert "frame" not in result


@pytest.mark.parametrize(
    "mutation",
    ("catalog_digest", "project_ref", "session_ref", "snapshot_ref", "model_id", "expired"),
)
def test_port_fails_closed_on_digest_scope_model_or_expiry_mismatch(mutation: str) -> None:
    import workbench.predictive_research.classification_adapters as module
    from workbench.agent.trusted_executor_registry import ProviderRuntimeContextV1, TrustedExecutorRegistryError
    from workbench.predictive_research.classification_adapters import (
        ClassificationExecutionPortV1,
        build_classification_runtime_contribution,
    )
    from workbench.providers.catalog import load_builtin_catalog

    catalog = load_builtin_catalog()
    typed_input = _input(catalog.catalog_digest)
    port = ClassificationExecutionPortV1.from_server(
        typed_input,
        catalog_digest=catalog.catalog_digest,
        resolver=lambda _input: _frame(),
        _issuer=module._CLASSIFICATION_SERVER_OWNED_ISSUER,
    )
    contribution = build_classification_runtime_contribution(catalog, execution_port=port)
    context = ProviderRuntimeContextV1(
        compilation_record_id="classification:test",
        execution_instance_hash="classification-execution:test",
        actor_ref="workbench.server.classification",
        session_ref="session:test",
        project_ref="project:test",
        effect="read_only",
    )
    request = {"input_ref": typed_input.input_ref, "model_id": typed_input.model_id}
    if mutation == "catalog_digest":
        request["catalog_digest"] = "f" * 64
    elif mutation == "project_ref":
        request["project_ref"] = "project:other"
    elif mutation == "session_ref":
        request["session_ref"] = "session:other"
    elif mutation == "snapshot_ref":
        request["snapshot_ref"] = "snapshot:other"
    elif mutation == "model_id":
        request["model_id"] = "random_forest"
    else:
        expired = _input(catalog.catalog_digest, expires_at=0.0)
        port = ClassificationExecutionPortV1.from_server(
            expired,
            catalog_digest=catalog.catalog_digest,
            resolver=lambda _input: _frame(),
            _issuer=module._CLASSIFICATION_SERVER_OWNED_ISSUER,
        )
        contribution = build_classification_runtime_contribution(catalog, execution_port=port)
        request["input_ref"] = expired.input_ref

    with pytest.raises((ValueError, TrustedExecutorRegistryError), match="scope|digest|model|expired|stale|input|typed"):
        contribution.executor(context, request)
